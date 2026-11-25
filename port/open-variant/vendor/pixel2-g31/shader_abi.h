/* SPDX-License-Identifier: Apache-2.0 */
#ifndef PIXEL2_G31_SHADER_ABI_H
#define PIXEL2_G31_SHADER_ABI_H

#include <stdint.h>

/* Strides and pixel offsets are measured in 32-bit pixels, not bytes. */
struct g31_uniforms {
    uint64_t source;
    uint64_t destination;
    uint32_t width;
    uint32_t height;
    uint32_t destination_stride;
    uint32_t source_origin;
    int32_t source_step_x;
    int32_t source_step_y;
};

enum { G31_GROUP_X = 8, G31_GROUP_Y = 8 };
_Static_assert(sizeof(struct g31_uniforms) == 40, "Unexpected shader ABI");
#endif
