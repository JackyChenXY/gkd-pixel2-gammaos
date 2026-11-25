/* SPDX-License-Identifier: Apache-2.0 */
/* Exercise the platform dispatch libraries and switch between three live contexts. */
#include <dlfcn.h>
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES3/gl31.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

enum { SIDE = 16 };
struct api {
    int major;
    EGLint bit;
    EGLSurface surface;
    EGLContext context;
    void *library;
    const GLubyte *(*string)(GLenum);
    void (*color)(GLfloat, GLfloat, GLfloat, GLfloat);
    void (*clear)(GLbitfield);
    void (*read)(GLint, GLint, GLsizei, GLsizei, GLenum, GLenum, void *);
    GLenum (*error)(void);
};

static int start(EGLDisplay display, struct api *a)
{
    const EGLint config_attrs[] = { EGL_SURFACE_TYPE, EGL_PBUFFER_BIT,
        EGL_RENDERABLE_TYPE, a->bit, EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8,
        EGL_BLUE_SIZE, 8, EGL_ALPHA_SIZE, 8, EGL_NONE };
    const EGLint surface_attrs[] = { EGL_WIDTH, SIDE, EGL_HEIGHT, SIDE, EGL_NONE };
    const EGLint context_attrs[] = { EGL_CONTEXT_CLIENT_VERSION, a->major, EGL_NONE };
    EGLConfig config;
    EGLint count;
    if (!eglChooseConfig(display, config_attrs, &config, 1, &count) || count != 1)
        return 0;
    a->surface = eglCreatePbufferSurface(display, config, surface_attrs);
    a->context = eglCreateContext(display, config, EGL_NO_CONTEXT, context_attrs);
    if (!a->surface || !a->context ||
        !eglMakeCurrent(display, a->surface, a->surface, a->context))
        return 0;
    a->library = dlopen(a->major == 1 ? "libGLESv1_CM.so" : "libGLESv2.so", RTLD_NOW);
    if (!a->library)
        return 0;
    a->string = dlsym(a->library, "glGetString");
    a->color = dlsym(a->library, "glClearColor");
    a->clear = dlsym(a->library, "glClear");
    a->read = dlsym(a->library, "glReadPixels");
    a->error = dlsym(a->library, "glGetError");
    if (!a->string || !a->color || !a->clear || !a->read || !a->error)
        return 0;
    const GLubyte *version = a->string(GL_VERSION);
    const GLubyte *renderer = a->string(GL_RENDERER);
    if (!version || !renderer)
        return 0;
    printf("ES%d requested: %s / %s\n", a->major, version, renderer);
    a->color(a->major == 1, a->major == 2, a->major == 3, 1.0f);
    a->clear(GL_COLOR_BUFFER_BIT);
    return a->error() == GL_NO_ERROR;
}

static int check_compute(void)
{
    const char *source =
        "#version 310 es\n"
        "layout(local_size_x=4) in;\n"
        "layout(std430,binding=0) buffer Data { uint values[]; };\n"
        "void main() { uint i=gl_GlobalInvocationID.x; values[i]=i*i+17u; }\n";
    GLuint shader = glCreateShader(GL_COMPUTE_SHADER);
    GLuint program = glCreateProgram();
    GLuint buffer = 0;
    GLint success = 0;
    int valid = 0;
    glShaderSource(shader, 1, &source, NULL);
    glCompileShader(shader);
    glGetShaderiv(shader, GL_COMPILE_STATUS, &success);
    if (!success) goto done;
    glAttachShader(program, shader);
    glLinkProgram(program);
    glGetProgramiv(program, GL_LINK_STATUS, &success);
    if (!success) goto done;
    glUseProgram(program);
    glGenBuffers(1, &buffer);
    glBindBuffer(GL_SHADER_STORAGE_BUFFER, buffer);
    glBufferData(GL_SHADER_STORAGE_BUFFER, 64 * sizeof(GLuint), NULL, GL_DYNAMIC_READ);
    glBindBufferBase(GL_SHADER_STORAGE_BUFFER, 0, buffer);
    glDispatchCompute(16, 1, 1);
    glMemoryBarrier(GL_BUFFER_UPDATE_BARRIER_BIT);
    const GLuint *values = glMapBufferRange(GL_SHADER_STORAGE_BUFFER, 0,
                                             64 * sizeof(GLuint), GL_MAP_READ_BIT);
    if (!values) goto done;
    valid = 1;
    for (GLuint i = 0; i < 64; ++i)
        if (values[i] != i * i + 17) valid = 0;
    if (!glUnmapBuffer(GL_SHADER_STORAGE_BUFFER)) valid = 0;
done:
    glUseProgram(0);
    glDeleteBuffers(1, &buffer);
    glDeleteProgram(program);
    glDeleteShader(shader);
    return valid && glGetError() == GL_NO_ERROR;
}

int main(void)
{
    struct api apis[] = {{.major=1, .bit=EGL_OPENGL_ES_BIT},
                         {.major=2, .bit=EGL_OPENGL_ES2_BIT},
                         {.major=3, .bit=EGL_OPENGL_ES3_BIT_KHR}};
    EGLDisplay d = eglGetDisplay(EGL_DEFAULT_DISPLAY);
    int result = 1;
    if (d == EGL_NO_DISPLAY || !eglInitialize(d, NULL, NULL) || !eglBindAPI(EGL_OPENGL_ES_API))
        goto done;
    for (int i = 0; i < 3; ++i)
        if (!start(d, &apis[i]))
            goto done;
    for (int i = 2; i >= 0; --i) {
        struct api *a = &apis[i];
        uint8_t pixels[SIDE * SIDE][4];
        const uint8_t expected[] = {i == 0 ? 255 : 0, i == 1 ? 255 : 0,
                                    i == 2 ? 255 : 0, 255};
        if (!eglMakeCurrent(d, a->surface, a->surface, a->context))
            goto done;
        a->read(0, 0, SIDE, SIDE, GL_RGBA, GL_UNSIGNED_BYTE, pixels);
        if (a->error() != GL_NO_ERROR)
            goto done;
        for (int p = 0; p < SIDE * SIDE; ++p)
            if (memcmp(pixels[p], expected, 4) != 0)
                goto done;
        printf("ES%d: %d RGBA pixels match\n", a->major, SIDE * SIDE);
        if (a->major == 3) {
            if (!check_compute()) goto done;
            puts("ES3.1: all 64 compute-shader results match");
        }
    }
    result = 0;
done:
    if (result)
        fprintf(stderr, "EGL / GLES context or pixel validation failed (EGL 0x%x)\n", eglGetError());
    if (d != EGL_NO_DISPLAY) {
        eglMakeCurrent(d, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
        for (int i = 0; i < 3; ++i) {
            if (apis[i].surface) eglDestroySurface(d, apis[i].surface);
            if (apis[i].context) eglDestroyContext(d, apis[i].context);
            if (apis[i].library) dlclose(apis[i].library);
        }
        eglTerminate(d);
    }
    return result;
}
