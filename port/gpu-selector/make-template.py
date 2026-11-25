#!/usr/bin/env python3
"""Build the public, zero-filled vendor slot and its verified import layout."""
import argparse, contextlib, fcntl, hashlib, json, os, re, shutil, struct, subprocess, tempfile
from pathlib import Path

def run(*args):
    return subprocess.run(args, check=True, stdout=subprocess.DEVNULL)
def digest(path):
    with path.open("rb") as f: return hashlib.file_digest(f, "sha256").hexdigest() if hasattr(hashlib,"file_digest") else stream_hash(f)
def stream_hash(f):
    h=hashlib.sha256()
    for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
    return h.hexdigest()
def regions(p):
    buf=bytearray(32+56*256)
    struct.pack_into("<QQIIII",buf,0,0,2**64-1,1,0,256,0)
    with p.open("rb") as f: fcntl.ioctl(f,0xc020660b,buf,True)
    count=struct.unpack_from("<I",buf,20)[0]
    if not 0<count<256: raise ValueError("Unexpected extent count")
    result=[]; cursor=0
    for i in range(count):
        offset,physical,length,_,_,flags=struct.unpack_from("<QQQQQI",buf,32+56*i)
        if offset!=cursor or flags & ~1: raise ValueError("Nonlinear or shared extent "+str(p))
        used=min(length,p.stat().st_size-cursor)
        result.append([physical,used]);cursor+=used
    if cursor!=p.stat().st_size:raise ValueError("Unmapped file area")
    return result
@contextlib.contextmanager
def mount(img,p,writable=False):
    p.mkdir(exist_ok=True)
    run("mount","-t","ext4","-o","rw,loop" if writable else "ro,noload,loop",img,p)
    try:yield p
    finally:run("umount",p)
def once(data,old,new):
    if data.count(old)!=1:raise ValueError("Unexpected source for "+old)
    return data.replace(old,new)
def metadata(tree):
    ret={}
    for p in tree.rglob("*"):
        st=p.lstat()
        v=os.readlink(p) if p.is_symlink() else digest(p) if p.is_file() else None
        ret[p.relative_to(tree).as_posix()]=(st.st_mode,st.st_uid,st.st_gid,st.st_rdev,{k:os.getxattr(p,k,follow_symlinks=False) for k in os.listxattr(p,follow_symlinks=False)},v)
    return ret
def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ("open-vendor","raw-donor","output","profile"):p.add_argument("--"+key,type=Path,required=True)
    a=p.parse_args()
    if a.output.exists() or a.profile.exists() or not a.raw_donor.is_file() or not a.open_vendor.is_file():p.error("Use regular inputs and new outputs")
    if digest(a.open_vendor)!="04c3e661fbde021af2f0344cab85533230b0b6baf46128623fb8da439094f588":p.error("Need the rc.1 public vendor image")
    ref=json.loads(Path(__file__).with_name("reference.json").read_text())
    if a.raw_donor.stat().st_size!=ref["raw_size"]:p.error("Unexpected Android vendor size")
    removed={"etc/init/android.hardware.graphics.composer@2.4-service.rc","etc/init/android.hardware.graphics.allocator@4.0-service.minigbm.rc"}
    cfg={"build.prop","etc/vintf/manifest.xml"}
    with tempfile.TemporaryDirectory(dir=a.output.parent) as temp:
        t=Path(temp); src=t/"base"; raw=t/"allocated"; clean=t/"public"; ready=t/"private-check"
        with mount(a.open_vendor,src): before=metadata(src)
        shutil.copyfile(a.open_vendor,raw); os.truncate(raw,128<<20)
        run("e2fsck","-fp",raw);run("resize2fs",raw)
        files=ref["files"]
        with mount(raw,t/"modify",True) as tree:
            for r in removed:(tree/r).unlink()
            prop=tree/"build.prop";data=prop.read_text()
            for old,new in (("egl=mesa","egl=mali"),("hwcomposer=drm_minigbm","hwcomposer=rk30board"),("gralloc=minigbm","gralloc=default")):
                data=once(data,"ro.hardware."+old+"\n","ro.hardware."+new+"\n")
            prop.write_text(data)
            manifest=tree/"etc/vintf/manifest.xml";xml=manifest.read_text()
            match=re.search(r"<name>android\.hardware\.graphics\.composer</name>(.*?)</hal>",xml,re.S)
            if not match or "<version>2.4</version>" not in match[0]:raise ValueError("Unexpected HWC manifest")
            manifest.write_text(once(xml,match[0],match[0].replace("2.4","2.1")))
            for obj in files:
                dst=tree/obj["path"]
                with dst.open("xb") as f:
                    left=obj["size"]
                    while left:
                        n=min(left,1<<20);f.write(b"\x59"*n);left-=n
                os.chown(dst,obj["uid"],obj["gid"]);os.chmod(dst,obj["mode"])
        # Write Android labels with libext2fs; host kernels need not implement SELinux.
        for item in files:
            attr=t/"label";attr.write_bytes(item["label"].encode()+b"\0")
            run("debugfs","-w","-R","ea_set -f "+str(attr)+" /"+item["path"]+" security.selinux",raw)
        run("e2image","-ra",raw,clean)
        with mount(clean,t/"extents") as tree:
            for item in files:item["dest"]=regions(tree/item["path"])
        spans=sorted((start,length) for item in files for start,length in item["dest"])
        if any(start<0 or n<=0 or start+n>clean.stat().st_size or (i and spans[i-1][0]+spans[i-1][1]>start) for i,(start,n) in enumerate(spans)):raise ValueError("Overlapping slot extents")
        with clean.open("r+b") as f:
            for start,n in spans:
                f.seek(start);f.write(bytes(n))
        run("e2fsck","-fn",clean)
        with mount(clean,t/"audit") as tree:
            after=metadata(tree);added={row["path"] for row in files}
            if set(after)!=(set(before)-removed)|added:raise ValueError("Unexpected public files")
            if any(after[n]!=before[n] for n in before.keys()-removed-cfg):raise ValueError("Unexpected change to public baseline")
            for item in files:
                found=after[item["path"]]
                if found[-1]!=hashlib.sha256(bytes(item["size"])).hexdigest() or found[4].get("security.selinux")!=item["label"].encode()+b"\0":
                    raise ValueError("Nonempty placeholder or wrong label")
        shutil.copyfile(clean,ready)
        with ready.open("r+b") as out,a.raw_donor.open("rb") as inp:
            for item in files:
                blob=bytearray()
                for off,n in item["source"]:inp.seek(off);blob+=inp.read(n)
                if hashlib.sha256(blob).hexdigest()!=item["hash"]:raise ValueError("Wrong donor: "+item["path"])
                pos=0
                for off,n in item["dest"]:out.seek(off);out.write(blob[pos:pos+n]);pos+=n
                if pos!=len(blob):raise ValueError("Invalid target range")
        with mount(ready,t/"private-audit") as tree:
            for item in files:
                if digest(tree/item["path"])!=item["hash"]:raise ValueError("Import verification failed")
        ref.update(slot_size=clean.stat().st_size,empty_hash=digest(clean),full_hash=digest(ready))
        clean.chmod(0o644);os.link(clean,a.output)
        a.profile.write_text(json.dumps(ref,indent=2)+"\n")
        print("Public slot audited; matched private reconstruction for",len(files),"components.",flush=True)
if __name__=="__main__":main()
