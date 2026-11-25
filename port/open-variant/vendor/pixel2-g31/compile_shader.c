/* SPDX-License-Identifier: Apache-2.0 */
/* Build-time tool. The target does not load a shader compiler. */
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include "shader_abi.h"
#include "compiler/nir/nir_builder.h"
#include "panfrost/lib/pan_shader.h"
#include "util/u_dynarray.h"

static nir_ssa_def *uniform_at(nir_builder *b, unsigned bits, unsigned offset)
{
    return nir_load_push_constant(b, 1, bits, nir_imm_int(b, 0), .base = offset);
}

#define FIELD(b, name) uniform_at(b, sizeof(((struct g31_uniforms *)0)->name) * 8, \
                                  offsetof(struct g31_uniforms, name))

static nir_ssa_def *pixel_address(nir_builder *b, nir_ssa_def *base, nir_ssa_def *pixel)
{
    return nir_iadd(b, base, nir_u2u64(b, nir_ishl_imm(b, pixel, 2)));
}

static void emit_words(const char *name, const void *data, size_t size)
{
    const uint32_t *words = data;
    printf("static const uint32_t %s[] = {\n", name);
    size_t count = size / sizeof(*words);
    for (size_t i = 0; i < count; ++i)
        printf("0x%08" PRIx32 "u,%c", words[i], (i % 6 == 5 || i + 1 == count) ? '\n' : ' ');
    puts("};");
}

enum shader_kind { SCALAR, TILE_90, TILE_270 };

static void emit_tile(nir_builder *b, enum shader_kind kind, nir_ssa_def *src,
                      nir_ssa_def *dst, nir_ssa_def *step_x)
{
    /* One four-pixel vector in the source becomes one column of the output. */
    if (kind == TILE_270) src = nir_iadd_imm(b, src, -3);
    nir_ssa_def *columns[4];
    for (unsigned column = 0; column < 4; ++column) {
        nir_ssa_def *index = nir_iadd(b, src, nir_imul_imm(b, step_x, column));
        columns[column] = nir_load_global(b, pixel_address(b, FIELD(b, source), index), 16, 4, 32);
    }
    for (unsigned row = 0; row < 4; ++row) {
        nir_ssa_def *pixels[4];
        unsigned lane = kind == TILE_270 ? (3 - row) : row;
        for (unsigned column = 0; column < 4; ++column)
            pixels[column] = nir_channel(b, columns[column], lane);
        nir_ssa_def *index = nir_iadd(b, dst, nir_imul_imm(b, FIELD(b, destination_stride), row));
        nir_store_global(b, pixel_address(b, FIELD(b, destination), index), 16, nir_vec(b, pixels, 4), 0xf);
    }
}

static int compile(enum shader_kind kind, const char *program_name, const char *state_name)
{
    nir_builder b = nir_builder_init_simple_shader(MESA_SHADER_COMPUTE,
            GENX(pan_shader_get_compiler_options)(), "pixel2_rotate_rgba");
    b.shader->info.workgroup_size[0] = G31_GROUP_X;
    b.shader->info.workgroup_size[1] = G31_GROUP_Y;
    b.shader->info.workgroup_size[2] = 1;

    nir_ssa_def *id = nir_load_global_invocation_id(&b, 32);
    nir_ssa_def *x = nir_channel(&b, id, 0);
    nir_ssa_def *y = nir_channel(&b, id, 1);
    if (kind != SCALAR) {
        x = nir_ishl_imm(&b, x, 2);
        y = nir_ishl_imm(&b, y, 2);
    }
    nir_push_if(&b, nir_iand(&b, nir_ult(&b, x, FIELD(&b, width)),
                                  nir_ult(&b, y, FIELD(&b, height))));
    nir_ssa_def *src = nir_iadd(&b, FIELD(&b, source_origin),
                        nir_iadd(&b, nir_imul(&b, x, FIELD(&b, source_step_x)),
                                     nir_imul(&b, y, FIELD(&b, source_step_y))));
    nir_ssa_def *dst = nir_iadd(&b, x, nir_imul(&b, y, FIELD(&b, destination_stride)));
    if (kind == SCALAR) {
        nir_ssa_def *rgba = nir_load_global(&b, pixel_address(&b, FIELD(&b, source), src), 4, 1, 32);
        nir_store_global(&b, pixel_address(&b, FIELD(&b, destination), dst), 4, rgba, 1);
    } else {
        emit_tile(&b, kind, src, dst, FIELD(&b, source_step_x));
    }
    nir_pop_if(&b, NULL);

    struct panfrost_compile_inputs inputs = {
        .gpu_id = 0x7093, .fixed_sysval_ubo = -1, .no_ubo_to_push = true,
    };
    struct util_dynarray binary;
    struct pan_shader_info info;
    util_dynarray_init(&binary, NULL);
    GENX(pan_shader_compile)(b.shader, &inputs, &binary, &info);
    if (!binary.size || binary.size % 16 || info.tls_size || info.wls_size ||
        info.sysvals.sysval_count || info.ubo_count || info.texture_count ||
        info.sampler_count || info.contains_barrier) {
        fprintf(stderr, "Unsupported compiler output for the G31 rotation kernel\n");
        return 1;
    }
    info.push.count = sizeof(struct g31_uniforms) / sizeof(uint32_t);
    struct mali_renderer_state_packed state;
    pan_pack(&state, RENDERER_STATE, rsd) {
        pan_shader_prepare_rsd(&info, 0, &rsd);
    }
    emit_words(program_name, binary.data, binary.size);
    emit_words(state_name, &state, sizeof(state));
    util_dynarray_fini(&binary);
    ralloc_free(b.shader);
    return ferror(stdout) ? 1 : 0;
}

int main(void)
{
    puts("/* Generated from compile_shader.c using Mesa 22.3.7 for Mali-G31. */");
    return compile(SCALAR, "scalar_code", "scalar_state") ||
           compile(TILE_90, "cw90_code", "cw90_state") ||
           compile(TILE_270, "cw270_code", "cw270_state");
}
