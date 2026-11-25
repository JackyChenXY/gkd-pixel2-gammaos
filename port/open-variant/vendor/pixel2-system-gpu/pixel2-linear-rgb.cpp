/* SPDX-License-Identifier: MIT */
#include <climits>
#include <cstdint>
#include <hardware/gralloc.h>
#include <system/window.h>
#include "cros_gralloc_handle.h"
#include "drm-uapi/drm_fourcc.h"
#include "util/u_gralloc/u_gralloc.h"

/* The Pixel 2 allocator publishes its linear RGB layout in the native handle.
 * YUV, protected, tiled and unfamiliar handles use Mesa's regular mapper. */
extern "C" bool
pixel2_describe_linear_rgb(const ANativeWindowBuffer *buffer,
                          u_gralloc_buffer_basic_info *out)
{
   if (!buffer || !out || buffer->width <= 0 || buffer->height <= 0 ||
       buffer->stride < buffer->width || (buffer->usage & GRALLOC_USAGE_PROTECTED))
      return false;

   const native_handle_t *raw = buffer->handle;
   if (!raw || raw->version != sizeof(native_handle_t) ||
       raw->numFds < 1 || raw->numFds > 2 || raw->numInts < 0 ||
       uint64_t(raw->numFds) + raw->numInts <
          (sizeof(cros_gralloc_handle) - sizeof(native_handle_t)) / sizeof(int))
      return false;

   const auto *h = static_cast<const cros_gralloc_handle *>(raw);
   constexpr uint32_t magic = 0xABCDDCBA; /* Pixel 2 minigbm cros_gralloc_helpers.h */
   if (h->magic != magic || h->num_planes != 1 || h->fds[0] < 0 ||
       h->numFds != (h->reserved_region_size ? 2 : 1) ||
       h->tiling != 0 || h->format_modifier != DRM_FORMAT_MOD_LINEAR ||
       h->width != uint32_t(buffer->width) || h->height != uint32_t(buffer->height) ||
       h->pixel_stride != uint32_t(buffer->stride) || h->droid_format != buffer->format ||
       (h->usage & GRALLOC_USAGE_PROTECTED))
      return false;

   uint32_t fourcc;
   uint32_t bytes_per_pixel;
   switch (buffer->format) {
   case HAL_PIXEL_FORMAT_RGBA_8888: fourcc = DRM_FORMAT_ABGR8888; bytes_per_pixel = 4; break;
   case HAL_PIXEL_FORMAT_RGBX_8888: fourcc = DRM_FORMAT_XBGR8888; bytes_per_pixel = 4; break;
   case HAL_PIXEL_FORMAT_BGRA_8888: fourcc = DRM_FORMAT_ARGB8888; bytes_per_pixel = 4; break;
   case HAL_PIXEL_FORMAT_RGB_565:   fourcc = DRM_FORMAT_RGB565;   bytes_per_pixel = 2; break;
   default: return false;
   }
   const uint64_t pitch = uint64_t(h->pixel_stride) * bytes_per_pixel;
   const uint64_t used = uint64_t(h->height - 1) * h->strides[0] +
                         uint64_t(h->width) * bytes_per_pixel;
   if (h->format != fourcc || h->strides[0] != pitch || pitch > INT_MAX ||
       h->offsets[0] > INT_MAX || used > h->sizes[0] ||
       h->reserved_region_size > h->total_size ||
       uint64_t(h->offsets[0]) + used > h->total_size - h->reserved_region_size)
      return false;

   *out = {};
   out->drm_fourcc = fourcc;
   out->modifier = DRM_FORMAT_MOD_LINEAR;
   out->num_planes = 1;
   out->fds[0] = h->fds[0];
   out->strides[0] = static_cast<int>(pitch);
   out->offsets[0] = static_cast<int>(h->offsets[0]);
   return true;
}
