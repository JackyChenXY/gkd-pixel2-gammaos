#define _GNU_SOURCE
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES2/gl2.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/sync_file.h>
#include <poll.h>
#include <signal.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

#define REQUIRE(condition, operation) do { \
    if (!(condition)) { \
        fprintf(stderr, "%s failed (EGL=0x%x, GL=0x%x, errno=%d)\n", \
                operation, eglGetError(), glGetError(), errno); \
        goto cleanup; \
    } \
} while (0)

static void deadline(int sig)
{
    (void)sig;
    static const char msg[] = "KHR_FENCE result=fail process_timeout\n";
    (void)write(STDERR_FILENO, msg, sizeof(msg) - 1);
    _exit(124);
}

static bool extension(const char *list, const char *name)
{
    if (!list)
        return false;
    size_t len = strlen(name);
    for (const char *found = strstr(list, name); found;
         found = strstr(found + len, name)) {
        if ((found == list || found[-1] == ' ') &&
            (found[len] == '\0' || found[len] == ' '))
            return true;
    }
    return false;
}

int main(void)
{
    int status = 1, exported = -1, import_fd = -1;
    EGLDisplay display = EGL_NO_DISPLAY;
    EGLSurface surface = EGL_NO_SURFACE;
    EGLContext context = EGL_NO_CONTEXT;
    EGLSyncKHR original = EGL_NO_SYNC_KHR, imported = EGL_NO_SYNC_KHR;
    bool initialized = false;
    PFNEGLDESTROYSYNCKHRPROC destroy_sync = NULL;
    signal(SIGALRM, deadline);
    alarm(8);

    display = eglGetDisplay(EGL_DEFAULT_DISPLAY);
    REQUIRE(display != EGL_NO_DISPLAY, "eglGetDisplay");
    EGLint major, minor;
    REQUIRE(eglInitialize(display, &major, &minor), "eglInitialize");
    initialized = true;
    const char *exts = eglQueryString(display, EGL_EXTENSIONS);
    bool native = extension(exts, "EGL_ANDROID_native_fence_sync");
    bool age = extension(exts, "EGL_EXT_buffer_age");
    bool partial = extension(exts, "EGL_KHR_partial_update");
    printf("EGL_VERSION=%d.%d native_fence_sync=%d buffer_age=%d partial_update=%d\n",
           major, minor, native, age, partial);
    if (!native) {
        puts("KHR_FENCE result=skip native_fence_not_advertised");
        status = 3;
        goto cleanup;
    }

    PFNEGLCREATESYNCKHRPROC create_sync =
        (PFNEGLCREATESYNCKHRPROC)eglGetProcAddress("eglCreateSyncKHR");
    destroy_sync = (PFNEGLDESTROYSYNCKHRPROC)eglGetProcAddress("eglDestroySyncKHR");
    PFNEGLCLIENTWAITSYNCKHRPROC client_wait =
        (PFNEGLCLIENTWAITSYNCKHRPROC)eglGetProcAddress("eglClientWaitSyncKHR");
    PFNEGLDUPNATIVEFENCEFDANDROIDPROC dup_fence =
        (PFNEGLDUPNATIVEFENCEFDANDROIDPROC)eglGetProcAddress("eglDupNativeFenceFDANDROID");
    PFNEGLWAITSYNCKHRPROC server_wait =
        (PFNEGLWAITSYNCKHRPROC)eglGetProcAddress("eglWaitSyncKHR");
    REQUIRE(create_sync && destroy_sync && client_wait && dup_fence && server_wait,
            "eglGetProcAddress KHR/native entry points");

    REQUIRE(eglBindAPI(EGL_OPENGL_ES_API), "eglBindAPI");
    const EGLint config_attributes[] = {
        EGL_SURFACE_TYPE, EGL_PBUFFER_BIT, EGL_RENDERABLE_TYPE, EGL_OPENGL_ES2_BIT,
        EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8, EGL_ALPHA_SIZE, 8, EGL_NONE
    };
    const EGLint pbuffer_attributes[] = {EGL_WIDTH, 16, EGL_HEIGHT, 16, EGL_NONE};
    const EGLint context_attributes[] = {EGL_CONTEXT_CLIENT_VERSION, 2, EGL_NONE};
    EGLConfig config;
    EGLint count = 0;
    REQUIRE(eglChooseConfig(display, config_attributes, &config, 1, &count) && count == 1,
            "eglChooseConfig");
    surface = eglCreatePbufferSurface(display, config, pbuffer_attributes);
    REQUIRE(surface != EGL_NO_SURFACE, "eglCreatePbufferSurface");
    context = eglCreateContext(display, config, EGL_NO_CONTEXT, context_attributes);
    REQUIRE(context != EGL_NO_CONTEXT, "eglCreateContext");
    REQUIRE(eglMakeCurrent(display, surface, surface, context), "eglMakeCurrent");
    printf("renderer=%s version=%s\n", glGetString(GL_RENDERER), glGetString(GL_VERSION));

    glDisable(GL_DITHER);
    glClearColor(1, 0, 1, 1);
    glClear(GL_COLOR_BUFFER_BIT);
    const EGLint no_attrs[] = {EGL_NONE};
    original = create_sync(display, EGL_SYNC_NATIVE_FENCE_ANDROID, no_attrs);
    REQUIRE(original != EGL_NO_SYNC_KHR, "eglCreateSyncKHR export fence");
    glFlush();
    exported = dup_fence(display, original);
    REQUIRE(exported >= 0, "eglDupNativeFenceFDANDROID");
    struct sync_file_info info = {0};
    REQUIRE(ioctl(exported, SYNC_IOC_FILE_INFO, &info) == 0, "SYNC_IOC_FILE_INFO on export");
    unsigned int fences = info.num_fences;

    import_fd = fcntl(exported, F_DUPFD_CLOEXEC, 0);
    REQUIRE(import_fd >= 0, "duplicate caller-owned export for import");
    int transferred_fd = import_fd;
    const EGLint import_attributes[] = {
        EGL_SYNC_NATIVE_FENCE_FD_ANDROID, transferred_fd, EGL_NONE
    };
    import_fd = -1; /* The import call takes ownership of this duplicate. */
    imported = create_sync(display, EGL_SYNC_NATIVE_FENCE_ANDROID, import_attributes);
    REQUIRE(imported != EGL_NO_SYNC_KHR, "eglCreateSyncKHR import fence");
    REQUIRE(server_wait(display, imported, 0), "eglWaitSyncKHR imported fence");
    REQUIRE(client_wait(display, imported, 0, 1000000000u) == EGL_CONDITION_SATISFIED_KHR,
            "eglClientWaitSyncKHR imported fence");
    struct pollfd pfd = {.fd = exported, .events = POLLIN};
    REQUIRE(poll(&pfd, 1, 1000) == 1 && (pfd.revents & POLLIN) &&
            !(pfd.revents & (POLLERR | POLLNVAL)), "poll caller-owned sync file");
    memset(&info, 0, sizeof(info));
    REQUIRE(ioctl(exported, SYNC_IOC_FILE_INFO, &info) == 0 && info.status == 1,
            "exported sync file signaled");

    GLubyte pixel[4] = {0};
    glReadPixels(8, 8, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, pixel);
    REQUIRE(glGetError() == GL_NO_ERROR && pixel[0] == 255 && pixel[1] == 0 &&
            pixel[2] == 255 && pixel[3] == 255, "known pixel after fence");
    REQUIRE(destroy_sync(display, imported), "eglDestroySyncKHR imported fence");
    imported = EGL_NO_SYNC_KHR;
    REQUIRE(destroy_sync(display, original), "eglDestroySyncKHR original fence");
    original = EGL_NO_SYNC_KHR;
    REQUIRE(fcntl(exported, F_GETFD) >= 0, "caller-owned export still open after EGL destroy");
    printf("KHR_FENCE result=pass sync_file=%s fences=%u signal=%d pixel=%u,%u,%u,%u\n",
           info.name, fences, info.status, pixel[0], pixel[1], pixel[2], pixel[3]);
    status = 0;

cleanup:
    if (destroy_sync && imported != EGL_NO_SYNC_KHR)
        destroy_sync(display, imported);
    if (destroy_sync && original != EGL_NO_SYNC_KHR)
        destroy_sync(display, original);
    if (exported >= 0)
        close(exported);
    if (import_fd >= 0)
        close(import_fd);
    if (initialized) {
        eglMakeCurrent(display, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
        if (context != EGL_NO_CONTEXT)
            eglDestroyContext(display, context);
        if (surface != EGL_NO_SURFACE)
            eglDestroySurface(display, surface);
        eglTerminate(display);
        eglReleaseThread();
    }
    alarm(0);
    if (status == 1)
        puts("KHR_FENCE result=fail");
    return status;
}
