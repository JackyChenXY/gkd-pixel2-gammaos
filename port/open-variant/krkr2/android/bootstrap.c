#define _GNU_SOURCE
#include <android/dlext.h>
#include <android/log.h>
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <inttypes.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

extern struct android_namespace_t *android_get_exported_namespace(const char *);
static const char *const soname = "libgallium_dri.so";
static const char *const logtag = "Pixel2KrkrGL";
static const char *const gpuoptions[][2] = {
    {"PAN_MESA_DEBUG","forcepack,nocache"}, {"PIXEL2_RESOURCE_TRACE","large"},
    {"PIXEL2_SHADOW_MODE","observe"}, {"PIXEL2_DEFER_AFBC","survival"},
};
static bool reject(const char *what, const char *why) {
    __android_log_print(ANDROID_LOG_WARN,logtag,"%s: %s",what,why?why:"unknown");
#ifdef PIXEL2_HOST_PROBE
    fprintf(stderr,"%s: %s\n",what,why?why:"unknown");
#endif
    return false;
}
static int immutable_file(const char *path) {
    int fd=open(path,O_NOFOLLOW|O_RDONLY|O_CLOEXEC);
    if(fd<0) return -1;
    struct stat s;
    if(fstat(fd,&s)!=0 || !S_ISREG(s.st_mode) || s.st_uid!=0 ||
       (s.st_mode & 0022) || s.st_size!=10807252) {
        close(fd);errno=EINVAL;return -1;
    }
    return fd;
}
static void *pending_handle;
static bool install(const char *path) {
    if(pending_handle) return true;
    android_dlextinfo ns={.flags=ANDROID_DLEXT_USE_NAMESPACE,
        .library_namespace=android_get_exported_namespace("sphal")};
    if(!ns.library_namespace) return reject("sphal","unavailable");
    void *existing=android_dlopen_ext(soname,RTLD_NOW|RTLD_NOLOAD,&ns);
    if(existing) {dlclose(existing);return reject("already initialized","stock driver retained");}
    int src=immutable_file(path);
    if(src<0) return reject("system driver input",strerror(errno));
    for(size_t i=0;i<sizeof(gpuoptions)/sizeof(*gpuoptions);++i) {
        if(getenv(gpuoptions[i][0])) {close(src);return reject("environment conflict",gpuoptions[i][0]);}
    }
    size_t set=0;
    for(;set<sizeof(gpuoptions)/sizeof(*gpuoptions);++set)
        if(setenv(gpuoptions[set][0],gpuoptions[set][1],0)!=0) break;
    void *h=NULL, *check=NULL;
    if(set==sizeof(gpuoptions)/sizeof(*gpuoptions)){
        // Open through an allowed ODM path and verify the loader mapped the immutable inode we inspected.
        struct stat before;
        if(fstat(src,&before)==0) h=android_dlopen_ext(path,RTLD_NOW|RTLD_LOCAL,&ns);
        if(!h) reject("driver load",dlerror());
        if(h) {
            check=android_dlopen_ext(soname,RTLD_NOLOAD|RTLD_NOW,&ns);
            Dl_info info; struct stat current;
            void *screen=dlsym(h,"driCreateNewScreen3");
            if(check==h && screen && dlsym(h,"driGetAPIMask") && dladdr(screen,&info) &&
               info.dli_fname && strcmp(info.dli_fname,path)==0 && stat(info.dli_fname,&current)==0 &&
               current.st_ino==before.st_ino && current.st_dev==before.st_dev) pending_handle=h;
            else reject("driver identity","same-namespace Mesa SONAME or exports missing");
        }
    }
    if(check) dlclose(check);
    close(src);
    if(!pending_handle) {
        if(h) dlclose(h);
        while(set>0) unsetenv(gpuoptions[--set][0]);
        return false;
    }
    __android_log_print(ANDROID_LOG_INFO,logtag,"V7 ready in sphal pid=%d read-only ODM file",getpid());
    return true;
}
#ifndef PIXEL2_HOST_PROBE
static bool decimal(const char *text) {
    size_t n=0;
    while(*text>='0' && *text<='9' && n<9) {++text;++n;}
    return n>0 && n<=8 && !*text;
}
static bool expected_argv(void) {
    static const char *fixed[]={"/system/bin/app_process32","-Xcompiler-option","--generate-mini-debug-info",
        "/system/bin","--application","--nice-name=org.github.krkr2","com.android.internal.os.WrapperInit",
        NULL,NULL,"-cp","/system/etc/pixel2-krkr/official-software-decor.jar","pixel2.platformtest.OfficialSoftwareDecor"};
    int fd=open("/proc/self/cmdline",O_RDONLY|O_CLOEXEC);
    if(fd<0) return false;
    char buffer[4096];ssize_t n=TEMP_FAILURE_RETRY(read(fd,buffer,sizeof(buffer)));close(fd);
    if(n<=0)return false;
    size_t at=0;
    for(size_t i=0;i<sizeof(fixed)/sizeof(*fixed);i++) {
        if(at>=(size_t)n)return false;
        const char *arg=buffer+at,*nul=memchr(arg,0,(size_t)n-at);
        if(!nul || (fixed[i]?strcmp(arg,fixed[i])!=0:!decimal(arg)))return false;
        at=(size_t)(nul-buffer)+1;
    }
    return true;
}
static bool same_apk(const char *spec) {
    if(!spec || strncmp(spec,"/data/app/",10) || strlen(spec)>=PATH_MAX+96)return false;
    const char *sep=strchr(spec,'|');
    if(!sep || sep-spec<18 || sep-spec>=PATH_MAX || memcmp(sep-9,"/base.apk",9))return false;
    char path[PATH_MAX];size_t n=(size_t)(sep-spec);memcpy(path,spec,n);path[n]=0;
    if(strstr(path,"/../") || strstr(path,"/./") || !strstr(path,"/org.github.krkr2-"))return false;
    struct stat st;
    if(lstat(path,&st) || !S_ISREG(st.st_mode) || (st.st_mode & 0002) || st.st_uid==getuid())return false;
    char actual[128];
    snprintf(actual,sizeof(actual),"%" PRIu64 ":%" PRIu64 ":%" PRIu64 ":%" PRIu64,
        (uint64_t)st.st_dev,(uint64_t)st.st_ino,(uint64_t)st.st_size,(uint64_t)st.st_mtime);
    return strcmp(sep+1,actual)==0;
}
__attribute__((constructor)) static void verified_start(void) {
    const char *ld=getenv("LD_PRELOAD");
    if(!ld || strcmp(ld,"/system/lib/libpixel2_krkr_bootstrap.so"))return;
    char pid[32];snprintf(pid,sizeof(pid),"%d",getpid());
    const char *marker=getenv("PIXEL2_KRKR_VERIFIED_PID");
    bool target=getuid()==10117 && marker && !strcmp(marker,pid) && expected_argv() &&
        same_apk(getenv("PIXEL2_KRKR_VERIFIED_SOURCE"));
    unsetenv("LD_PRELOAD");unsetenv("PIXEL2_KRKR_VERIFIED_PID");unsetenv("PIXEL2_KRKR_VERIFIED_SOURCE");
    unsetenv("PIXEL2_KRKR_BRIDGE_READY");
    if(target && install("/odm/lib/libpixel2_krkr_v7.so")){
        setenv("PIXEL2_KRKR_BRIDGE_READY",pid,1);
    } else if(!target) {
        reject("platform handoff","scope, PID, or installed APK metadata mismatch");
    }
}
#endif
#ifdef PIXEL2_HOST_PROBE
int main(int argc, char **argv) {
    if(argc>1 && !strcmp(argv[1],"--stock-already-loaded")) {
        android_dlextinfo stockns={.flags=ANDROID_DLEXT_USE_NAMESPACE,.library_namespace=android_get_exported_namespace("sphal")};
        if(!stockns.library_namespace || !android_dlopen_ext("/vendor/lib/libgallium_dri.so",RTLD_NOW,&stockns)) return 7;
        if(install("/odm/lib/libpixel2_krkr_v7.so") || getenv("PIXEL2_DEFER_AFBC")) return 8;
        puts("Existing stock driver preserved");return 0;
    }
    if(argc>1 && !strcmp(argv[1],"--missing-file")) {
        if(install("/odm/lib/absent-pixel2-test.so") || getenv("PIXEL2_DEFER_AFBC")) return 9;
        puts("Unavailable candidate preserves original environment");return 0;
    }
    if(!install("/odm/lib/libpixel2_krkr_v7.so")) return 2;
    android_dlextinfo ns={.flags=ANDROID_DLEXT_USE_NAMESPACE,.library_namespace=android_get_exported_namespace("sphal")};
    void *egl=android_dlopen_ext("/vendor/lib/egl/libEGL_mesa.so",RTLD_NOW,&ns);
    if(!egl) {reject("EGL",dlerror());return 3;}
    void *driver=dlsym(pending_handle,"driCreateNewScreen3"),*consumer=dlsym(egl,"driCreateNewScreen3");
    printf("MESA EGL resolves driver export %p, injected V7 %p\n",consumer,driver);
    if(!driver || driver!=consumer) return 4;
    FILE *f=fopen("/proc/self/maps","r");char line[768];bool odm=false,stock=false;
    if(!f) return 5;
    while(fgets(line,sizeof(line),f)) {
        if(strstr(line,"/odm/lib/libpixel2_krkr_v7.so")) odm=true;
        if(strstr(line,"/vendor/lib/libgallium_dri.so")) stock=true;
    }
    fclose(f);printf("file-backed ODM V7=%d original mapped=%d\n",odm,stock);
    return odm && !stock?0:6;
}
#endif
