#!/usr/bin/env python3
"""Create a clean ext4 system partition from the Pixel 2 factory build."""
import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import stat
import struct
import subprocess
import tempfile
import zipfile
import zlib
from pathlib import Path

MIB = 1 << 20
BASE = "6ecdaa0ec8f48b579d317e2d18a8200cb9aa1ce1f61da1965e0c3a5b15ec5a1b"
LAUNCHER = "system/system_ext/priv-app/TrebuchetQuickStep"
NAV = "system/product/app/Pixel2PadNavigation"
ANIM = "system/product/media/bootanimation.zip"

def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(4*MIB), b""):
            h.update(chunk)
    return h.hexdigest()

@contextlib.contextmanager
def mounted(image, point):
    point.mkdir()
    subprocess.run(["mount","-t","ext4","-o","loop,ro,noload",image,point],check=True)
    try:
        yield
    finally:
        subprocess.run(["umount",point],check=True)

def entries(root):
    yield ".", root
    for directory, dirs, files in os.walk(root):
        for name in sorted(dirs + files):
            path = Path(directory)/name
            yield path.relative_to(root).as_posix(), path

def attrs(path):
    return {n:os.getxattr(path,n,follow_symlinks=False) for n in os.listxattr(path,follow_symlinks=False)}

def png(w,h,rgb):
    def chunk(typ,data):
        return struct.pack(">I",len(data))+typ+data+struct.pack(">I",zlib.crc32(typ+data)&0xffffffff)
    rows = b"".join(b"\0"+rgb[y*w*3:(y+1)*w*3] for y in range(h))
    return b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR",struct.pack(">IIBBBBB",w,h,8,2,0,0,0))+chunk(b"IDAT",zlib.compress(rows,9))+chunk(b"IEND",b"")

def boot_animation(path):
    # Original, quiet 3-dot progress animation. Android bootanimation needs stored zip entries.
    w = h = 160
    with zipfile.ZipFile(path,"w",compression=zipfile.ZIP_STORED) as z:
        z.writestr("desc.txt","160 160 8\np 0 0 part0\n")
        for frame in range(16):
            rgb = bytearray(b"\x00\x00\x00"*(w*h))
            for dot,cx in enumerate((59,80,101)):
                pulse = 8 - abs((frame-3*dot)%16-8)
                color = bytes((44+12*pulse,86+12*pulse,108+12*pulse))
                for y in range(74,87):
                    for x in range(cx-6,cx+7):
                        if (x-cx)**2+(y-80)**2<=36:
                            i=(y*w+x)*3
                            rgb[i:i+3]=color
            z.writestr("part0/%02d.png"%frame,png(w,h,rgb))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ("baseline","gamma","runtime","desktop","navigation","output"):
        p.add_argument("--"+arg,required=True,type=Path)
    a=p.parse_args()
    if os.getuid()!=0 or not a.baseline.is_file() or sha(a.baseline)!=BASE:
        p.error("Use a private mount namespace as root and the verified factory system input")
    if a.output.exists() or a.output.is_symlink():
        p.error("Choose a new output file")
    tools=a.gamma/"out-pixel2-gamma/host/linux-x86/bin"
    env={**os.environ,"PATH":str(tools)+":"+os.environ["PATH"]}
    def avb(*args):
        subprocess.run([tools/"avbtool",*args],check=True,env=env,stdout=subprocess.DEVNULL)
    key=a.gamma/"external/avb/test/data/testkey_rsa2048.pem"
    avb("verify_image","--image",a.baseline,"--key",key)
    with tempfile.TemporaryDirectory(dir=a.output.parent,prefix="system-") as td:
        w=Path(td); tree=w/"tree"; tree.mkdir(); origin=w/"origin"; raw=w/"system.img"
        with mounted(a.baseline,origin):
            omitted=[LAUNCHER+"/oat"]
            for v in (28,29,30,31):
                for suffix in ("",".apex"):
                    rel="system/system_ext/apex/com.android.vndk.v%d%s"%(v,suffix)
                    assert (origin/rel).exists(),rel
                    omitted.append(rel)
            for forbidden in ("system/product/app/daijisho","system/product/app/webview","system/product/app/Jelly","adb_keys","system/etc/security/adb_keys"):
                assert not (origin/forbidden).exists(),forbidden
            for area in ("data","metadata"):
                assert not list((origin/area).iterdir()),area
            subprocess.run(["rsync","-aH","--numeric-ids",*["--exclude=/"+s for s in omitted],str(origin)+"/",str(tree)+"/"],check=True)
            metadata={n:attrs(p) for n,p in entries(origin) if not any(n==s or n.startswith(s+"/") for s in omitted)}
            replacements={"system/bin/getSPL":a.runtime/"getSPL","system/bin/pixel2-extra-swap":a.runtime/"pixel2-extra-swap",LAUNCHER+"/TrebuchetQuickStep.apk":a.desktop}
            for n,src in replacements.items():
                assert (tree/n).is_file() and not (tree/n).is_symlink()
                shutil.copyfile(src,tree/n)
            with zipfile.ZipFile(a.desktop) as z:
                assert "classes.dex" in z.namelist()
            with zipfile.ZipFile(a.navigation) as z:
                lib=z.read("lib/armeabi-v7a/libpadchord.so")
            app=tree/NAV
            (app/"lib/arm").mkdir(parents=True)
            shutil.copyfile(a.navigation,app/"Pixel2PadNavigation.apk")
            (app/"lib/arm/libpadchord.so").write_bytes(lib)
            for n,f in entries(app):
                os.chmod(f,0o755 if f.is_dir() else 0o644)
                metadata[NAV+("/"+n if n!="." else "")]=metadata["system/product/app"]
            boot_animation(tree/ANIM)
            marker="system/etc/pixel2-release"
            (tree/marker).write_text("GKD Pixel 2 community TF image 0.3.0-rc.1\n",encoding="ascii")
            os.chmod(tree/marker,0o644)
            metadata[marker]=metadata["system/etc"]
            for n in ("system/build.prop","system/system_ext/etc/build.prop","system/product/etc/build.prop"):
                f=tree/n
                if f.is_file():
                    s=f.read_text()
                    s=re.sub(r"(?m)^ro\.setupwizard\.mode=.*$","ro.setupwizard.mode=DISABLED",s)
                    s=re.sub(r"(?m)^ro\.product\.locale=.*$","ro.product.locale=zh-CN",s)
                    f.write_text(s)
            assert "ro.adb.secure=1" in (tree/"system/build.prop").read_text()
            # Publish a new, zero-backed filesystem. Removed files are never written to it.
            with raw.open("xb") as f:
                f.truncate(1712*MIB)
            subprocess.run(["/sbin/mke2fs","-q","-t","ext4","-F","-b","4096","-I","256","-m","0",
                            "-U","bfc95c3a-2ebd-465f-83f6-16f18b7e670e","-L","/",
                            "-O","none,ext_attr,dir_index,filetype,extent,sparse_super,large_file,huge_file,uninit_bg,dir_nlink,extra_isize",
                            "-E","lazy_itable_init=0","-d",tree,raw],check=True)
            # Restore Android SELinux labels and Linux capabilities, including symlinks.
            saved={}; commands=[]
            for n,fields in metadata.items():
                dest="/" if n=="." else "/"+n
                if any(c in dest for c in '"\\\n\r'):
                    raise ValueError(dest)
                for field,value in fields.items():
                    if value not in saved:
                        label=w/("label-%d"%len(saved)); label.write_bytes(value); saved[value]=label
                    commands.append('ea_set -f "%s" "%s" %s'%(saved[value],dest,field))
            batch=w/"labels"; batch.write_text("\n".join(commands)+"\n")
            proc=subprocess.run(["/sbin/debugfs","-w","-f",batch,raw],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,check=True)
            if any(line and not line.startswith(b"debugfs ") for line in proc.stderr.splitlines()):
                raise RuntimeError(proc.stderr.decode()[-1400:])
            subprocess.run(["/sbin/e2fsck","-fn",raw],check=True,stdout=subprocess.DEVNULL)
            with mounted(raw,w/"check"):
                dst=dict(entries(w/"check"))
                assert set(dst)==set(metadata),(set(dst)^set(metadata))
                for n,staged in entries(tree):
                    actual=dst[n]; before=staged.lstat(); after=actual.lstat()
                    assert (before.st_mode,before.st_uid,before.st_gid,before.st_rdev)==(after.st_mode,after.st_uid,after.st_gid,after.st_rdev),("mode/owner",n)
                    assert attrs(actual)==metadata[n],("xattr",n)
                    if actual.is_symlink():
                        assert os.readlink(actual)==os.readlink(staged),n
                    elif actual.is_file():
                        assert sha(actual)==sha(staged),n
            print("Verified contents, ownership, links and extended attributes for",len(metadata),"paths.",flush=True)
        info=subprocess.check_output([tools/"avbtool","info_image","--image",a.baseline],text=True)
        def field(label):
            return re.search(r"(?m)^\s*"+label+r":\s*(\S+)",info).group(1)
        props=[]
        for k,v in re.findall(r"(?m)^\s*Prop: (.*?) -> '(.*?)'$",info):
            props.extend(["--prop",k+":"+v])
        avb("add_hashtree_footer","--image",raw,"--partition_name","system","--partition_size",str(1792*MIB),
            "--algorithm",field("Algorithm"),"--key",key,"--rollback_index",field("Rollback Index"),
            "--hash_algorithm",field("Hash Algorithm"),"--salt",field("Salt"),*props)
        avb("verify_image","--image",raw,"--key",key)
        os.link(raw,a.output)
        print("system",a.output.stat().st_size,sha(a.output),flush=True)
if __name__=="__main__":
    main()
