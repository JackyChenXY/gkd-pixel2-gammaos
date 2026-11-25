#!/usr/bin/env python3
"""Add the OEM mount and default wallpaper to a verified GammaOS v0.3.0 system."""
import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

BASE_SHA = "722647bc0ded58548435645c8d2cf740f0b712116a8871cd0d74719f37887560"
HERE = Path(__file__).resolve().parent
WALL = b"ro.config.wallpaper=/oem/app/AT4K/H700-wallpaper.jpg\n"

def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for buf in iter(lambda: f.read(4 << 20), b""):
            h.update(buf)
    return h.hexdigest()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("baseline","gamma","output"):
        p.add_argument("--"+name,type=Path,required=True)
    a=p.parse_args()
    if os.path.lexists(a.output) or not a.baseline.is_file() or digest(a.baseline)!=BASE_SHA:
        p.error("Expected the released v0.3.0 system and a new output name")
    host=a.gamma/"out-pixel2-gamma/host/linux-x86/bin"
    key=a.gamma/"external/avb/test/data/testkey_rsa2048.pem"
    env={**os.environ,"LC_ALL":"C","PATH":str(host)+":"+os.environ["PATH"]}
    def avb(*args):
        return subprocess.check_output([host/"avbtool",*args],env=env,text=True)
    avb("verify_image","--image",a.baseline,"--key",key)
    info=avb("info_image","--image",a.baseline)
    def field(name):
        return re.search(r"(?m)^\s*"+name+r":\s*(\S+)",info)[1]
    props=[]
    for name,v in re.findall(r"(?m)^\s*Prop: (.*?) -> '(.*?)'$",info):
        props.extend(["--prop",name+":"+v])
    with tempfile.TemporaryDirectory(dir=a.output.parent) as td:
        temp=Path(td); fs=temp/"system.img"; shutil.copyfile(a.baseline,fs)
        avb("erase_footer","--image",fs)
        def read(cmd):
            return subprocess.check_output(["debugfs","-R",cmd,fs],stderr=subprocess.DEVNULL)
        prop="/system/build.prop"
        marker="/system/etc/pixel2-release"
        rc="/system/etc/init/pixel2-oem.rc"
        original=read("cat "+prop)
        if not original or b"\nro.config.wallpaper=" in original or read("cat "+marker)!=b"GKD Pixel 2 community TF image 0.3.0\n" or read("stat "+rc):
            raise ValueError("Unexpected factory system")
        entries={prop:original.rstrip(b"\n")+b"\n"+WALL,marker:b"GKD Pixel 2 community TF image 0.3.1\n",rc:(HERE/"pixel2-oem.rc").read_bytes()}
        label=temp/"context";label.write_bytes(b"u:object_r:system_file:s0\x00")
        cmds=[]
        for i,(dst,data) in enumerate(entries.items()):
            src=temp/str(i);src.write_bytes(data)
            if dst in (prop,marker):cmds.append("rm "+dst)
            cmds += ["write "+str(src)+" "+dst,"set_inode_field "+dst+" mode 0100644",
                     "set_inode_field "+dst+" uid 0","set_inode_field "+dst+" gid 0",
                     "ea_set -f "+str(label)+" "+dst+" security.selinux"]
        subprocess.run(["debugfs","-w","-f","-",fs],input="\n".join(cmds)+"\n",text=True,check=True,
                       stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        for dst,data in entries.items():
            if read("cat "+dst)!=data or b"u:object_r:system_file:s0" not in read("ea_list "+dst):
                raise ValueError("Incorrect content or SELinux label: "+dst)
        subprocess.run(["e2fsck","-fn",fs],check=True,stdout=subprocess.DEVNULL)
        avb("add_hashtree_footer","--image",fs,"--partition_name","system","--partition_size",str(a.baseline.stat().st_size),
            "--algorithm",field("Algorithm"),"--hash_algorithm",field("Hash Algorithm"),"--key",key,
            "--rollback_index",field("Rollback Index"),"--salt",field("Salt"),*props)
        avb("verify_image","--image",fs,"--key",key)
        os.link(fs,a.output)
        print("Verified signed system:",digest(a.output),flush=True)

if __name__=="__main__":
    main()
