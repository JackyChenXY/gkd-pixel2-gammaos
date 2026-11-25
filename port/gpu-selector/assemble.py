#!/usr/bin/env python3
"""Build the public switchable-driver card from the verified factory layout."""
import argparse,gzip,hashlib,json,os,re,shutil,struct,subprocess,tempfile,uuid
from pathlib import Path
SECTOR=512
def digest(f,off,n):
    h=hashlib.sha256();f.seek(off)
    while n:
        b=f.read(min(n,2<<20))
        if not b:raise EOFError
        h.update(b);n-=len(b)
    return h.hexdigest()
def sha(path):
    with path.open("rb") as f:return digest(f,0,path.stat().st_size)
def parts(f):
    f.seek(512);h=f.read(512);guid=uuid.UUID(bytes_le=h[56:72])
    if h[:8]!=b"EFI PART" or str(guid)!="10e4d830-2e2a-409a-b641-c9ccd806744c":raise ValueError("Unexpected public GPT")
    f.seek(1024);a=f.read(16384);result={}
    for i in range(128):
        v=a[128*i:128*i+128];n=v[56:].decode("utf-16le").strip("\0")
        if n:
            start,end=struct.unpack_from("<QQ",v,32)
            result[n]=(start*512,(end-start+1)*512)
    return result
def extent(f,super_offset,slot,name):
    f.seek(super_offset+4096+40);step=struct.unpack("<I",f.read(4))[0]
    if step!=65536:raise ValueError("Unexpected LP metadata capacity")
    f.seek(super_offset+12288+slot*step);data=f.read(step)
    magic,major,minor,head=struct.unpack_from("<IHHI",data)
    if magic!=0x414c5030 or major!=10:raise ValueError("Unexpected LP header")
    po,pc,ps,eo,ec,es=struct.unpack_from("<IIIIII",data,80)
    for j in range(pc):
        pos=head+po+j*ps
        if data[pos:pos+36].split(b"\0",1)[0]!=name.encode():continue
        index,count=struct.unpack_from("<II",data,pos+40)
        n,typ,start,dev=struct.unpack_from("<QIQI",data,head+eo+es*index)
        if count!=1 or typ!=0 or dev!=0:raise ValueError("Non-contiguous logical partition")
        return super_offset+start*512,n*512
    raise ValueError("Missing "+name)
def mali_ramdisk(src):
    archive=gzip.decompress(src.read_bytes());pos=0;changes=0;out=bytearray()
    while archive[pos:pos+6]==b"070701":
        fields=[int(archive[i:i+8],16) for i in range(pos+6,pos+110,8)]
        end_name=pos+110+fields[11];start=(end_name+3)&~3;end=start+fields[6];nxt=(end+3)&~3
        if archive[pos+110:end_name].rstrip(b"\0")==b"fstab.rk30board":
            data,count=re.subn(rb"(?m)^vendor[ \t]+/vendor[ \t]+ext4[ \t]+ro,barrier=1[ \t]+wait,logical,first_stage_mount$",b"/dev/block/by-name/backup /vendor ext4 ro,barrier=1 wait,first_stage_mount",archive[start:end])
            if count!=1:raise ValueError("Unexpected vendor mount")
            header=bytearray(archive[pos:start]);header[54:62]=f"{len(data):08x}".encode();out+=header+data+b"\0"*(-len(data)%4);changes+=1
        else:out+=archive[pos:nxt]
        pos=nxt
    if changes!=1 or any(archive[pos:]):raise ValueError("Unexpected ramdisk")
    return gzip.compress(out+b"\0"*(-len(out)%512),mtime=0)
def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("base","system","empty","kernel","output"):p.add_argument("--"+name,required=True,type=Path)
    a=p.parse_args();here=Path(__file__).resolve().parent
    if a.output.exists() or a.output.is_symlink() or not all(f.is_file() for f in (a.base,a.system,a.empty,a.kernel)):p.error("Use regular inputs and a new output file")
    if sha(a.base)!="08e3fbfb7189fe8b8a139a6f9dbf85fee0a2e81743694254e8bac0fe25f52f55" or sha(a.kernel)!="f3c58e958e57bd4deabb7ee355528679557c88e27f21cfdb641cadef9f91b500":raise ValueError("Wrong base image or matching open-source kbase kernel")
    desc=json.loads((here/"backend/profile/profile.json").read_text())
    if sha(a.empty)!=desc["empty_hash"] or a.empty.stat().st_size!=128<<20:raise ValueError("Wrong public GPU template")
    with tempfile.TemporaryDirectory(dir=a.output.parent) as directory:
        t=Path(directory);disk=t/"card.raw"
        subprocess.run(["cp","--reflink=auto","--sparse=always","--",a.base,disk],check=True)
        with disk.open("r+b") as f:
            pt=parts(f);start,capacity=pt["backup"]
            if (start,capacity)!=(641024*512,761856*512):raise ValueError("Wrong GPU slot")
            misc,misc_size=pt["misc"]
            if (misc,misc_size)!=(319488*512,8192*512):raise ValueError("Wrong misc partition")
            control=misc+8192
            f.seek(control)
            if f.read(512)!=bytes(512):raise ValueError("Vendor boot-control sector already in use")
            loc,size=extent(f,pt["super"][0],0,"system")
            if extent(f,pt["super"][0],1,"system")!=(loc,size) or a.system.stat().st_size!=size:raise ValueError("Unexpected system extent")
            if digest(f,loc,size)!="aaf1f661ed14d10930bb1d04cbd36476ac2992006a681bbb529775a27448b108":raise ValueError("Wrong original system")
            for off,src in ((loc,a.system),(start,a.empty)):
                f.seek(off)
                with src.open("rb") as inp:shutil.copyfileobj(inp,f,length=2<<20)
                f.flush()
                if digest(f,off,src.stat().st_size)!=sha(src):raise OSError("Partition readback failed")
            record=struct.pack("<4sIII",b"P2G2",0x30201,0x20,0xffffffdf).ljust(512,b"\0");f.seek(control);f.write(record);f.flush();os.fsync(f.fileno())
        fat=str(disk)+"@@"+str(pt["bootfiles"][0])
        def extract(name,dest):subprocess.run(["mcopy","-i",fat,"::/"+name,dest],check=True)
        for n in ("Image","pixel2.dtb","initramfs.cpio.gz"):extract(n,t/n)
        subprocess.run(["mkimage","-A","arm64","-O","linux","-T","script","-C","none","-n","Pixel 2 system GPU profiles","-d",here/"boot.cmd",t/"boot.scr"],check=True,stdout=subprocess.DEVNULL)
        (t/"mali.gz").write_bytes(mali_ramdisk(t/"initramfs.cpio.gz"))
        for name,src in (("boot.scr",t/"boot.scr"),("mali.img",a.kernel),("mali.gz",t/"mali.gz")):
            subprocess.run(["mcopy","-o","-i",fat,src,"::/"+name],check=True)
            check=t/("check-"+name);extract(name,check)
            if sha(check)!=sha(src):raise OSError("FAT readback failed")
        for n in ("Image","pixel2.dtb","initramfs.cpio.gz"):
            dst=t/("check-"+n);extract(n,dst)
            if sha(dst)!=sha(t/n):raise OSError("Mesa boot files changed")
        with disk.open("rb") as f:
            f.seek(control)
            if f.read(512)!=record:raise ValueError("Default selection changed")
            f.seek(pt["userdata"][0])
            if any(f.read(1<<20)):raise ValueError("Unexpected userdata filesystem")
            # rc.1 ships a formatted, empty metadata ext4. Verify every byte, including its superblock.
            with a.base.open("rb") as factory:
                for off,size in ((misc,8192),(control+512,misc+misc_size-control-512)):
                    if digest(f,off,size)!=digest(factory,off,size):raise ValueError("Other misc boot fields changed")
                for n in ("metadata","userdata"):
                    off,size=pt[n]
                    if digest(f,off,size)!=digest(factory,off,size):raise ValueError("Factory partition changed: "+n)
        subprocess.run(["sgdisk","-v",disk],check=True)
        os.link(disk,a.output);print("raw",a.output.stat().st_size,sha(disk),flush=True)
if __name__=="__main__":main()
