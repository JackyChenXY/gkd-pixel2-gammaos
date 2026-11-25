#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES3/gl3.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

enum { WIDTH = 320, HEIGHT = 240, TEX_SIZE = 256, WARMUP = 20, SAMPLES = 72 };
static uint8_t texture_data[TEX_SIZE * TEX_SIZE * 4];

static const char vertex_source[] =
    "#version 300 es\n"
    "void main() {\n"
    "  vec2 p = vec2(gl_VertexID == 1 ? 3.0 : -1.0,\n"
    "                gl_VertexID == 2 ? 3.0 : -1.0);\n"
    "  gl_Position = vec4(p, 0.0, 1.0);\n"
    "}\n";

static const char fragment_preamble[] =
    "#version 300 es\n"
    "precision highp float;\n"
    "precision highp int;\n"
    "uniform highp sampler2D source;\n"
    "uniform ivec2 offset;\n"
    "out vec4 color;\n"
    "vec4 tap(ivec2 p) { return texelFetch(source, p & ivec2(255), 0); }\n";

static const char fragment_blit[] =
    "void main() { color = tap(ivec2(gl_FragCoord.xy) + offset); }\n";

static const char fragment_filter[] =
    "void main() {\n"
    "  ivec2 p = ivec2(gl_FragCoord.xy) + offset;\n"
    "  vec4 cardinal = tap(p + ivec2(-1, 0)) + tap(p + ivec2(1, 0))\n"
    "                + tap(p + ivec2(0, -1)) + tap(p + ivec2(0, 1));\n"
    "  vec4 diagonal = tap(p + ivec2(-1, -1)) + tap(p + ivec2(1, -1))\n"
    "                + tap(p + ivec2(-1, 1)) + tap(p + ivec2(1, 1));\n"
    "  color = (tap(p) * 4.0 + cardinal * 2.0 + diagonal) * (1.0 / 16.0);\n"
    "}\n";

static double now_ms(void) {
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now) != 0) {
        perror("clock_gettime");
        exit(2);
    }
    return now.tv_sec * 1000.0 + now.tv_nsec / 1000000.0;
}

static GLuint compile_shader(GLenum type, const char *const *sources, GLsizei count) {
    GLuint shader = glCreateShader(type);
    glShaderSource(shader, count, sources, NULL);
    glCompileShader(shader);
    GLint success = GL_FALSE;
    glGetShaderiv(shader, GL_COMPILE_STATUS, &success);
    if (success == GL_TRUE) {
        return shader;
    }

    char log[1024] = {0};
    glGetShaderInfoLog(shader, sizeof(log), NULL, log);
    fprintf(stderr, "Shader compilation failed: %s\n", log);
    glDeleteShader(shader);
    return 0;
}

static GLuint make_program(const char *fragment_body) {
    const char *vertex_parts[] = {vertex_source};
    GLuint vertex = compile_shader(GL_VERTEX_SHADER, vertex_parts, 1);
    if (vertex == 0) {
        return 0;
    }

    const char *fragment_parts[] = {fragment_preamble, fragment_body};
    GLuint fragment = compile_shader(GL_FRAGMENT_SHADER, fragment_parts, 2);
    if (fragment == 0) {
        glDeleteShader(vertex);
        return 0;
    }

    GLuint program = glCreateProgram();
    glAttachShader(program, vertex);
    glAttachShader(program, fragment);
    glLinkProgram(program);
    glDeleteShader(fragment);
    glDeleteShader(vertex);

    GLint success = GL_FALSE;
    glGetProgramiv(program, GL_LINK_STATUS, &success);
    if (success == GL_TRUE) {
        return program;
    }

    char log[1024] = {0};
    glGetProgramInfoLog(program, sizeof(log), NULL, log);
    fprintf(stderr, "Program link failed: %s\n", log);
    glDeleteProgram(program);
    return 0;
}

static GLuint make_texture(void) {
    for (int y = 0; y < TEX_SIZE; ++y) {
        for (int x = 0; x < TEX_SIZE; ++x) {
            size_t index = ((size_t)y * TEX_SIZE + x) * 4;
            texture_data[index] = (17 * x + 29 * y + 31) & 255;
            texture_data[index + 1] = (47 * x + 7 * y + 19) & 255;
            texture_data[index + 2] = (13 * x + 37 * y + 23) & 255;
            texture_data[index + 3] = 255;
        }
    }

    GLuint texture = 0;
    glGenTextures(1, &texture);
    glBindTexture(GL_TEXTURE_2D, texture);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, TEX_SIZE, TEX_SIZE, 0, GL_RGBA,
                 GL_UNSIGNED_BYTE, texture_data);
    glFinish();
    return texture;
}

static int source_component(int x, int y, int component) {
    return texture_data[(((y & 255) * TEX_SIZE) + (x & 255)) * 4 + component];
}

static int expected_component(int x, int y, int component, int filtered) {
    if (!filtered) {
        return source_component(x, y, component);
    }
    static const int weights[] = {1, 2, 1};
    int sum = 0;
    for (int dy = -1; dy <= 1; ++dy) {
        for (int dx = -1; dx <= 1; ++dx) {
            sum += weights[dx + 1] * weights[dy + 1] *
                   source_component(x + dx, y + dy, component);
        }
    }
    return (sum + 8) / 16;
}

static int verify_output(int offset_x, int offset_y, int filtered, uint32_t *checksum) {
    static const int points[][2] = {{37, 53}, {151, 102}, {319, 239}, {0, 0}};
    uint32_t hash = 2166136261u;
    for (size_t i = 0; i < sizeof(points) / sizeof(points[0]); ++i) {
        int x = points[i][0];
        int y = points[i][1];
        GLubyte pixel[4] = {0};
        glReadPixels(x, y, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, pixel);
        for (int component = 0; component < 4; ++component) {
            int expected = expected_component(x + offset_x, y + offset_y, component, filtered);
            int tolerance = filtered ? 1 : 0;
            if (abs((int)pixel[component] - expected) > tolerance) {
                fprintf(stderr, "Unexpected pixel %d,%d channel %d: %u vs expected %d\n",
                        x, y, component, pixel[component], expected);
                return 0;
            }
            hash = (hash ^ pixel[component]) * 16777619u;
        }
    }
    *checksum = hash;
    return 1;
}

static int compare_double(const void *a, const void *b) {
    double left = *(const double *)a;
    double right = *(const double *)b;
    return (left > right) - (left < right);
}

static int draw_benchmark(const char *name, const char *body, int filtered) {
    double start = now_ms();
    GLuint program = make_program(body);
    double build_ms = now_ms() - start;
    if (program == 0) {
        return 0;
    }

    glUseProgram(program);
    GLint offset = glGetUniformLocation(program, "offset");
    if (offset == -1) {
        fprintf(stderr, "Unable to resolve the source offset\n");
        glDeleteProgram(program);
        return 0;
    }

    double samples[SAMPLES];
    double first_draw_ms = 0;
    int offset_x = 0;
    int offset_y = 0;
    for (int frame = 0; frame < WARMUP + SAMPLES; ++frame) {
        offset_x = (frame * 3) & 255;
        offset_y = (frame * 5) & 255;
        start = now_ms();
        glUniform2i(offset, offset_x, offset_y);
        glDrawArrays(GL_TRIANGLES, 0, 3);
        glFinish();
        double elapsed = now_ms() - start;
        if (frame == 0) {
            first_draw_ms = elapsed;
        }
        if (frame >= WARMUP) {
            samples[frame - WARMUP] = elapsed;
        }
    }

    uint32_t checksum = 0;
    int valid = verify_output(offset_x, offset_y, filtered, &checksum);
    GLenum error = glGetError();
    glDeleteProgram(program);
    if (!valid || error != GL_NO_ERROR) {
        fprintf(stderr, "%s verification failed, GL error 0x%x\n", name, error);
        return 0;
    }

    qsort(samples, SAMPLES, sizeof(samples[0]), compare_double);
    double median = (samples[SAMPLES / 2 - 1] + samples[SAMPLES / 2]) / 2.0;
    double p95 = samples[(SAMPLES * 95 + 99) / 100 - 1];
    printf("%s samples=%d median_ms=%.3f p95_ms=%.3f shader_build_ms=%.3f "
           "first_draw_ms=%.3f checksum=%08x pixels=pass\n",
           name, SAMPLES, median, p95, build_ms, first_draw_ms, (unsigned)checksum);
    fflush(stdout);
    return 1;
}

int main(void) {
    EGLDisplay display = eglGetDisplay(EGL_DEFAULT_DISPLAY);
    if (display == EGL_NO_DISPLAY || !eglInitialize(display, NULL, NULL)) {
        fprintf(stderr, "EGL initialization failed: 0x%x\n", eglGetError());
        return 2;
    }

    const EGLint config_attributes[] = {
        EGL_SURFACE_TYPE, EGL_PBUFFER_BIT,
        EGL_RENDERABLE_TYPE, EGL_OPENGL_ES3_BIT_KHR,
        EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8, EGL_ALPHA_SIZE, 8,
        EGL_NONE
    };
    const EGLint surface_attributes[] = {EGL_WIDTH, WIDTH, EGL_HEIGHT, HEIGHT, EGL_NONE};
    const EGLint context_attributes[] = {EGL_CONTEXT_CLIENT_VERSION, 3, EGL_NONE};
    EGLConfig config;
    EGLint count = 0;
    EGLContext context = EGL_NO_CONTEXT;
    EGLSurface surface = EGL_NO_SURFACE;
    int result = 2;

    if (!eglBindAPI(EGL_OPENGL_ES_API) ||
        !eglChooseConfig(display, config_attributes, &config, 1, &count) || count == 0) {
        fprintf(stderr, "EGL GLES3 configuration unavailable: 0x%x\n", eglGetError());
        goto done;
    }

    context = eglCreateContext(display, config, EGL_NO_CONTEXT, context_attributes);
    surface = eglCreatePbufferSurface(display, config, surface_attributes);
    if (context == EGL_NO_CONTEXT || surface == EGL_NO_SURFACE ||
        !eglMakeCurrent(display, surface, surface, context)) {
        fprintf(stderr, "EGL GLES3 pbuffer initialization failed: 0x%x\n", eglGetError());
        goto done;
    }

    printf("renderer=%s\nversion=%s\nsize=%dx%d warmup=%d\n",
           (const char *)glGetString(GL_RENDERER), (const char *)glGetString(GL_VERSION),
           WIDTH, HEIGHT, WARMUP);
    fflush(stdout);

    glViewport(0, 0, WIDTH, HEIGHT);
    glDisable(GL_DITHER);
    GLuint texture = make_texture();
    int blit_ok = draw_benchmark("blit", fragment_blit, 0);
    int filter_ok = draw_benchmark("filter3x3", fragment_filter, 1);
    glDeleteTextures(1, &texture);
    result = blit_ok && filter_ok ? 0 : 3;

done:
    eglMakeCurrent(display, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
    if (surface != EGL_NO_SURFACE) {
        eglDestroySurface(display, surface);
    }
    if (context != EGL_NO_CONTEXT) {
        eglDestroyContext(display, context);
    }
    eglTerminate(display);
    return result;
}
