/* SPDX-License-Identifier: Apache-2.0
 * Test-only ARM executable for the instrumented virtual card; never included in firmware. */
#define _GNU_SOURCE
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <errno.h>
#include <fcntl.h>
#include <grp.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static int logfd;
static const char *step;
static void fail(const char *msg){dprintf(logfd,"<3>P2_GPUTEST FAIL %s %s errno=%d\n",step,msg,errno);exit(2);}
static int connect_gpu(void){
    struct sockaddr_un addr={.sun_family=AF_UNIX};
    strcpy(addr.sun_path,"/dev/socket/pixel2_gpu");
    int fd=socket(AF_UNIX,SOCK_STREAM|SOCK_CLOEXEC,0);
    if(fd>=0 && connect(fd,(struct sockaddr*)&addr,sizeof(addr))<0){close(fd);return -1;}
    return fd;
}
static int query(char op,const char *file,int expect,int state,const char *active){
    int s=-1;for(int i=0;i<100 && s<0;i++){s=connect_gpu();if(s<0)usleep(100000);}if(s<0)fail("connect");
    struct iovec v={.iov_base=&op,.iov_len=1};struct msghdr msg={.msg_iov=&v,.msg_iovlen=1};
    int input=-1;union { struct cmsghdr align; unsigned char data[CMSG_SPACE(sizeof(int))]; } control;
    if(file){
        input=open(file,O_RDONLY|O_CLOEXEC);if(input<0)fail("input");
        memset(&control,0,sizeof(control));msg.msg_control=control.data;msg.msg_controllen=sizeof(control.data);
        struct cmsghdr *c=CMSG_FIRSTHDR(&msg);c->cmsg_level=SOL_SOCKET;c->cmsg_type=SCM_RIGHTS;c->cmsg_len=CMSG_LEN(sizeof(int));
        memcpy(CMSG_DATA(c),&input,sizeof(input));
    }
    if(sendmsg(s,&msg,MSG_NOSIGNAL)!=1)fail("send");
    if(input>=0)close(input);
    char reply[512]={0};size_t have=0;ssize_t n;
    while(have<sizeof(reply)-1 && (n=read(s,reply+have,sizeof(reply)-1-have))>0){have+=(size_t)n;if(strchr(reply,'\n'))break;}
    close(s);
    dprintf(logfd,"<5>P2_GPUTEST %s %c %s",step,op,reply);
    if(!strstr(reply,expect?"\"ok\":true":"\"ok\":false"))fail("unexpected response");
    char *p=strstr(reply,"\"state\":");if(expect && (!p||atoi(p+8)!=state))fail("unexpected state");
    if(active && !strstr(reply,active))fail("unexpected active profile");
    return 0;
}
static void marker(const char *wanted,const char *next){
    char value[64]={0};const char *path="/data/.gpu-selector-fixture";
    if(wanted){int fd=open(path,O_RDONLY);if(fd<0||read(fd,value,sizeof(value)-1)<0||strcmp(value,wanted))fail("userdata continuity");close(fd);}
    if(next){int fd=open(path,O_WRONLY|O_CREAT|O_TRUNC|O_CLOEXEC,0600);if(fd<0||write(fd,next,strlen(next))!=(ssize_t)strlen(next)||fsync(fd))fail("userdata write");close(fd);}
}
int main(void){
    char cmd[4096]={0};FILE *f=fopen("/proc/cmdline","r");if(!f||!fgets(cmd,sizeof(cmd),f))return 3;fclose(f);
    char *v=strstr(cmd,"androidboot.pixel2test=");if(!v)return 3;v+=strlen("androidboot.pixel2test=");v[strcspn(v," \r\n")]=0;step=v;
    logfd=open("/dev/kmsg",O_WRONLY|O_CLOEXEC);if(logfd<0)return 3;
    dprintf(logfd,"<5>P2_GPUTEST BEGIN %s\n",step);
    /* class_start core follows post-fs-data on this Android version. */
    for(int i=0; i<600 && access("/dev/socket/pixel2_gpu",F_OK)!=0; ++i) usleep(200000);
    if(access("/dev/socket/pixel2_gpu",F_OK)!=0)fail("service socket creation");
    if (!strcmp(step,"preloaded") || !strcmp(step,"unconfirmed")) {
        struct stat apk, wall;
        const char *home = "/oem/app/AT4K/AT4K.apk";
        const char *background = "/oem/app/AT4K/H700-wallpaper.jpg";
        if (stat(home, &apk) || apk.st_size != 12272145 ||
                stat(background, &wall) || wall.st_size != 1324045 ||
                access("/oem/etc/preferred-apps/at4k-home.xml", R_OK))
            fail("OEM desktop mount and default HOME");
        dprintf(logfd,"<5>P2_DESKTOP %s mounted APK, wallpaper and HOME preference before framework startup\n",step);
    }
    if(!strcmp(step,"seed") || !strcmp(step,"preloaded"))marker(NULL,"from-mesa");
    else if(!strcmp(step,"unconfirmed"))marker("from-mesa","from-mali");
    else marker("from-mali",NULL);
    if(!strcmp(step,"persistent")){
        pid_t pid=fork();if(pid==0){execl("/system/bin/pixel2-gpu","pixel2-gpu","complete",(char*)NULL);_exit(3);}
        int status;if(waitpid(pid,&status,0)<0||!WIFEXITED(status)||WEXITSTATUS(status))fail("boot completion callback");
    }
    if(!strcmp(step,"seed")){
        pid_t pid=fork();if(pid==0){if(setgid(1000)||setuid(2000))_exit(2);int s=connect_gpu();char a[12];if(s<0)_exit(0);send(s,"S",1,MSG_NOSIGNAL);_exit(read(s,a,sizeof(a))<=0?0:1);}
        int code;if(waitpid(pid,&code,0)<0||!WIFEXITED(code)||WEXITSTATUS(code))fail("non-system access");
    }
    if(setgroups(0,NULL)||setgid(1000)||setuid(1000))fail("assume system UI identity");
    if(!strcmp(step,"seed")){
        query('S',NULL,1,32,"\"mesa\"");query('I',"/mnt/p2gpu/bad",0,-1,NULL);query('S',NULL,1,32,"\"mesa\"");
        query('I',"/mnt/p2gpu/driver.zip",1,33,"\"mesa\"");query('T',NULL,1,34,"\"mesa\"");
    }else if(!strcmp(step,"preloaded")){
        query('S',NULL,1,33,"\"mesa\"");query('T',NULL,1,34,"\"mesa\"");
    }else if(!strcmp(step,"unconfirmed")){
        query('S',NULL,1,36,"\"trial\"");
    }else if(!strcmp(step,"fallback")){
        query('S',NULL,1,36,"\"mesa\"");query('T',NULL,1,34,"\"mesa\"");
    }else if(!strcmp(step,"confirm")){
        query('S',NULL,1,36,"\"trial\"");query('K',NULL,1,35,"\"trial\"");
    }else if(!strcmp(step,"persistent")){
        query('S',NULL,1,35,"\"kept\"");query('M',NULL,1,33,"\"kept\"");
    }else if(!strcmp(step,"return")){
        query('S',NULL,1,33,"\"mesa\"");
    }else fail("unknown test");
    sync();dprintf(logfd,"<5>P2_GPUTEST PASS %s\n",step);return 0;
}
