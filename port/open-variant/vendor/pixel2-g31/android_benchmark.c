/* SPDX-License-Identifier: Apache-2.0 */
#include "android_surface.h"
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES3/gl3.h>
#include <GLES2/gl2ext.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

struct image {
    AHardwareBuffer *native;
    struct g31_surface *view;
    EGLImageKHR image;
    GLuint texture;
    uint32_t w, h, stride;
};

static EGLDisplay display;
static PFNEGLGETNATIVECLIENTBUFFERANDROIDPROC native_client;
static PFNEGLCREATEIMAGEKHRPROC create_image;
static PFNEGLDESTROYIMAGEKHRPROC destroy_image;
static PFNGLEGLIMAGETARGETTEXTURE2DOESPROC bind_image;

static void require(bool ok, const char *where)
{
    if (!ok) {
        fprintf(stderr, "%s failed (EGL 0x%x, GL 0x%x)\n", where, eglGetError(), glGetError());
        exit(1);
    }
}

static GLuint shader(GLenum type, const char *text)
{
    GLuint id = glCreateShader(type);
    glShaderSource(id, 1, &text, NULL);
    glCompileShader(id);
    GLint ok;
    glGetShaderiv(id, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[1024];
        glGetShaderInfoLog(id, sizeof(log), NULL, log);
        fprintf(stderr, "%s\n", log);
        exit(1);
    }
    return id;
}

static GLuint program(void)
{
    GLuint v = shader(GL_VERTEX_SHADER,
        "#version 300 es\nvoid main(){ vec2 p = vec2(gl_VertexID == 1 ? 3.0 : -1.0,"
        "gl_VertexID == 2 ? 3.0 : -1.0); gl_Position = vec4(p, 0.0, 1.0); }");
    GLuint f = shader(GL_FRAGMENT_SHADER,
        "#version 300 es\nprecision highp float; precision highp int; uniform highp sampler2D src;"
        "uniform int srcWidth; out vec4 color; void main(){ivec2 p=ivec2(gl_FragCoord.xy);"
        "color=texelFetch(src, ivec2(srcWidth-1-p.y, p.x), 0);}");
    GLuint prog = glCreateProgram();
    glAttachShader(prog, v);
    glAttachShader(prog, f);
    glLinkProgram(prog);
    GLint ok;
    glGetProgramiv(prog, GL_LINK_STATUS, &ok);
    require(ok, "link rotation shader");
    glDeleteShader(v);
    glDeleteShader(f);
    return prog;
}

static struct image allocate_image(struct g31_device *dev, unsigned w, unsigned h)
{
    AHardwareBuffer_Desc desc = {
        .width = w, .height = h, .layers = 1, .format = AHARDWAREBUFFER_FORMAT_R8G8B8A8_UNORM,
        .usage = AHARDWAREBUFFER_USAGE_GPU_SAMPLED_IMAGE | AHARDWAREBUFFER_USAGE_GPU_COLOR_OUTPUT |
                 AHARDWAREBUFFER_USAGE_CPU_READ_OFTEN | AHARDWAREBUFFER_USAGE_CPU_WRITE_OFTEN,
    };
    struct image im = { .w = w, .h = h };
    require(AHardwareBuffer_allocate(&desc, &im.native) == 0, "allocate AHardwareBuffer");
    AHardwareBuffer_describe(im.native, &desc);
    im.stride = desc.stride;
    im.view = g31_import_android(dev, im.native);
    if (!im.view) { perror("import minigbm buffer"); exit(1); }
    const EGLint attrs[] = {EGL_IMAGE_PRESERVED_KHR, EGL_TRUE, EGL_NONE};
    im.image = create_image(display, EGL_NO_CONTEXT, EGL_NATIVE_BUFFER_ANDROID, native_client(im.native), attrs);
    require(im.image != EGL_NO_IMAGE_KHR, "EGL image from same AHardwareBuffer");
    glGenTextures(1, &im.texture);
    glBindTexture(GL_TEXTURE_2D, im.texture);
    bind_image(GL_TEXTURE_2D, im.image);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    require(glGetError() == GL_NO_ERROR, "bind imported texture");
    return im;
}

static void free_image(struct image *im)
{
    glDeleteTextures(1, &im->texture);
    destroy_image(display, im->image);
    g31_destroy(im->view);
    AHardwareBuffer_release(im->native);
}

static uint32_t pattern(unsigned x, unsigned y, unsigned seed)
{
    uint32_t bits = 0x9e3779b9u * (y + seed * 597u) + x;
    bits ^= bits >> 15;
    return bits * 0x85ebca6bu;
}

static void fill(struct image *im, unsigned seed, bool clear)
{
    void *map = NULL;
    require(AHardwareBuffer_lock(im->native, AHARDWAREBUFFER_USAGE_CPU_WRITE_OFTEN, -1, NULL, &map) == 0,
            "lock CPU writer");
    uint32_t *p = map;
    for (unsigned y = 0; y < im->h; ++y)
        for (unsigned x = 0; x < im->w; ++x)
            p[y * im->stride + x] = clear ? 0x75260fe3u : pattern(x, y, seed);
    require(AHardwareBuffer_unlock(im->native, NULL) == 0, "unlock CPU writer");
}

static void verify(struct image *dst, unsigned source_width, unsigned seed)
{
    void *map = NULL;
    require(AHardwareBuffer_lock(dst->native, AHARDWAREBUFFER_USAGE_CPU_READ_OFTEN, -1, NULL, &map) == 0,
            "lock CPU reader");
    const uint32_t *p = map;
    for (unsigned y = 0; y < dst->h; ++y) {
        for (unsigned x = 0; x < dst->w; ++x) {
            uint32_t want = pattern(source_width - 1 - y, x, seed);
            if (p[y * dst->stride + x] != want) {
                fprintf(stderr, "bad pixel at %u,%u: %08x vs %08x\n", x, y, p[y * dst->stride + x], want);
                exit(1);
            }
        }
    }
    require(AHardwareBuffer_unlock(dst->native, NULL) == 0, "unlock CPU reader");
}

static uint64_t now_ns(void)
{
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC, &t) < 0) { perror("clock"); exit(1); }
    return (uint64_t)t.tv_sec * 1000000000u + t.tv_nsec;
}

static void run_size(struct g31_device *dev, GLuint prog, unsigned w, unsigned h)
{
    struct image src = allocate_image(dev, w, h);
    struct image dst = allocate_image(dev, h, w);
    GLuint fb;
    glGenFramebuffers(1, &fb);
    glBindFramebuffer(GL_FRAMEBUFFER, fb);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, dst.texture, 0);
    require(glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE, "shared destination FBO");
    glViewport(0, 0, h, w);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, src.texture);
    glUseProgram(prog);
    glUniform1i(glGetUniformLocation(prog, "src"), 0);
    glUniform1i(glGetUniformLocation(prog, "srcWidth"), w);
    glDisable(GL_DITHER);
    glFinish();
    const bool direct[] = {true, false, false, true, false, true, true, false};
    const GLenum target = GL_COLOR_ATTACHMENT0;
    enum { WARMUP = 8, SAMPLES = 32 };
    for (unsigned block = 0; block < sizeof(direct) / sizeof(direct[0]); ++block) {
        unsigned seed = 1 + block;
        fill(&src, seed, false);
        fill(&dst, seed, true);
        uint64_t durations[SAMPLES];
        for (int i = -WARMUP; i < SAMPLES; ++i) {
            uint64_t start = now_ns();
            if (direct[block]) {
                if (g31_rotate(src.view, dst.view, 270) != 0) { perror("rotate shared image"); exit(1); }
            } else {
                glInvalidateFramebuffer(GL_FRAMEBUFFER, 1, &target);
                glDrawArrays(GL_TRIANGLES, 0, 3);
                glFinish();
            }
            uint64_t elapsed = now_ns() - start;
            if (i >= 0) durations[i] = elapsed;
        }
        require(glGetError() == GL_NO_ERROR, "GLES rotation");
        verify(&dst, w, seed);
        printf("PASS_SHARED %u %u %u %s", w, h, block + 1, direct[block] ? "direct" : "mesa");
        for (unsigned i = 0; i < SAMPLES; ++i) printf(" %.3f", (double)durations[i] / 1e6);
        putchar('\n');
        fflush(stdout);
    }
    glDeleteFramebuffers(1, &fb);
    free_image(&dst);
    free_image(&src);
}

int main(void)
{
    display = eglGetDisplay(EGL_DEFAULT_DISPLAY);
    require(display != EGL_NO_DISPLAY && eglInitialize(display, NULL, NULL), "initialize EGL");
    const EGLint cfg_attrs[] = {
        EGL_SURFACE_TYPE, EGL_PBUFFER_BIT, EGL_RENDERABLE_TYPE, EGL_OPENGL_ES3_BIT_KHR,
        EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8, EGL_ALPHA_SIZE, 8, EGL_NONE
    };
    EGLConfig cfg;
    EGLint count;
    require(eglChooseConfig(display, cfg_attrs, &cfg, 1, &count) && count == 1, "choose GLES3 config");
    const EGLint pbuf[] = {EGL_WIDTH, 1, EGL_HEIGHT, 1, EGL_NONE};
    const EGLint attr[] = {EGL_CONTEXT_CLIENT_VERSION, 3, EGL_NONE};
    EGLSurface surface = eglCreatePbufferSurface(display, cfg, pbuf);
    EGLContext ctx = eglCreateContext(display, cfg, EGL_NO_CONTEXT, attr);
    require(eglMakeCurrent(display, surface, surface, ctx), "activate offscreen context");
    native_client = (PFNEGLGETNATIVECLIENTBUFFERANDROIDPROC)eglGetProcAddress("eglGetNativeClientBufferANDROID");
    create_image = (PFNEGLCREATEIMAGEKHRPROC)eglGetProcAddress("eglCreateImageKHR");
    destroy_image = (PFNEGLDESTROYIMAGEKHRPROC)eglGetProcAddress("eglDestroyImageKHR");
    bind_image = (PFNGLEGLIMAGETARGETTEXTURE2DOESPROC)eglGetProcAddress("glEGLImageTargetTexture2DOES");
    require(native_client && create_image && destroy_image && bind_image, "Android EGL image functions");
    GLuint prog = program();
    struct g31_device *dev = g31_open();
    if (!dev) { perror("open G31"); return 1; }
    printf("GLES %s | %s\n", glGetString(GL_RENDERER), glGetString(GL_VERSION));
    puts("270 degrees clockwise; identical shared RGBA8888 source and destination per size; elapsed ms through completion");
    run_size(dev, prog, 480, 272);
    run_size(dev, prog, 640, 480);
    g31_close(dev);
    glDeleteProgram(prog);
    eglMakeCurrent(display, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
    eglDestroyContext(display, ctx);
    eglDestroySurface(display, surface);
    eglTerminate(display);
    return 0;
}
