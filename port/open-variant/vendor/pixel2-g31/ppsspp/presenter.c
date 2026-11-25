/* SPDX-License-Identifier: Apache-2.0 */
#include "android_surface.h"
#include <android/log.h>
#include <android/native_window_jni.h>
#include <errno.h>
#include <jni.h>
#include <linux/sync_file.h>
#include <media/NdkImageReader.h>
#include <poll.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <system/window.h>
#include <unistd.h>

#define INFO(...) __android_log_print(ANDROID_LOG_INFO, "Pixel2G31", __VA_ARGS__)
#define ERROR(...) __android_log_print(ANDROID_LOG_ERROR, "Pixel2G31", __VA_ARGS__)
enum { CACHE_SIZE = 12, IN_FLIGHT = 3 };

struct cached_buffer {
    uint64_t id;
    AHardwareBuffer *buffer;
    struct g31_surface *view;
};

struct presenter {
    ANativeWindow *output;
    AImageReader *reader;
    struct g31_device *gpu;
    struct cached_buffer sources[CACHE_SIZE], targets[CACHE_SIZE];
    pthread_mutex_t lock;
    pthread_cond_t ready;
    pthread_t worker;
    bool running, stop, available, connected;
    int fences[IN_FLIGHT];
    unsigned slot, queued, errors, degrees;
    int width, height, transform;
};

static void wait_fence(int fd)
{
    if (fd < 0) return;
    struct pollfd item = { .fd = fd, .events = POLLIN };
    while (poll(&item, 1, -1) < 0 && errno == EINTR) {}
}

static void release_fd(int fd)
{
    if (fd >= 0) close(fd);
}

static void finish_slot(struct presenter *p, unsigned slot)
{
    wait_fence(p->fences[slot]);
    release_fd(p->fences[slot]);
    p->fences[slot] = -1;
}

static void finish_all(struct presenter *p)
{
    for (unsigned i = 0; i < IN_FLIGHT; i++) finish_slot(p, i);
}

static void clear_cache(struct cached_buffer *cache)
{
    for (int i = 0; i < CACHE_SIZE; i++) {
        if (!cache[i].buffer) break;
        g31_destroy(cache[i].view);
        AHardwareBuffer_release(cache[i].buffer);
        cache[i] = (struct cached_buffer){0};
    }
}

static struct g31_surface *view_for(struct presenter *p, struct cached_buffer *cache,
                                    AHardwareBuffer *buffer, uint32_t width, uint32_t height)
{
    uint64_t id;
    AHardwareBuffer_Desc desc;
    AHardwareBuffer_describe(buffer, &desc);
    if (desc.width != width || desc.height != height || AHardwareBuffer_getId(buffer, &id) != 0) {
        ERROR("Unexpected buffer %ux%u format %u (wanted %ux%u)", desc.width, desc.height, desc.format, width, height);
        return NULL;
    }
    int i = 0;
    for (; i < CACHE_SIZE && cache[i].buffer; i++)
        if (cache[i].id == id) return cache[i].view;
    if (i == CACHE_SIZE) {
        finish_all(p);
        clear_cache(cache);
        i = 0;
    }
    struct g31_surface *view = g31_import_android(p->gpu, buffer);
    if (!view) {
        ERROR("Cannot import %ux%u format %u stride %u: %s", width, height, desc.format, desc.stride, strerror(errno));
        return NULL;
    }
    AHardwareBuffer_acquire(buffer);
    cache[i] = (struct cached_buffer){ id, buffer, view };
    return view;
}

/* Inputs are borrowed. If a merge is unavailable, wait for the second input
 * before passing the first to the hardware. */
static int dependency(int source, int target, int *owned)
{
    *owned = -1;
    if (source < 0) return target;
    if (target < 0) return source;
    struct sync_merge_data merge = { .name = "pixel2-game", .fd2 = target, .fence = -1 };
    int result;
    do { result = ioctl(source, SYNC_IOC_MERGE, &merge); } while (result < 0 && errno == EINTR);
    if (!result) {
        *owned = merge.fence;
        return merge.fence;
    }
    wait_fence(target);
    return source;
}

/* Owns image and acquire. Every dequeued buffer is returned exactly once. */
static bool present(struct presenter *p, AImage *image, int acquire)
{
    AHardwareBuffer *input = NULL;
    AImageCropRect crop;
    ANativeWindowBuffer *target = NULL;
    int target_fence = -1, merged = -1;
    if (AImage_getHardwareBuffer(image, &input) != AMEDIA_OK ||
        AImage_getCropRect(image, &crop) != AMEDIA_OK || crop.left || crop.top ||
        crop.right != p->width || crop.bottom != p->height) goto fail;
    struct g31_surface *src = view_for(p, p->sources, input, p->width, p->height);
    if (!src) goto fail;
    int status = ANativeWindow_dequeueBuffer(p->output, &target, &target_fence);
    if (status != 0) {
        if (!p->errors) ERROR("Display dequeue returned %d", status);
        goto fail;
    }
    struct g31_surface *dst = view_for(p, p->targets, ANativeWindowBuffer_getHardwareBuffer(target), p->height, p->width);
    if (!dst) goto cancel;
    finish_slot(p, p->slot);
    int dep = dependency(acquire, target_fence, &merged);
    int done = g31_rotate_async(src, dst, p->degrees, dep);
    release_fd(merged);
    if (done < 0) {
        ERROR("Rotation submit failed: %s", strerror(errno));
        goto cancel;
    }
    release_fd(acquire);
    release_fd(target_fence);
    int reader_done = dup(done);
    int cache_done = dup(done);
    if (reader_done < 0 || cache_done < 0) wait_fence(done);
    p->fences[p->slot] = cache_done;
    p->slot = (p->slot + 1) % IN_FLIGHT;
    AImage_deleteAsync(image, reader_done);
    status = ANativeWindow_queueBuffer(p->output, target, done);
    if (status != 0) {
        ERROR("Display queue returned %d", status);
        return false;
    }
    return true;

cancel:
    ANativeWindow_cancelBuffer(p->output, target, target_fence);
fail:
    AImage_deleteAsync(image, acquire);
    return false;
}

static void notified(void *context, AImageReader *reader)
{
    (void)reader;
    struct presenter *p = context;
    pthread_mutex_lock(&p->lock);
    p->available = true;
    pthread_cond_signal(&p->ready);
    pthread_mutex_unlock(&p->lock);
}

static void *process(void *context)
{
    struct presenter *p = context;
    for (;;) {
        pthread_mutex_lock(&p->lock);
        while (!p->available && !p->stop) pthread_cond_wait(&p->ready, &p->lock);
        bool stop = p->stop;
        p->available = false;
        pthread_mutex_unlock(&p->lock);
        if (stop) break;
        for (;;) {
            AImage *image = NULL;
            int acquire = -1;
            if (AImageReader_acquireNextImageAsync(p->reader, &image, &acquire) != AMEDIA_OK) break;
            if (present(p, image, acquire)) {
                p->queued++;
                if (p->queued == 1 || p->queued % 600 == 0)
                    INFO("Presented %u game frames, errors=%u", p->queued, p->errors);
            } else if (++p->errors <= 3) {
                ERROR("Game frame could not be presented (%u)", p->errors);
            }
            pthread_mutex_lock(&p->lock);
            stop = p->stop;
            pthread_mutex_unlock(&p->lock);
            if (stop) return NULL;
        }
    }
    return NULL;
}

static void destroy(struct presenter *p)
{
    if (p->running) {
        pthread_mutex_lock(&p->lock);
        p->stop = true;
        pthread_cond_signal(&p->ready);
        pthread_mutex_unlock(&p->lock);
        pthread_join(p->worker, NULL);
    }
    if (p->reader) {
        AImageReader_setImageListener(p->reader, NULL);
        AImageReader_delete(p->reader);
    }
    finish_all(p);
    clear_cache(p->sources);
    clear_cache(p->targets);
    if (p->connected) {
        ANativeWindow_setBuffersTransform(p->output, ANATIVEWINDOW_TRANSFORM_IDENTITY);
        ANativeWindow_setBuffersGeometry(p->output, 0, 0, 0);
        native_window_api_disconnect(p->output, NATIVE_WINDOW_API_EGL);
    }
    if (p->output) ANativeWindow_release(p->output);
    if (p->gpu) g31_close(p->gpu);
    pthread_cond_destroy(&p->ready);
    pthread_mutex_destroy(&p->lock);
    INFO("Presenter closed, queued=%u errors=%u", p->queued, p->errors);
    free(p);
}

JNIEXPORT jlong JNICALL Java_org_ppsspp_ppsspp_Pixel2Presentation_open(
    JNIEnv *env, jclass cls, jobject surface, jint width, jint height)
{
    (void)cls;
    struct presenter *p = calloc(1, sizeof(*p));
    if (!p) return 0;
    for (unsigned i = 0; i < IN_FLIGHT; i++) p->fences[i] = -1;
    pthread_mutex_init(&p->lock, NULL);
    pthread_cond_init(&p->ready, NULL);
    p->width = width;
    p->height = height;
    p->gpu = g31_open();
    p->output = ANativeWindow_fromSurface(env, surface);
    if (!p->gpu || !p->output) { ERROR("GPU/window unavailable: %s", strerror(errno)); goto fail; }
    int rc = native_window_api_connect(p->output, NATIVE_WINDOW_API_EGL);
    if (rc != 0) { ERROR("Display connect: %d", rc); goto fail; }
    p->connected = true;
    int hint = 0;
    p->output->query(p->output, NATIVE_WINDOW_TRANSFORM_HINT, &hint);
    /* The image stored in memory must carry the inverse consumer transform. */
    p->transform = hint == ANATIVEWINDOW_TRANSFORM_ROTATE_270 ?
                    ANATIVEWINDOW_TRANSFORM_ROTATE_90 : ANATIVEWINDOW_TRANSFORM_ROTATE_270;
    p->degrees = p->transform == ANATIVEWINDOW_TRANSFORM_ROTATE_90 ? 270 : 90;
    if (hint != ANATIVEWINDOW_TRANSFORM_ROTATE_270 && hint != ANATIVEWINDOW_TRANSFORM_ROTATE_90) {
        ERROR("Unsupported display transform hint %d", hint);
        goto fail;
    }
    uint64_t usage = AHARDWAREBUFFER_USAGE_GPU_SAMPLED_IMAGE | AHARDWAREBUFFER_USAGE_GPU_COLOR_OUTPUT;
    if ((rc = ANativeWindow_setDequeueTimeout(p->output, 250000000)) != 0 ||
        (rc = ANativeWindow_setBuffersGeometry(p->output, height, width, WINDOW_FORMAT_RGBA_8888)) != 0 ||
        (rc = ANativeWindow_setBuffersTransform(p->output, p->transform)) != 0 ||
        (rc = ANativeWindow_setUsage(p->output, usage)) != 0) {
        ERROR("Display configuration failed %d", rc);
        goto fail;
    }
    AImageReader_ImageListener listener = { .context = p, .onImageAvailable = notified };
    rc = AImageReader_newWithUsage(width, height, AIMAGE_FORMAT_RGBA_8888, AHARDWAREBUFFER_USAGE_GPU_SAMPLED_IMAGE, 4, &p->reader);
    if (rc != AMEDIA_OK || AImageReader_setImageListener(p->reader, &listener) != AMEDIA_OK ||
        pthread_create(&p->worker, NULL, process, p) != 0) {
        ERROR("Image queue creation failed %d", rc);
        goto fail;
    }
    p->running = true;
    INFO("Game %dx%d -> panel buffer %dx%d, hardware rotation %u, transform %d, hint %d",
         width, height, height, width, p->degrees, p->transform, hint);
    return (jlong)(uintptr_t)p;
fail:
    destroy(p);
    return 0;
}

JNIEXPORT jobject JNICALL Java_org_ppsspp_ppsspp_Pixel2Presentation_inputSurface(
    JNIEnv *env, jclass cls, jlong handle)
{
    (void)cls;
    struct presenter *p = (void *)(uintptr_t)handle;
    ANativeWindow *window = NULL;
    if (!p || AImageReader_getWindow(p->reader, &window) != AMEDIA_OK) return NULL;
    return ANativeWindow_toSurface(env, window);
}

JNIEXPORT void JNICALL Java_org_ppsspp_ppsspp_Pixel2Presentation_close(
    JNIEnv *env, jclass cls, jlong handle)
{
    (void)env; (void)cls;
    if (handle) destroy((void *)(uintptr_t)handle);
}
