/* SPDX-License-Identifier: MIT */
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES3/gl3.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
enum { W=1024,H=1024 };
static const uint8_t colors[3][4]={{17,93,201,41},{252,39,117,129},{83,199,5,227}};
static GLuint shader(GLenum tag,const char *str){
    GLuint sh=glCreateShader(tag);glShaderSource(sh,1,&str,NULL);glCompileShader(sh);
    GLint ok=0;glGetShaderiv(sh,GL_COMPILE_STATUS,&ok);
    if(!ok){char m[1024]={0};glGetShaderInfoLog(sh,sizeof m,NULL,m);fprintf(stderr,"%s\n",m);exit(2);}
    return sh;
}
static void pattern(unsigned x,unsigned y,unsigned seed,uint8_t *v){
    if (seed || (x<305 && y<773)) {
        v[0]=(x*23+y*17+seed*7)&255;
        v[1]=((x*11)^(y*13)^seed)&255;
        v[2]=(x*3+y*31+3*seed)&255;
        v[3]=((x*7)^(y*19)^(seed*11))&255;
    } else memcpy(v,colors[(x/128+y/256)%3],4);
}
static void copy_to(GLuint out,GLuint src){
    glBindFramebuffer(GL_FRAMEBUFFER,out);glBindTexture(GL_TEXTURE_2D,src);
    glViewport(0,0,W,H);glDrawArrays(GL_TRIANGLES,0,3);
}
static int check(GLuint out,uint8_t *pixels,int modified,unsigned source){
    glBindFramebuffer(GL_FRAMEBUFFER,out);glReadPixels(0,0,W,H,GL_RGBA,GL_UNSIGNED_BYTE,pixels);
    GLenum err=glGetError();unsigned bad=0;
    for(unsigned y=0;y<H;y++)for(unsigned x=0;x<W;x++){
        uint8_t expected[4];
        pattern(x,y,0,expected);
        if (x<305 && y<773) expected[0]^=(uint8_t)(source*37);
        else memcpy(expected,colors[(x/128+y/256+source)%3],4);
        if(modified==1 && x>=157 && x<157+320 && y>=103 && y<103+256)
            pattern((x-157)/5,(y-103)/4,7,expected);
        if(modified==2 && x>=157 && x<157+64 && y>=103 && y<103+64)
            pattern(x-157,y-103,7,expected);
        uint8_t *v=pixels+4u*(y*W+x);
        if(memcmp(expected,v,4)){if(!bad)fprintf(stderr,"first mismatch %u,%u got %u %u %u %u expected %u %u %u %u\n",x,y,v[0],v[1],v[2],v[3],expected[0],expected[1],expected[2],expected[3]);bad++;}
    }
    printf("%s RGBA8 pixels=%u mismatches=%u error=0x%x\n",modified?"after_partial_gpu_rewrite":"sampled_before_rewrite",W*H,bad,err);
    return bad || err!=GL_NO_ERROR;
}
int main(int argc,char **argv){
    int mode=(argc>1 && !strcmp(argv[1],"copy"))?2:1;
    EGLDisplay d=eglGetDisplay(EGL_DEFAULT_DISPLAY); EGLConfig cfg; EGLint n=0;
    const EGLint ca[]={EGL_SURFACE_TYPE,EGL_PBUFFER_BIT,EGL_RENDERABLE_TYPE,EGL_OPENGL_ES3_BIT_KHR,EGL_RED_SIZE,8,EGL_GREEN_SIZE,8,EGL_BLUE_SIZE,8,EGL_ALPHA_SIZE,8,EGL_NONE};
    const EGLint sa[]={EGL_WIDTH,2,EGL_HEIGHT,2,EGL_NONE},xa[]={EGL_CONTEXT_CLIENT_VERSION,3,EGL_NONE};
    if(!eglInitialize(d,NULL,NULL)||!eglBindAPI(EGL_OPENGL_ES_API)||!eglChooseConfig(d,ca,&cfg,1,&n)||n!=1)return 2;
    EGLSurface surface=eglCreatePbufferSurface(d,cfg,sa);EGLContext ctx=eglCreateContext(d,cfg,EGL_NO_CONTEXT,xa);
    if(!eglMakeCurrent(d,surface,surface,ctx))return 2;
    printf("renderer=%s version=%s\n",glGetString(GL_RENDERER),glGetString(GL_VERSION));
    const char *vs="#version 300 es\nvoid main(){vec2 a=vec2((gl_VertexID<<1)&2,gl_VertexID&2);gl_Position=vec4(a*2.-1.,0,1);}";
    const char *fs="#version 300 es\nprecision highp float; uniform highp sampler2D t; out vec4 c; void main(){c=texelFetch(t,ivec2(gl_FragCoord.xy),0);}";
    GLuint v=shader(GL_VERTEX_SHADER,vs),f=shader(GL_FRAGMENT_SHADER,fs),p=glCreateProgram();
    glAttachShader(p,v);glAttachShader(p,f);glLinkProgram(p);GLint linked=0;glGetProgramiv(p,GL_LINK_STATUS,&linked);if(!linked)return 2;
    glUseProgram(p);glUniform1i(glGetUniformLocation(p,"t"),0);glDisable(GL_DITHER);glDisable(GL_BLEND);
    GLuint tex[4],fb[4];glGenTextures(4,tex);glGenFramebuffers(4,fb);
    for(int i=0;i<4;i++){glBindTexture(GL_TEXTURE_2D,tex[i]);glTexStorage2D(GL_TEXTURE_2D,1,GL_RGBA8,W,H);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
        glBindFramebuffer(GL_FRAMEBUFFER,fb[i]);glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,tex[i],0);
        if(glCheckFramebufferStatus(GL_FRAMEBUFFER)!=GL_FRAMEBUFFER_COMPLETE)return 2;}
    glViewport(0,0,W,H);glBindFramebuffer(GL_FRAMEBUFFER,fb[0]);
    const char *patternfs="#version 300 es\nprecision highp float; precision highp int; uniform int source; out vec4 c; void main(){ivec2 p=ivec2(gl_FragCoord.xy);int x=p.x,y=p.y; if(x<305 && y<773)c=vec4(ivec4((x*23+y*17)^(source*37),(x*11)^(y*13),x*3+y*31,(x*7)^(y*19))&255)/255.;else {int k=(x/128+y/256+source)%3;c=(k==0?vec4(17,93,201,41):k==1?vec4(252,39,117,129):vec4(83,199,5,227))/255.;}}";
    GLuint pf=shader(GL_FRAGMENT_SHADER,patternfs), program=glCreateProgram();
    glAttachShader(program,v);glAttachShader(program,pf);glLinkProgram(program);
    glGetProgramiv(program,GL_LINK_STATUS,&linked);if(!linked)return 2;
    glUseProgram(program);
    GLint color=glGetUniformLocation(program,"source");
    if (color<0) return 2;
    for (int i=0;i<3;i++) {
        glBindFramebuffer(GL_FRAMEBUFFER,fb[i]);
        glUniform1i(color,i);
        glDrawArrays(GL_TRIANGLES,0,3);
    }
    glUseProgram(p);
    glDeleteProgram(program);glDeleteShader(pf);
    /* The large source must no longer be bound when glFinish reaches the
     * driver. A separate 1x1 sample and FBO keep the output reference intact. */
    GLuint dummy[2], scratch;
    glGenTextures(2,dummy);glGenFramebuffers(1,&scratch);
    for(int i=0;i<2;i++){
        glBindTexture(GL_TEXTURE_2D,dummy[i]);glTexStorage2D(GL_TEXTURE_2D,1,GL_RGBA8,1,1);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
    }
    glBindFramebuffer(GL_FRAMEBUFFER,scratch);
    glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,dummy[1],0);
    if(glCheckFramebufferStatus(GL_FRAMEBUFFER)!=GL_FRAMEBUFFER_COMPLETE)return 2;
    /* The sources have been drawn but never sampled. Bind a small target
     * and request a new large texture. Only the allocation boundary should
     * recover the three inactive targets in this test. */
    copy_to(scratch,dummy[0]);
    usleep(300000);
    GLuint request;
    glGenTextures(1, &request);
    glBindTexture(GL_TEXTURE_2D,request);
    glTexStorage2D(GL_TEXTURE_2D,1,GL_RGBA8,1024,2048);
    glDeleteTextures(1,&request);
    puts("alloc_before_first_sample_complete");
    glDeleteFramebuffers(1,&scratch);glDeleteTextures(2,dummy);
    uint8_t *pixels=malloc(W*H*4u);if(!pixels)return 2;
    int bad=0;
    for(int i=0;i<3;i++) {
        printf("source=%d ",i);
        copy_to(fb[3],tex[i]);
        glFinish();
        bad|=check(fb[3],pixels,0,i);
    }
    GLuint small,smallfb;glGenTextures(1,&small);glBindTexture(GL_TEXTURE_2D,small);
    uint8_t tile[64*64*4];
    for(unsigned y=0;y<64;y++)for(unsigned x=0;x<64;x++)pattern(x,y,7,&tile[(y*64+x)*4]);
    glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA8,64,64,0,GL_RGBA,GL_UNSIGNED_BYTE,tile);
    glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
    glGenFramebuffers(1,&smallfb);glBindFramebuffer(GL_READ_FRAMEBUFFER,smallfb);
    glFramebufferTexture2D(GL_READ_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,small,0);
    if(glCheckFramebufferStatus(GL_READ_FRAMEBUFFER)!=GL_FRAMEBUFFER_COMPLETE)return 2;
    for(int i=0;i<3;i++){
        glBindFramebuffer(GL_READ_FRAMEBUFFER,smallfb);
        if(mode==1) {
            glBindFramebuffer(GL_DRAW_FRAMEBUFFER,fb[i]);
            glBlitFramebuffer(0,0,64,64,157,103,157+320,103+256,GL_COLOR_BUFFER_BIT,GL_NEAREST);
        } else {
            glBindTexture(GL_TEXTURE_2D,tex[i]);
            glCopyTexSubImage2D(GL_TEXTURE_2D,0,157,103,0,0,64,64);
        }
        printf("source=%d rewrite=%s ",i,mode==1?"scaled_framebuffer_blit":"copy_tex_subimage");
        copy_to(fb[3],tex[i]);glFinish();bad|=check(fb[3],pixels,mode,i);
    }
    glDeleteFramebuffers(1,&smallfb);glDeleteTextures(1,&small);
    free(pixels);glDeleteFramebuffers(4,fb);glDeleteTextures(4,tex);glDeleteProgram(p);glDeleteShader(v);glDeleteShader(f);
    eglMakeCurrent(d,EGL_NO_SURFACE,EGL_NO_SURFACE,EGL_NO_CONTEXT);eglDestroyContext(d,ctx);eglDestroySurface(d,surface);eglTerminate(d);
    return bad;
}
