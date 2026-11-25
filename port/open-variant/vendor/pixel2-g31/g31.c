/* SPDX-License-Identifier: Apache-2.0 */
#define _FILE_OFFSET_BITS 64
#include "g31.h"
#include "shader_abi.h"

#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
#include "panfrost_drm.h"
#include "v7_pack.h"
#include "g31_program.h"

enum kernel_id { SCALAR, TILE_90, TILE_270, KERNEL_COUNT };
_Static_assert(G31_GROUP_X == 8 && G31_GROUP_Y == 8, "Bifrost grid packing uses 8x8 local groups");
static const struct {
    const uint32_t *code, *state;
    size_t bytes;
} kernels[KERNEL_COUNT] = {
    [SCALAR] = { scalar_code, scalar_state, sizeof(scalar_code) },
    [TILE_90] = { cw90_code, cw90_state, sizeof(cw90_code) },
    [TILE_270] = { cw270_code, cw270_state, sizeof(cw270_code) },
};

struct g31_bo {
    uint32_t handle;
    uint64_t gpu;
    void *mapping;
    size_t bytes;
};

enum { ASYNC_SLOTS = 3 };
struct async_slot {
    struct g31_bo command;
    uint32_t sync;
    bool pending;
};

struct g31_device {
    int fd;
    pthread_mutex_t submit_lock;
    bool lost;
    struct g31_bo code[KERNEL_COUNT];
    struct g31_bo command;
    struct g31_surface *surfaces;
    struct async_slot slots[ASYNC_SLOTS];
    unsigned next_slot;
};

struct g31_surface {
    struct g31_device *device;
    struct g31_bo pixels;
    uint32_t width, height, stride;
    struct g31_surface *next;
};

/* Align each descriptor at the boundary required by Bifrost. */
struct command_block {
    _Alignas(MALI_COMPUTE_JOB_ALIGN) uint8_t job[MALI_COMPUTE_JOB_LENGTH];
    _Alignas(MALI_RENDERER_STATE_ALIGN) uint8_t state[KERNEL_COUNT][MALI_RENDERER_STATE_LENGTH];
    _Alignas(MALI_LOCAL_STORAGE_ALIGN) uint8_t tls[MALI_LOCAL_STORAGE_LENGTH];
    _Alignas(16) struct g31_uniforms uniforms;
};

static int drm_call(int fd, unsigned long request, void *argument)
{
    int result;
    do {
        result = ioctl(fd, request, argument);
    } while (result < 0 && errno == EINTR);
    return result;
}

static void release_bo(int fd, struct g31_bo *bo)
{
    if (bo->mapping) munmap(bo->mapping, bo->bytes);
    if (bo->handle) {
        struct drm_gem_close close_bo = { .handle = bo->handle };
        drm_call(fd, DRM_IOCTL_GEM_CLOSE, &close_bo);
    }
    *bo = (struct g31_bo){0};
}

static int allocate_bo(int fd, struct g31_bo *bo, uint32_t bytes, uint32_t flags)
{
    struct drm_panfrost_create_bo create = { .size = bytes, .flags = flags };
    if (drm_call(fd, DRM_IOCTL_PANFROST_CREATE_BO, &create) < 0) return -1;
    bo->handle = create.handle;
    bo->gpu = create.offset;
    bo->bytes = bytes;
    struct drm_panfrost_mmap_bo map = { .handle = create.handle };
    if (drm_call(fd, DRM_IOCTL_PANFROST_MMAP_BO, &map) == 0) {
        void *address = mmap(NULL, bytes, PROT_READ | PROT_WRITE, MAP_SHARED, fd, map.offset);
        if (address != MAP_FAILED) {
            bo->mapping = address;
            return 0;
        }
    }
    int error = errno;
    release_bo(fd, bo);
    errno = error;
    return -1;
}

static int open_render_node(void)
{
    int last_error = ENODEV;
    for (unsigned minor = 128; minor < 192; ++minor) {
        char path[32], driver[32] = {0};
        snprintf(path, sizeof(path), "/dev/dri/renderD%u", minor);
        int fd = open(path, O_RDWR | O_CLOEXEC);
        if (fd < 0) {
            if (errno != ENOENT) last_error = errno;
            continue;
        }
        struct drm_version version = { .name = driver, .name_len = sizeof(driver) - 1 };
        if (drm_call(fd, DRM_IOCTL_VERSION, &version) == 0 && !strcmp(driver, "panfrost")) {
            struct drm_panfrost_get_param id = { .param = DRM_PANFROST_PARAM_GPU_PROD_ID };
            if (drm_call(fd, DRM_IOCTL_PANFROST_GET_PARAM, &id) != 0) last_error = errno;
            else if (id.value == 0x7093) return fd;
        }
        close(fd);
    }
    errno = last_error;
    return -1;
}

struct g31_device *g31_open(void)
{
    struct g31_device *dev = calloc(1, sizeof(*dev));
    if (!dev) return NULL;
    dev->fd = open_render_node();
    if (dev->fd < 0) {
        free(dev);
        return NULL;
    }
    int error = pthread_mutex_init(&dev->submit_lock, NULL);
    if (error) {
        close(dev->fd);
        free(dev);
        errno = error;
        return NULL;
    }
    if (allocate_bo(dev->fd, &dev->command, sizeof(struct command_block), PANFROST_BO_NOEXEC) < 0)
        goto fail;
    struct command_block *cmd = dev->command.mapping;
    for (unsigned k = 0; k < KERNEL_COUNT; ++k) {
        if (allocate_bo(dev->fd, &dev->code[k], kernels[k].bytes, 0) < 0) goto fail;
        memcpy(dev->code[k].mapping, kernels[k].code, kernels[k].bytes);
        pan_unpack((const uint8_t *)kernels[k].state, RENDERER_STATE, state);
        state.shader.shader = dev->code[k].gpu;
        MALI_RENDERER_STATE_pack((uint32_t *)cmd->state[k], &state);
    }
    pan_pack(cmd->tls, LOCAL_STORAGE, tls) {
        tls.wls_instances = MALI_LOCAL_STORAGE_NO_WORKGROUP_MEM;
    }
    pan_section_pack(cmd->job, COMPUTE_JOB, PARAMETERS, params) {
        /* ceil(log2(8+1)) + ceil(log2(8+1)) + ceil(log2(1+1)) */
        params.job_task_split = 9;
    }
    return dev;
fail:
    error = errno;
    g31_close(dev);
    errno = error;
    return NULL;
}

void g31_close(struct g31_device *dev)
{
    if (!dev) return;
    for (unsigned i = 0; i < ASYNC_SLOTS; ++i) {
        if (dev->slots[i].sync) {
            struct drm_syncobj_destroy sync = { .handle = dev->slots[i].sync };
            drm_call(dev->fd, DRM_IOCTL_SYNCOBJ_DESTROY, &sync);
        }
        release_bo(dev->fd, &dev->slots[i].command);
    }
    release_bo(dev->fd, &dev->command);
    for (unsigned k = 0; k < KERNEL_COUNT; ++k) release_bo(dev->fd, &dev->code[k]);
    pthread_mutex_destroy(&dev->submit_lock);
    close(dev->fd);
    free(dev);
}

static struct g31_surface *new_surface(struct g31_device *dev, uint32_t width,
                                       uint32_t height, uint32_t stride)
{
    if (!dev || !width || !height || width > 4096 || height > 4096 ||
        stride < width || stride > 8192) {
        errno = EINVAL;
        return NULL;
    }
    struct g31_surface *surface = calloc(1, sizeof(*surface));
    if (!surface) return NULL;
    surface->device = dev;
    surface->width = width;
    surface->height = height;
    surface->stride = stride;
    return surface;
}

/* PRIME returns the same GEM handle for repeated imports into a DRM file. */
static bool owns_handle(const struct g31_device *dev, uint32_t handle)
{
    for (const struct g31_surface *s = dev->surfaces; s; s = s->next)
        if (s->pixels.handle == handle) return true;
    return false;
}

static void add_surface(struct g31_surface *surface)
{
    surface->next = surface->device->surfaces;
    surface->device->surfaces = surface;
}

struct g31_surface *g31_create(struct g31_device *dev, uint32_t width,
                               uint32_t height, uint32_t stride)
{
    struct g31_surface *surface = new_surface(dev, width, height, stride);
    if (!surface) return NULL;
    if (allocate_bo(dev->fd, &surface->pixels, height * stride * 4, PANFROST_BO_NOEXEC) < 0) {
        free(surface);
        return NULL;
    }
    pthread_mutex_lock(&dev->submit_lock);
    add_surface(surface);
    pthread_mutex_unlock(&dev->submit_lock);
    return surface;
}

struct g31_surface *g31_import(struct g31_device *dev, int fd, uint32_t width,
                               uint32_t height, uint32_t stride, uint32_t offset)
{
    struct stat st;
    if (fstat(fd, &st) < 0) return NULL;
    struct g31_surface *surface = new_surface(dev, width, height, stride);
    if (!surface) return NULL;
    uint64_t required = offset + 4ull * ((uint64_t)(height - 1) * stride + width);
    if ((offset & 3) || st.st_size < 0 || required > (uint64_t)st.st_size) {
        free(surface);
        errno = EINVAL;
        return NULL;
    }
    pthread_mutex_lock(&dev->submit_lock);
    struct drm_prime_handle prime = { .fd = fd };
    if (drm_call(dev->fd, DRM_IOCTL_PRIME_FD_TO_HANDLE, &prime) < 0) goto fail;
    struct drm_panfrost_get_bo_offset address = { .handle = prime.handle };
    if (drm_call(dev->fd, DRM_IOCTL_PANFROST_GET_BO_OFFSET, &address) < 0) {
        int error = errno;
        if (!owns_handle(dev, prime.handle)) {
            struct drm_gem_close unused = { .handle = prime.handle };
            drm_call(dev->fd, DRM_IOCTL_GEM_CLOSE, &unused);
        }
        errno = error;
        goto fail;
    }
    surface->pixels.handle = prime.handle;
    surface->pixels.gpu = address.offset + offset;
    add_surface(surface);
    pthread_mutex_unlock(&dev->submit_lock);
    return surface;
fail: {
        int error = errno;
        pthread_mutex_unlock(&dev->submit_lock);
        free(surface);
        errno = error;
        return NULL;
    }
}

void g31_destroy(struct g31_surface *surface)
{
    if (surface) {
        struct g31_device *dev = surface->device;
        pthread_mutex_lock(&dev->submit_lock);
        struct g31_surface **link = &dev->surfaces;
        while (*link != surface) link = &(*link)->next;
        *link = surface->next;
        if (owns_handle(dev, surface->pixels.handle)) surface->pixels.handle = 0;
        release_bo(dev->fd, &surface->pixels);
        pthread_mutex_unlock(&dev->submit_lock);
        free(surface);
    }
}

uint32_t *g31_pixels(struct g31_surface *surface)
{
    return surface ? surface->pixels.mapping : NULL;
}

int g31_export(const struct g31_surface *surface)
{
    if (!surface) { errno = EINVAL; return -1; }
    struct drm_prime_handle prime = { .handle = surface->pixels.handle, .flags = DRM_CLOEXEC | DRM_RDWR };
    if (drm_call(surface->device->fd, DRM_IOCTL_PRIME_HANDLE_TO_FD, &prime) < 0) return -1;
    return prime.fd;
}

static void set_grid(uint8_t *job, uint32_t width, uint32_t height)
{
    uint32_t nx = (width + G31_GROUP_X - 1) / G31_GROUP_X;
    uint32_t ny = (height + G31_GROUP_Y - 1) / G31_GROUP_Y;
    unsigned xbits = nx > 1 ? 32u - __builtin_clz(nx - 1) : 0;
    unsigned ybits = ny > 1 ? 32u - __builtin_clz(ny - 1) : 0;
    /* Local X and Y occupy bits 0..2 and 3..5. Z has only one lane. */
    pan_section_pack(job, COMPUTE_JOB, INVOCATION, grid) {
        grid.invocations = 7u | (7u << 3) | ((nx - 1) << 6) | ((ny - 1) << (6 + xbits));
        grid.size_y_shift = 3;
        grid.size_z_shift = 6;
        grid.workgroups_x_shift = 6;
        grid.workgroups_y_shift = 6 + xbits;
        grid.workgroups_z_shift = 6 + xbits + ybits;
        grid.thread_group_split = 6;
    }
}

static int wait_command(struct g31_device *dev, const struct g31_bo *command)
{
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now) < 0) return -1;
    struct drm_panfrost_wait_bo wait = {
        .handle = command->handle,
        .timeout_ns = ((int64_t)now.tv_sec + 5) * 1000000000LL + now.tv_nsec,
    };
    /* This BSP can return the remaining jiffies on a successful wait. */
    if (drm_call(dev->fd, DRM_IOCTL_PANFROST_WAIT_BO, &wait) < 0) return -1;
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    const struct command_block *block = command->mapping;
    if (((const volatile uint32_t *)block->job)[0] > 1) { errno = EIO; return -1; }
    return 0;
}

static struct async_slot *next_slot(struct g31_device *dev)
{
    struct async_slot *slot = &dev->slots[dev->next_slot];
    if (!slot->command.handle) {
        if (allocate_bo(dev->fd, &slot->command, sizeof(struct command_block), PANFROST_BO_NOEXEC) < 0)
            return NULL;
        struct drm_syncobj_create sync = {0};
        if (drm_call(dev->fd, DRM_IOCTL_SYNCOBJ_CREATE, &sync) < 0) {
            int error = errno;
            release_bo(dev->fd, &slot->command);
            errno = error;
            return NULL;
        }
        slot->sync = sync.handle;
        /* The shader state and local-storage descriptor are immutable. */
        memcpy(slot->command.mapping, dev->command.mapping, sizeof(struct command_block));
    }
    if (slot->pending && wait_command(dev, &slot->command) < 0) {
        dev->lost = true;
        return NULL;
    }
    slot->pending = false;
    dev->next_slot = (dev->next_slot + 1) % ASYNC_SLOTS;
    return slot;
}

static int rotate(struct g31_surface *src, struct g31_surface *dst,
                  unsigned degrees, bool async, int acquire_fd)
{
    if (!src || !dst || acquire_fd < -1 || src->device != dst->device || src->pixels.handle == dst->pixels.handle ||
        (degrees != 0 && degrees != 90 && degrees != 180 && degrees != 270)) {
        errno = EINVAL;
        return -1;
    }
    bool sideways = degrees == 90 || degrees == 270;
    if (dst->width != (sideways ? src->height : src->width) ||
        dst->height != (sideways ? src->width : src->height)) {
        errno = EINVAL;
        return -1;
    }

    struct g31_uniforms u = {
        .source = src->pixels.gpu, .destination = dst->pixels.gpu,
        .width = dst->width, .height = dst->height, .destination_stride = dst->stride,
        .source_step_x = 1, .source_step_y = (int32_t)src->stride,
    };
    int32_t pitch = (int32_t)src->stride;
    uint32_t last_row = (src->height - 1) * src->stride;
    switch (degrees) {
    case 90:  u.source_origin = last_row; u.source_step_x = -pitch; u.source_step_y = 1; break;
    case 180: u.source_origin = last_row + src->width - 1; u.source_step_x = -1; u.source_step_y = -pitch; break;
    case 270: u.source_origin = src->width - 1; u.source_step_x = pitch; u.source_step_y = -1; break;
    }
    struct g31_device *dev = src->device;
    int error = pthread_mutex_lock(&dev->submit_lock);
    if (error) { errno = error; return -1; }
    if (dev->lost) {
        pthread_mutex_unlock(&dev->submit_lock);
        errno = EIO;
        return -1;
    }
    int result = -1;
    struct drm_syncobj_create input = {0};
    struct async_slot *slot = NULL;
    if (async && !(slot = next_slot(dev))) goto done;
    if (acquire_fd >= 0) {
        if (drm_call(dev->fd, DRM_IOCTL_SYNCOBJ_CREATE, &input) < 0) goto done;
        struct drm_syncobj_handle in = {
            .handle = input.handle, .fd = acquire_fd, .flags = DRM_SYNCOBJ_FD_TO_HANDLE_FLAGS_IMPORT_SYNC_FILE,
        };
        if (drm_call(dev->fd, DRM_IOCTL_SYNCOBJ_FD_TO_HANDLE, &in) < 0) goto done;
    }
    struct g31_bo *command = slot ? &slot->command : &dev->command;
    struct command_block *cmd = command->mapping;
    cmd->uniforms = u;
    pan_section_pack(cmd->job, COMPUTE_JOB, HEADER, header) {
        header.type = MALI_JOB_TYPE_COMPUTE;
        header.index = 1;
    }
    bool tiled = sideways && ((src->width | src->height | src->stride | dst->stride) & 3) == 0 &&
                 ((src->pixels.gpu | dst->pixels.gpu) & 15) == 0;
    enum kernel_id k = tiled ? (degrees == 90 ? TILE_90 : TILE_270) : SCALAR;
    unsigned span = tiled ? 4 : 1;
    set_grid(cmd->job, dst->width / span, dst->height / span);
    pan_section_pack(cmd->job, COMPUTE_JOB, DRAW, draw) {
        draw.state = command->gpu + offsetof(struct command_block, state) + k * sizeof(cmd->state[0]);
        draw.thread_storage = command->gpu + offsetof(struct command_block, tls);
        draw.push_uniforms = command->gpu + offsetof(struct command_block, uniforms);
    }
    uint32_t handles[] = { dev->code[k].handle, command->handle, src->pixels.handle, dst->pixels.handle };
    struct drm_panfrost_submit submit = {
        .jc = command->gpu + offsetof(struct command_block, job),
        .bo_handles = (uintptr_t)handles, .bo_handle_count = sizeof(handles) / sizeof(handles[0]),
        .in_syncs = input.handle ? (uintptr_t)&input.handle : 0, .in_sync_count = input.handle ? 1 : 0,
        .out_sync = slot ? slot->sync : 0,
    };
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    if (drm_call(dev->fd, DRM_IOCTL_PANFROST_SUBMIT, &submit) < 0) goto done;
    if (slot) {
        slot->pending = true;
        struct drm_syncobj_handle out = {
            .handle = slot->sync, .flags = DRM_SYNCOBJ_HANDLE_TO_FD_FLAGS_EXPORT_SYNC_FILE, .fd = -1,
        };
        if (drm_call(dev->fd, DRM_IOCTL_SYNCOBJ_HANDLE_TO_FD, &out) == 0) result = out.fd;
        else {
            int export_error = errno;
            if (wait_command(dev, command) < 0) dev->lost = true;
            else errno = export_error;
        }
    } else {
        result = wait_command(dev, command);
        if (result < 0) dev->lost = true;
    }
done:
    error = errno;
    if (input.handle) {
        struct drm_syncobj_destroy destroy = { .handle = input.handle };
        drm_call(dev->fd, DRM_IOCTL_SYNCOBJ_DESTROY, &destroy);
    }
    pthread_mutex_unlock(&dev->submit_lock);
    if (result < 0) errno = error;
    return result;
}

int g31_rotate(struct g31_surface *src, struct g31_surface *dst, unsigned degrees)
{
    return rotate(src, dst, degrees, false, -1);
}

int g31_rotate_async(struct g31_surface *src, struct g31_surface *dst, unsigned degrees, int acquire_fd)
{
    return rotate(src, dst, degrees, true, acquire_fd);
}
