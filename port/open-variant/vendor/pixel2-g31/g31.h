/* SPDX-License-Identifier: Apache-2.0 */
#ifndef PIXEL2_G31_H
#define PIXEL2_G31_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

struct g31_device;
struct g31_surface;

/* All calls that can fail set errno. A surface belongs to one device.
 * Finish using its surfaces before closing the device. */
struct g31_device *g31_open(void);
void g31_close(struct g31_device *device);

/* Linear, tightly packed or padded RGBA8888, with a top-left origin.
 * Stride is measured in pixels. */
struct g31_surface *g31_create(struct g31_device *device, uint32_t width,
                               uint32_t height, uint32_t stride);
/* Import an existing single-plane, linear RGBA8888 DMA-BUF without copying.
 * Stride is in pixels, offset is in bytes. The caller owns the fd and waits
 * for its producer's acquire fence before g31_rotate(). */
struct g31_surface *g31_import(struct g31_device *device, int fd, uint32_t width,
                               uint32_t height, uint32_t stride, uint32_t offset);
void g31_destroy(struct g31_surface *surface);

/* For g31_create() surfaces. Imported surfaces use their owner's CPU mapping. */
uint32_t *g31_pixels(struct g31_surface *surface);

/* The returned DMA-BUF fd belongs to the caller. */
int g31_export(const struct g31_surface *surface);

/* Synchronous copy or clockwise rotation. Input and output must be distinct.
 * 90 and 270 degrees exchange width and height. */
int g31_rotate(struct g31_surface *src, struct g31_surface *dst, unsigned degrees);
/* Return an owned Linux sync_file fd for completion. acquire_fd is borrowed
 * and may be -1. Keep CPU users off both images until the fence signals.
 * Up to three asynchronous command buffers can be in flight per device. */
int g31_rotate_async(struct g31_surface *src, struct g31_surface *dst,
                     unsigned degrees, int acquire_fd);
#ifdef __cplusplus
}
#endif
#endif
