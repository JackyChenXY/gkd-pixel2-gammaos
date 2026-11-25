#include <errno.h>
#include <fcntl.h>
#include <jni.h>
#include <linux/input.h>
#include <poll.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>

/* Android's original button events are either accepted or consumed by the accessibility service.
 * This read-only descriptor lets that decision observe the second button before Android dispatches
 * the first. It never grabs the controller, writes input, or opens a keyboard. */
struct reader {
    int fd;
    bool saved;
    struct input_event next;
};

static bool attribute_equals(int index, const char *attribute, const char *expected) {
    char path[128], value[64];
    snprintf(path, sizeof(path), "/sys/class/input/event%d/device/%s", index, attribute);
    FILE *file = fopen(path, "re");
    if (!file) return false;
    bool ok = fgets(value, sizeof(value), file) != NULL;
    fclose(file);
    if (!ok) return false;
    value[strcspn(value, "\r\n")] = 0;
    return strcmp(value, expected) == 0;
}

JNIEXPORT jlong JNICALL
Java_org_gkdpixel2_padnavigation_PadChord_openReader(JNIEnv *env, jclass cls, jint product) {
    (void)env; (void)cls;
    if (product != 1 && product != 0x2102) return 0;
    bool forwarded = product == 0x2102;
    for (int i = 0; i < 64; ++i) {
        if (!attribute_equals(i, "name", "gkd_pixel2_joypad")
                || !attribute_equals(i, "id/bustype", forwarded ? "0006" : "0019")
                || !attribute_equals(i, "id/vendor", "0001")
                || !attribute_equals(i, "id/product", forwarded ? "2102" : "0001")) continue;
        char path[48], name[80] = {0};
        snprintf(path, sizeof(path), "/dev/input/event%d", i);
        int fd = open(path, O_RDONLY | O_NONBLOCK | O_CLOEXEC);
        if (fd < 0) continue;
        struct input_id id;
        int clock_id = CLOCK_MONOTONIC;
        if (ioctl(fd, EVIOCGID, &id) < 0 || id.vendor != 1 || id.product != product
                || id.bustype != (forwarded ? BUS_VIRTUAL : BUS_HOST)
                || ioctl(fd, EVIOCGNAME(sizeof(name)-1), name) < 0
                || strcmp(name, "gkd_pixel2_joypad") != 0
                || ioctl(fd, EVIOCSCLOCKID, &clock_id) < 0) {
            close(fd);
            continue;
        }
        uint8_t bits[KEY_MAX / 8 + 1] = {0};
        bits[BTN_TR / 8] |= 1u << (BTN_TR % 8);
        bits[BTN_TRIGGER_HAPPY1 / 8] |= 1u << (BTN_TRIGGER_HAPPY1 % 8);
        struct input_mask mask = {.type = EV_KEY, .codes_size = sizeof(bits),
                                  .codes_ptr = (uintptr_t)bits};
        /* Some older kernels only support filtering in userspace. */
        (void)ioctl(fd, EVIOCSMASK, &mask);
        struct reader *r = calloc(1, sizeof(*r));
        if (!r) { close(fd); return 0; }
        r->fd = fd;
        return (jlong)(uintptr_t)r;
    }
    return 0;
}

static int64_t uptime_ms(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (int64_t)t.tv_sec * 1000 + t.tv_nsec / 1000000;
}

JNIEXPORT jlong JNICALL
Java_org_gkdpixel2_padnavigation_PadChord_findFunctionDown(JNIEnv *env, jclass cls, jlong handle,
                                                           jlong r1_ms, jint window_ms) {
    (void)env; (void)cls;
    struct reader *r = (struct reader *)(uintptr_t)handle;
    if (!r) return -1;
    int64_t deadline = r1_ms + window_ms;
    bool found_down = false;
    for (;;) {
        struct input_event ev;
        if (r->saved) {
            ev = r->next;
            r->saved = false;
        } else {
            ssize_t got = read(r->fd, &ev, sizeof(ev));
            if (got < 0 && errno == EINTR) continue;
            if (got < 0 && errno == EAGAIN) {
                int64_t remaining = deadline - uptime_ms();
                if (!found_down || remaining <= 0) return -1;
                struct pollfd p = {.fd = r->fd, .events = POLLIN};
                int ready = poll(&p, 1, (int)remaining);
                if (ready < 0 && errno == EINTR) continue;
                if (ready == 0) return -1;
                if (ready < 0 || !(p.revents & POLLIN)) return -2;
                continue;
            }
            if (got != sizeof(ev)) return -2;
        }
        if (ev.type == EV_SYN && ev.code == SYN_DROPPED && found_down) return -1;
        if (ev.type != EV_KEY || (ev.code != BTN_TR && ev.code != BTN_TRIGGER_HAPPY1)) continue;
        int64_t when = (int64_t)ev.time.tv_sec * 1000 + ev.time.tv_usec / 1000;
        if (ev.code == BTN_TR && ev.value == 1) {
            /* Match this exact Android press. Leave a later tap for its own callback. */
            if (when > r1_ms + 2 || found_down) {
                r->next = ev;
                r->saved = true;
                return -1;
            }
            if (when >= r1_ms - 2) found_down = true;
            continue;
        }
        if (!found_down) continue;
        if (when > deadline || (ev.code == BTN_TR && ev.value == 0)) return -1;
        if (ev.code == BTN_TRIGGER_HAPPY1 && ev.value == 1) return when;
    }
}

JNIEXPORT void JNICALL
Java_org_gkdpixel2_padnavigation_PadChord_closeReader(JNIEnv *env, jclass cls, jlong handle) {
    (void)env; (void)cls;
    struct reader *r = (struct reader *)(uintptr_t)handle;
    if (r) { close(r->fd); free(r); }
}
