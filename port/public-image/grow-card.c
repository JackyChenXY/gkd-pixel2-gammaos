/* SPDX-License-Identifier: Apache-2.0 */
#define _GNU_SOURCE
#define _FILE_OFFSET_BITS 64
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <linux/blkpg.h>
#include <linux/fs.h>
#include "grow-card.h"

enum { SECTOR = 512, HEADER = 92, ENTRY = 128, TABLE = 128*ENTRY, USER = 14*ENTRY };
static uint32_t u32(const unsigned char *s)
{
    return (uint32_t)s[0] | (uint32_t)s[1]<<8 | (uint32_t)s[2]<<16 | (uint32_t)s[3]<<24;
}
static uint64_t u64(const unsigned char *s) { return u32(s) | (uint64_t)u32(s+4)<<32; }
static void put32(unsigned char *s,uint32_t n) { for (int i=0;i<4;i++) s[i]=(unsigned char)(n>>(8*i)); }
static void put64(unsigned char *s,uint64_t n) { put32(s,n); put32(s+4,n>>32); }
static uint32_t crc(const unsigned char *s,size_t n)
{
    uint32_t v=UINT32_MAX;
    while (n--) {
        v^=*s++;
        for (int i=0;i<8;i++) v=(v>>1)^(0xedb88320U & -(v&1));
    }
    return ~v;
}
static int zero(const unsigned char *p,size_t n)
{
    for (size_t i=0;i<n;i++) if (p[i]) return 0;
    return 1;
}
static int transfer(int fd, uint64_t lba, unsigned char *buf, size_t n,int writing)
{
    off_t pos=(off_t)(lba*SECTOR);
    while (n) {
        ssize_t k=writing?pwrite(fd,buf,n,pos):pread(fd,buf,n,pos);
        if (k<0 && errno==EINTR) continue;
        if (k<=0) return -1;
        buf+=k; n-=(size_t)k; pos+=k;
    }
    return 0;
}
static void header(unsigned char *buf,const unsigned char *backup,uint64_t last,int primary,uint32_t table_crc)
{
    memcpy(buf,backup,SECTOR);
    put64(buf+24,primary?1:last); put64(buf+32,primary?last:1);
    put64(buf+48,last-33); put64(buf+72,primary?2:last-32);
    put32(buf+88,table_crc); put32(buf+16,0); put32(buf+16,crc(buf,HEADER));
}
static int equal_on_disk(int fd,uint64_t lba,const unsigned char *want,size_t len)
{
    unsigned char block[TABLE];
    return len<=sizeof(block) && transfer(fd,lba,block,len,0)==0 && !memcmp(block,want,len);
}

/* The immutable initramfs supplies the image size, disk GUID and checksum of
 * all 128 original entries. Only a newly flashed, blank userdata can grow.
 * Preserve the original backup until Android formats userdata. An interrupted
 * primary update can then be completed from that exact signed-off template. */
int pixel2_grow_fd(int fd,uint64_t bytes,uint64_t image_bytes,const unsigned char guid[16],uint32_t original_crc,
                   uint64_t *userdata_start)
{
    unsigned char backup[SECTOR], old_primary[SECTOR], new_primary[SECTOR], new_backup[SECTOR], mbr[SECTOR];
    unsigned char old[TABLE], resized[TABLE], primary[SECTOR], current[TABLE], blank[4096];
    if (image_bytes<(4ULL<<30) || bytes<=image_bytes || bytes>(2ULL<<40) || (bytes|image_bytes)%SECTOR) return 0;
    uint64_t old_last=image_bytes/SECTOR-1, last=bytes/SECTOR-1;
    if (last-old_last<64) return 0;
    if (transfer(fd,0,mbr,SECTOR,0) || transfer(fd,1,primary,SECTOR,0)) return 0;
    if (mbr[510]!=0x55 || mbr[511]!=0xaa || mbr[450]!=0xee || u32(mbr+454)!=1 || !zero(mbr+462,48)) return 0;
    if (memcmp(primary,"EFI PART",8) || memcmp(primary+56,guid,16)) return 0;
    if (transfer(fd,old_last,backup,SECTOR,0) || transfer(fd,old_last-32,old,TABLE,0)) return 0;
    if (memcmp(backup,"EFI PART",8) || u32(backup+8)!=0x10000 || u32(backup+12)!=HEADER ||
        u64(backup+24)!=old_last || u64(backup+32)!=1 || u64(backup+40)!=34 ||
        u64(backup+48)!=old_last-33 || memcmp(backup+56,guid,16) || u64(backup+72)!=old_last-32 ||
        u32(backup+80)!=128 || u32(backup+84)!=ENTRY || u32(backup+88)!=original_crc || crc(old,TABLE)!=original_crc) return 0;
    header(new_backup,backup,old_last,0,original_crc);
    if (memcmp(new_backup,backup,SECTOR)) return 0;
    static const unsigned char name[]={'u',0,'s',0,'e',0,'r',0,'d',0,'a',0,'t',0,'a',0,0,0};
    uint64_t first=u64(old+USER+32);
    if (memcmp(old+USER+56,name,sizeof(name)) || u64(old+USER+40)!=old_last-33 || first<34 ||
        first+2048>=old_last-33 || !zero(old+USER+ENTRY,TABLE-USER-ENTRY)) return 0;
    memcpy(resized,old,TABLE); put64(resized+USER+40,last-33);
    uint32_t updated_crc=crc(resized,TABLE);
    header(old_primary,backup,old_last,1,original_crc);
    header(new_primary,backup,last,1,updated_crc);
    header(new_backup,backup,last,0,updated_crc);
    if (memcmp(primary,old_primary,SECTOR) && memcmp(primary,new_primary,SECTOR)) return 0;
    if (transfer(fd,2,current,TABLE,0) || (memcmp(current,old,TABLE) && memcmp(current,resized,TABLE))) return 0;
    uint32_t protective=last>UINT32_MAX?UINT32_MAX:(uint32_t)last;
    if (!memcmp(primary,new_primary,SECTOR) && !memcmp(current,resized,TABLE) && u32(mbr+458)==protective &&
        equal_on_disk(fd,last,new_backup,SECTOR) && equal_on_disk(fd,last-32,resized,TABLE)) return 0;
    for (size_t i=0;i<(1U<<20)/sizeof(blank);i++) {
        if (transfer(fd,first+i*(sizeof(blank)/SECTOR),blank,sizeof(blank),0) || !zero(blank,sizeof(blank))) return 0;
    }
    put32(mbr+458,protective);
    if (transfer(fd,last-32,resized,TABLE,1) || transfer(fd,last,new_backup,SECTOR,1) || fsync(fd) ||
        transfer(fd,2,resized,TABLE,1) || transfer(fd,1,new_primary,SECTOR,1) || fsync(fd) ||
        transfer(fd,0,mbr,SECTOR,1) || fsync(fd)) return -1;
    if (!equal_on_disk(fd,0,mbr,SECTOR) || !equal_on_disk(fd,1,new_primary,SECTOR) ||
        !equal_on_disk(fd,2,resized,TABLE) || !equal_on_disk(fd,last,new_backup,SECTOR) ||
        !equal_on_disk(fd,last-32,resized,TABLE)) return -1;
    *userdata_start=first;
    return 1;
}

/* Called before Android mounts the card. Re-read only a verified removable SD.
 * Return 2 when a cold kernel partition rescan is needed. */
int pixel2_grow_sd(unsigned unit,uint64_t image_bytes,const unsigned char guid[16],uint32_t table_crc)
{
    char path[128],type[16];
    snprintf(path,sizeof(path),"/sys/class/block/mmcblk%u/device/type",unit);
    FILE *f=fopen(path,"r");
    if (!f) return 0;
    int sd=fgets(type,sizeof(type),f)!=NULL && !strcmp(type,"SD\n");
    fclose(f);
    if (!sd) return 0;
    snprintf(path,sizeof(path),"/dev/mmcblk%u",unit);
    int fd=open(path,O_RDWR|O_CLOEXEC|O_NOFOLLOW);
    if (fd<0) return 0;
    struct stat st;
    unsigned long long bytes=0;
    int sectorsize=0,result=0;
    uint64_t start=0;
    if (!fstat(fd,&st) && S_ISBLK(st.st_mode) && !ioctl(fd,BLKSSZGET,&sectorsize) && sectorsize==SECTOR &&
        !ioctl(fd,BLKGETSIZE64,&bytes)) result=pixel2_grow_fd(fd,bytes,image_bytes,guid,table_crc,&start);
    if (result==1 && ioctl(fd,BLKRRPART,0)<0) {
        struct blkpg_partition p={0};
        p.pno=15; p.start=(long long)(start*SECTOR); p.length=(long long)(bytes-(start+33)*SECTOR);
        struct blkpg_ioctl_arg arg={.op=BLKPG_RESIZE_PARTITION,.datalen=sizeof(p),.data=&p};
        if (ioctl(fd,BLKPG,&arg)<0) result=2;
    }
    close(fd);
    return result;
}
