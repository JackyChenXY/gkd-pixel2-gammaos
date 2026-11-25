/* SPDX-License-Identifier: Apache-2.0 */
#include "g31.h"
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/ioctl.h>
#include <unistd.h>

static uint32_t pattern(uint32_t x, uint32_t y, uint32_t seed)
{
    uint32_t v = (x + seed * 2569u) ^ (y * 65537u + 17u);
    v ^= v >> 16;
    v *= 0x7feb352du;
    return v ^ (v >> 15);
}

static int check(struct g31_device *dev, unsigned w, unsigned h, unsigned degrees, unsigned pad)
{
    const unsigned sw = w + pad;
    const bool sideways = degrees == 90 || degrees == 270;
    const unsigned ow = sideways ? h : w, oh = sideways ? w : h;
    const unsigned dw = ow + pad + (pad ? ((pad & 3) ? 2 : 4) : 0);
    const uint32_t guard = 0xe4c38879;
    struct g31_surface *src = g31_create(dev, w, h, sw);
    struct g31_surface *dst = g31_create(dev, ow, oh, dw);
    uint32_t *want = malloc((size_t)oh * dw * sizeof(*want));
    int rc = -1;
    if (!src || !dst || !want) { perror("allocate test surfaces"); goto out; }
    for (unsigned repeat = 1; repeat <= 2; ++repeat) {
        uint32_t *in = g31_pixels(src), *out = g31_pixels(dst);
        for (unsigned i = 0; i < oh * dw; ++i) out[i] = want[i] = guard;
        for (unsigned y = 0; y < h; ++y) {
            for (unsigned x = 0; x < sw; ++x) {
                in[y * sw + x] = pattern(x, y, degrees + repeat);
                if (x >= w) continue;
                unsigned dx = x, dy = y;
                switch (degrees) {
                case 90:  dx = h - 1 - y; dy = x; break;
                case 180: dx = w - 1 - x; dy = h - 1 - y; break;
                case 270: dx = y; dy = w - 1 - x; break;
                }
                want[dy * dw + dx] = pattern(x, y, degrees + repeat);
            }
        }
        if (g31_rotate(src, dst, degrees) != 0) { perror("G31 job"); goto out; }
        for (unsigned i = 0; i < oh * dw; ++i) {
            if (out[i] != want[i]) {
                fprintf(stderr, "%ux%u rotation=%u sample=%u (%u,%u) expected=%08x got=%08x\n",
                        w, h, degrees, repeat, i % dw, i / dw, want[i], out[i]);
                goto out;
            }
        }
    }
    int fd = g31_export(dst);
    if (fd < 0) { perror("DMA-BUF export"); goto out; }
    int flags = fcntl(fd, F_GETFD);
    close(fd);
    if (flags < 0 || !(flags & FD_CLOEXEC)) { fputs("invalid exported fd\n", stderr); goto out; }
    rc = 0;
out:
    free(want);
    g31_destroy(dst);
    g31_destroy(src);
    return rc;
}

static bool invalid_requests_rejected(struct g31_device *dev)
{
    struct g31_surface *a = g31_create(dev, 5, 3, 5);
    struct g31_surface *b = g31_create(dev, 5, 3, 5);
    bool ok = a && b && !g31_create(dev, 5, 2, 4) && errno == EINVAL &&
              g31_rotate(a, a, 0) == -1 && errno == EINVAL &&
              g31_rotate(a, b, 90) == -1 && errno == EINVAL &&
              g31_rotate(a, b, 89) == -1 && errno == EINVAL;
    g31_destroy(a);
    g31_destroy(b);
    return ok;
}

static bool check_imported_view(struct g31_device *dev)
{
    struct g31_surface *backing = g31_create(dev, 48, 32, 56);
    struct g31_surface *dst = g31_create(dev, 12, 8, 12), *view = NULL, *invalid = NULL;
    int fd = -1;
    bool ok = false;
    if (!backing || !dst) goto out;
    uint32_t *pixels = g31_pixels(backing);
    for (unsigned y = 0; y < 32; ++y)
        for (unsigned x = 0; x < 56; ++x) pixels[y * 56 + x] = pattern(x, y, 27);
    fd = g31_export(backing);
    if (fd < 0) goto out;
    invalid = g31_import(dev, fd, 8, 12, 56, 0xfffffffcu);
    if (invalid || errno != EINVAL) goto out;
    view = g31_import(dev, fd, 8, 12, 56, (56 + 3) * 4);
    if (!view || g31_rotate(view, backing, 0) == 0 || errno != EINVAL) goto out;
    g31_destroy(backing);
    backing = NULL;
    close(fd);
    fd = -1;
    if (g31_rotate(view, dst, 270) != 0) goto out;
    pixels = g31_pixels(dst);
    for (unsigned y = 0; y < 8; ++y)
        for (unsigned x = 0; x < 12; ++x)
            if (pixels[y * 12 + x] != pattern(3 + 7 - y, 1 + x, 27)) goto out;
    ok = true;
out:
    if (fd >= 0) close(fd);
    g31_destroy(invalid);
    g31_destroy(view);
    g31_destroy(backing);
    g31_destroy(dst);
    return ok;
}

static int fence_ready(int fd, int timeout_ms)
{
    struct pollfd watch = { .fd = fd, .events = POLLIN };
    int ready;
    do { ready = poll(&watch, 1, timeout_ms); } while (ready < 0 && errno == EINTR);
    if (ready <= 0) return ready;
    return ((watch.revents & POLLIN) && !(watch.revents & (POLLERR | POLLNVAL))) ? 1 : -1;
}

static bool check_acquire_fence(struct g31_device *dev)
{
    /* Linux sw_sync test-timeline ABI (drivers/dma-buf/sw_sync.c). */
    struct fence_request { uint32_t value; char name[32]; int32_t fd; };
    struct fence_request input = { .value = 1, .name = "pixel2-g31-acquire", .fd = -1 };
    const uint32_t one = 1;
    int timeline = open("/dev/sw_sync", O_RDWR | O_CLOEXEC);
    if (timeline < 0 && (errno == EACCES || errno == ENOENT)) {
        puts("SKIP held acquire fence: sw_sync unavailable");
        return true;
    }
    if (timeline < 0) return false;
    struct g31_surface *src = g31_create(dev, 8, 8, 8), *dst = g31_create(dev, 8, 8, 8);
    int completion = -1;
    bool ok = false, released = false;
    if (!src || !dst || ioctl(timeline, _IOWR('W', 0, struct fence_request), &input) < 0) goto out;
    for (unsigned i = 0; i < 64; ++i) g31_pixels(src)[i] = i + 1;
    completion = g31_rotate_async(src, dst, 0, input.fd);
    if (completion < 0 || fence_ready(completion, 60) != 0) goto out;
    if (ioctl(timeline, _IOW('W', 1, uint32_t), &one) < 0) goto out;
    released = true;
    if (fence_ready(completion, 5000) != 1) goto out;
    for (unsigned i = 0; i < 64; ++i)
        if (g31_pixels(dst)[i] != i + 1) goto out;
    puts("PASS held acquire fence: output waited for release, all pixels verified");
    ok = true;
out:
    if (!released && input.fd >= 0) ioctl(timeline, _IOW('W', 1, uint32_t), &one);
    if (input.fd >= 0) close(input.fd);
    if (completion >= 0) close(completion);
    close(timeline);
    g31_destroy(dst);
    g31_destroy(src);
    return ok;
}

static bool check_async(struct g31_device *dev)
{
    enum { SIDE = 36, STRIDE = 40, JOBS = 7 };
    struct g31_surface *images[] = { g31_create(dev, SIDE, SIDE, STRIDE), g31_create(dev, SIDE, SIDE, STRIDE) };
    int fence = -1;
    bool ok = false;
    if (!images[0] || !images[1]) goto out;
    uint32_t *pixels = g31_pixels(images[0]);
    for (unsigned y = 0; y < SIDE; ++y)
        for (unsigned x = 0; x < SIDE; ++x) pixels[y * STRIDE + x] = pattern(x, y, 318);
    for (unsigned i = 0; i < JOBS; ++i) {
        int next = g31_rotate_async(images[i % 2], images[(i + 1) % 2], 90, fence);
        if (next < 0) { perror("queue G31 rotation"); goto out; }
        if (fence >= 0) close(fence);
        fence = next;
    }
    if (fence_ready(fence, 5000) != 1) goto out;
    pixels = g31_pixels(images[JOBS % 2]);
    for (unsigned y = 0; y < SIDE; ++y)
        for (unsigned x = 0; x < SIDE; ++x)
            if (pixels[y * STRIDE + x] != pattern(SIDE - 1 - y, x, 318)) goto out;
    ok = true;
out:
    if (fence >= 0) close(fence);
    g31_destroy(images[1]);
    g31_destroy(images[0]);
    return ok;
}

int main(void)
{
    const unsigned sizes[][3] = {
        {1, 1, 0}, {1, 17, 3}, {19, 1, 1}, {7, 9, 4}, {8, 8, 0}, {31, 47, 7},
        {36, 44, 4}, {480, 272, 0}, {640, 480, 0}, {479, 641, 13},
    };
    struct g31_device *dev = g31_open();
    if (!dev) { perror("open Mali-G31"); return 1; }
    if (!invalid_requests_rejected(dev)) { fputs("input validation failed\n", stderr); g31_close(dev); return 1; }
    if (!check_imported_view(dev)) { fputs("DMA-BUF offset or lifetime check failed\n", stderr); g31_close(dev); return 1; }
    if (!check_async(dev)) { fputs("asynchronous completion test failed\n", stderr); g31_close(dev); return 1; }
    if (!check_acquire_fence(dev)) { fputs("held acquire fence test failed\n", stderr); g31_close(dev); return 1; }
    unsigned jobs = 0;
    for (unsigned s = 0; s < sizeof(sizes) / sizeof(sizes[0]); ++s) {
        for (unsigned angle = 0; angle < 360; angle += 90) {
            if (check(dev, sizes[s][0], sizes[s][1], angle, sizes[s][2]) < 0) {
                g31_close(dev);
                return 1;
            }
            jobs += 2;
        }
        printf("%ux%u: four rotations, two distinct patterns, full pixels and padding verified\n",
               sizes[s][0], sizes[s][1]);
        fflush(stdout);
    }
    g31_close(dev);
    printf("PASS %u image rotations, one imported subimage, seven chained native-fence jobs\n", jobs);
    return 0;
}
