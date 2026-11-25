/* SPDX-License-Identifier: Apache-2.0 */
#include "android_surface.h"
#include <cerrno>
#include <drm_fourcc.h>
#include <vndk/hardware_buffer.h>
#include "cros_gralloc_handle.h"

extern "C" g31_surface *g31_import_android(g31_device *dev, AHardwareBuffer *buffer)
{
    if (!dev || !buffer) { errno = EINVAL; return nullptr; }
    AHardwareBuffer_Desc desc{};
    AHardwareBuffer_describe(buffer, &desc);
    const native_handle_t *raw = AHardwareBuffer_getNativeHandle(buffer);
    if (!raw || raw->version != sizeof(native_handle_t) || raw->numFds < 1 || raw->numFds > 2 ||
        raw->numInts < 0 || raw->numInts > 4096 ||
        sizeof(native_handle_t) + sizeof(int) * (raw->numFds + raw->numInts) < sizeof(cros_gralloc_handle)) {
        errno = ENOTSUP;
        return nullptr;
    }
    const auto *h = static_cast<const cros_gralloc_handle *>(raw);
    constexpr uint32_t minigbm_magic = 0xABCDDCBA; // cros_gralloc_helpers.h in this SDK
    if (h->magic != minigbm_magic || h->num_planes != 1 || h->format != DRM_FORMAT_ABGR8888 ||
        h->format_modifier != DRM_FORMAT_MOD_LINEAR || h->tiling != 0 ||
        desc.format != AHARDWAREBUFFER_FORMAT_R8G8B8A8_UNORM || desc.layers != 1 ||
        desc.usage & AHARDWAREBUFFER_USAGE_PROTECTED_CONTENT ||
        desc.width != h->width || desc.height != h->height || desc.stride != h->pixel_stride ||
        uint64_t(desc.stride) * 4 != h->strides[0] || h->fds[0] < 0) {
        errno = ENOTSUP;
        return nullptr;
    }
    return g31_import(dev, h->fds[0], desc.width, desc.height, desc.stride, h->offsets[0]);
}
