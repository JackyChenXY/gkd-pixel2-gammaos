#!/usr/bin/env python3
"""Add the signed Settings tile and driver service to the verified rc.1 system."""
import argparse, contextlib, hashlib, os, re, shutil, subprocess, tempfile
from pathlib import Path
def sha(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(2<<20),b""):h.update(b)
    return h.hexdigest()
def run(*a,**kw):return subprocess.run(a,check=True,**kw)
@contextlib.contextmanager
def mounted(img,point,rw=False):
    point.mkdir(exist_ok=True);run("mount","-o","rw,loop" if rw else "ro,noload,loop",img,point)
    try:yield point
    finally:run("umount",point)
def snapshot(root):
    out={}
    for p in root.rglob("*"):
        s=p.lstat();x={k:os.getxattr(p,k,follow_symlinks=False) for k in os.listxattr(p,follow_symlinks=False)}
        v=os.readlink(p) if p.is_symlink() else sha(p) if p.is_file() else ""
        out[p.relative_to(root).as_posix()]=(s.st_uid,s.st_gid,s.st_mode,x,v)
    return out
def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ("baseline","gamma","tools","output"):p.add_argument("--"+k,required=True,type=Path)
    a=p.parse_args()
    if a.output.exists() or not a.baseline.is_file() or sha(a.baseline)!="aaf1f661ed14d10930bb1d04cbd36476ac2992006a681bbb529775a27448b108":p.error("Expected rc.1 system and a new output file")
    host=a.gamma/"out-pixel2-gamma/host/linux-x86/bin";key=a.gamma/"external/avb/test/data/testkey_rsa2048.pem"
    env={**os.environ,"PATH":str(host)+":"+os.environ["PATH"]}
    def avb(*cmd):run(host/"avbtool",*cmd,env=env,stdout=subprocess.DEVNULL)
    avb("verify_image","--image",a.baseline,"--key",key)
    info=subprocess.check_output([host/"avbtool","info_image","--image",a.baseline],env=env,text=True)
    def field(n):return re.search(r"(?m)^\s*"+n+r":\s*(\S+)",info)[1]
    props=[]
    for k,v in re.findall(r"(?m)^\s*Prop: (.*?) -> '(.*?)'$",info):props+=["--prop",k+":"+v]
    here=Path(__file__).resolve().parent
    app="system/priv-app/Pixel2GpuSelector"
    items={app+"/Pixel2GpuSelector.apk":a.tools/"Pixel2GpuSelector.apk","system/bin/pixel2-gpu":a.tools/"pixel2-gpu","system/etc/init/pixel2-gpu.rc":here/"pixel2-gpu.rc"}
    with tempfile.TemporaryDirectory(dir=a.output.parent) as tmp:
        t=Path(tmp); raw=t/"system.img";point=t/"mount"
        with mounted(a.baseline,point):old=snapshot(point)
        shutil.copyfile(a.baseline,raw);avb("erase_footer","--image",raw)
        with mounted(raw,point,True):
            (point/app).mkdir()
            for name,src in items.items():
                dst=point/name
                if dst.exists():raise ValueError(name)
                shutil.copyfile(src,dst);dst.chmod(0o755 if name.startswith("system/bin/") else 0o644)
            release=point/"system/etc/pixel2-release"
            if "0.3.0-rc.1" not in release.read_text():raise ValueError("Unknown release")
            release.write_text("GKD Pixel 2 community TF image 0.3.0\n")
        label=t/"system.label";label.write_bytes(b"u:object_r:system_file:s0\0")
        for n in [app,*items]:run("debugfs","-w","-R","ea_set -f "+str(label)+" /"+n+" security.selinux",raw,stdout=subprocess.DEVNULL)
        run("e2fsck","-fn",raw,stdout=subprocess.DEVNULL)
        with mounted(raw,point):
            new=snapshot(point)
            if set(new)-set(old)!={app,*items} or old.keys()-new.keys():raise ValueError("Unexpected system paths")
            if any(new[n]!=old[n] for n in old if n!="system/etc/pixel2-release"):raise ValueError("Unexpected changed system content")
            for n,src in items.items():
                if new[n][-1]!=sha(src) or new[n][3].get("security.selinux")!=label.read_bytes():raise ValueError(n)
        avb("add_hashtree_footer","--image",raw,"--partition_name","system","--partition_size",str(a.baseline.stat().st_size),"--algorithm",field("Algorithm"),"--key",key,"--rollback_index",field("Rollback Index"),"--hash_algorithm",field("Hash Algorithm"),"--salt",field("Salt"),*props)
        avb("verify_image","--image",raw,"--key",key);os.link(raw,a.output)
        print("Verified system paths",len(new),"SHA256",sha(a.output),flush=True)
if __name__=="__main__": main()
