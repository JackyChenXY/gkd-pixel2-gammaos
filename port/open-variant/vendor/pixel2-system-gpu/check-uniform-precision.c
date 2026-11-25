/* SPDX-License-Identifier: MIT */
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES3/gl3.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct test_case {
    const char *name;
    bool es300;
    const char *vertex_declaration;
    const char *fragment_declaration;
    const char *vertex_value;
    const char *fragment_value;
    const char *location;
    int contributions;
    bool check_highp;
    bool expect_link;
};

static const struct test_case cases[] = {
    {"vertex highp, fragment unused", false, "highp mat4 m", "mediump mat4 m",
     "(m[0][0]-2048.0)", "0.0", "m", 1, true, true},
    {"fragment highp, vertex unused", false, "lowp mat4 m", "highp mat4 m",
     "0.0", "(m[0][0]-2048.0)", "m", 1, true, true},
    {"vertex mediump, fragment unused", false, "mediump mat4 m", "highp mat4 m",
     "m[0][0]", "0.0", "m", 1, false, true},
    {"fragment mediump, vertex unused", false, "highp mat4 m", "mediump mat4 m",
     "0.0", "m[0][0]", "m", 1, false, true},
    {"same array shape, active half", false, "highp mat4 m[2]", "mediump mat4 m[2]",
     "0.0", "m[1][0][0]", "m[1]", 1, false, true},
    {"both unused", false, "highp mat4 m", "mediump mat4 m",
     "0.25", "0.0", "m", 0, false, true},
    {"matching active mediump", false, "mediump mat4 m", "mediump mat4 m",
     "m[0][0]", "m[0][0]", "m", 2, false, true},
    {"matching active highp", false, "highp mat4 m", "highp mat4 m",
     "m[0][0]", "m[0][0]", "m", 2, false, true},
    {"different matrix dimensions", false, "highp mat4 m", "mediump mat3 m",
     "m[0][0]", "0.0", "m", 0, false, false},
    {"vector versus matrix", false, "highp mat4 m", "mediump vec4 m",
     "m[0][0]", "0.0", "m", 0, false, false},
    {"integer versus float matrix", false, "highp mat4 m", "mediump int m",
     "m[0][0]", "0.0", "m", 0, false, false},
    {"different array lengths", false, "highp mat4 m[2]", "mediump mat4 m[3]",
     "m[1][0][0]", "0.0", "m[1]", 0, false, false},
    {"both stages use mismatched precision", false, "highp mat4 m", "mediump mat4 m",
     "m[0][0]", "m[0][0]", "m", 0, false, false},
    {"ESSL 3.00 requires a match even if unused", true, "highp mat4 m", "mediump mat4 m",
     "m[0][0]", "0.0", "m", 0, false, false},
    {"ESSL 3.00 matching precision", true, "mediump mat4 m", "mediump mat4 m",
     "m[0][0]", "m[0][0]", "m", 2, false, true},
};

static GLuint compile_shader(GLenum type, const char *source)
{
    GLuint shader = glCreateShader(type);
    glShaderSource(shader, 1, &source, NULL);
    glCompileShader(shader);
    GLint compiled = 0;
    glGetShaderiv(shader, GL_COMPILE_STATUS, &compiled);
    if (!compiled) {
        char log[512] = {0};
        glGetShaderInfoLog(shader, sizeof(log), NULL, log);
        fprintf(stderr, "Fixture did not compile: %s\n", log);
        glDeleteShader(shader);
        return 0;
    }
    return shader;
}

static bool check_pixels(GLuint program, const struct test_case *test)
{
    GLint location = glGetUniformLocation(program, test->location);
    if ((location >= 0) != (test->contributions > 0))
        return false;
    glUseProgram(program);
    for (int sample = 0; sample < 2; ++sample) {
        float value = sample ? 0.375f : 0.25f;
        float matrix[16] = {value + (test->check_highp ? 2048.0f : 0.0f)};
        if (location >= 0)
            glUniformMatrix4fv(location, 1, GL_FALSE, matrix);
        glClearColor(0, 0, 0, 0);
        glClear(GL_COLOR_BUFFER_BIT);
        glDrawArrays(GL_TRIANGLES, 0, 3);
        GLubyte pixels[8 * 8][4];
        glReadPixels(0, 0, 8, 8, GL_RGBA, GL_UNSIGNED_BYTE, pixels);
        int red = (int)(255.0f * (test->contributions ? value * test->contributions : 0.25f) + 0.5f);
        for (size_t i = 0; i < sizeof(pixels) / sizeof(pixels[0]); ++i) {
            if (abs((int)pixels[i][0] - red) > 2 || abs((int)pixels[i][1] - 64) > 1 ||
                pixels[i][2] != 0 || pixels[i][3] != 255) {
                fprintf(stderr, "  sample %d pixel %zu = %u,%u,%u,%u (expected red %d)\n",
                        sample, i, pixels[i][0], pixels[i][1], pixels[i][2], pixels[i][3], red);
                return false;
            }
        }
    }
    return glGetError() == GL_NO_ERROR;
}

static bool run_case(const struct test_case *test)
{
    char vert[600], frag[600], info[400] = {0};
    const char *version = test->es300 ? "#version 300 es\n" : "#version 100\n";
    snprintf(vert, sizeof(vert),
             "%sprecision highp float;\n%s vec2 point;\n%s mediump float shade;\n"
             "uniform %s;\nvoid main(){gl_Position=vec4(point,0.0,1.0);shade=%s;}\n",
             version, test->es300 ? "in" : "attribute", test->es300 ? "out" : "varying",
             test->vertex_declaration, test->vertex_value);
    snprintf(frag, sizeof(frag),
             "%sprecision highp float;\n%s mediump float shade;\n%s\n"
             "uniform %s;\nvoid main(){%s=vec4(shade+(%s),0.25,0.0,1.0);}\n",
             version, test->es300 ? "in" : "varying", test->es300 ? "out vec4 result;" : "",
             test->fragment_declaration, test->es300 ? "result" : "gl_FragColor", test->fragment_value);
    GLuint vs = compile_shader(GL_VERTEX_SHADER, vert);
    GLuint fs = compile_shader(GL_FRAGMENT_SHADER, frag);
    GLuint program = glCreateProgram();
    bool ok = false;
    if (vs && fs) {
        glAttachShader(program, vs);
        glAttachShader(program, fs);
        glBindAttribLocation(program, 0, "point");
        glLinkProgram(program);
        GLint linked = 0;
        glGetProgramiv(program, GL_LINK_STATUS, &linked);
        ok = test->expect_link ? (linked && check_pixels(program, test)) : !linked;
        if (!ok)
            glGetProgramInfoLog(program, sizeof(info), NULL, info);
    }
    printf("%s  %s%s%s\n", ok ? "PASS" : "FAIL", test->name, *info ? " -- " : "", info);
    glUseProgram(0);
    glDeleteProgram(program);
    glDeleteShader(vs);
    glDeleteShader(fs);
    return ok;
}

int main(void)
{
    EGLDisplay d = eglGetDisplay(EGL_DEFAULT_DISPLAY);
    EGLConfig config;
    EGLint num = 0;
    const EGLint config_attr[] = {EGL_SURFACE_TYPE, EGL_PBUFFER_BIT,
        EGL_RENDERABLE_TYPE, EGL_OPENGL_ES3_BIT_KHR, EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8,
        EGL_BLUE_SIZE, 8, EGL_ALPHA_SIZE, 8, EGL_NONE};
    const EGLint surface_attr[] = {EGL_WIDTH, 8, EGL_HEIGHT, 8, EGL_NONE};
    const EGLint context_attr[] = {EGL_CONTEXT_CLIENT_VERSION, 3, EGL_NONE};
    if (!eglInitialize(d, NULL, NULL) || !eglBindAPI(EGL_OPENGL_ES_API) ||
        !eglChooseConfig(d, config_attr, &config, 1, &num) || num != 1)
        return 2;
    EGLSurface surface = eglCreatePbufferSurface(d, config, surface_attr);
    EGLContext context = eglCreateContext(d, config, EGL_NO_CONTEXT, context_attr);
    if (!eglMakeCurrent(d, surface, surface, context))
        return 2;
    printf("%s / %s\n", glGetString(GL_RENDERER), glGetString(GL_VERSION));
    GLuint vbo = 0;
    const GLfloat vertices[] = {-1, -1, 3, -1, -1, 3};
    glGenBuffers(1, &vbo);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(vertices), vertices, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, NULL);
    glViewport(0, 0, 8, 8);
    int failed = 0;
    for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); ++i)
        if (!run_case(&cases[i])) ++failed;
    printf("%d of %zu cases failed\n", failed, sizeof(cases) / sizeof(cases[0]));
    glDeleteBuffers(1, &vbo);
    eglMakeCurrent(d, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
    eglDestroySurface(d, surface);
    eglDestroyContext(d, context);
    eglTerminate(d);
    return failed ? 1 : 0;
}
