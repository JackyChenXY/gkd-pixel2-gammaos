/* SPDX-License-Identifier: Apache-2.0 */
#ifndef PIXEL2_G31_ANDROID_SURFACE_H
#define PIXEL2_G31_ANDROID_SURFACE_H
#include <android/hardware_buffer.h>
#include "g31.h"
#ifdef __cplusplus
extern "C" {
#endif
/* Board adapter for this port's minigbm allocator. The caller owns the AHB
 * and synchronizes access before/after using a GPU view, as for g31_import. */
struct g31_surface *g31_import_android(struct g31_device *dev, AHardwareBuffer *buffer);
#ifdef __cplusplus
}
#endif
#endif
