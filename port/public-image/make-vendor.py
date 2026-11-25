#!/usr/bin/env python3
"""Remove optional camera SDK binaries and zero all unallocated vendor blocks."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

base,out=map(Path,sys.argv[1:])
if not base.is_file() or out.exists() or out.is_symlink() or os.getuid()!=0:
    raise SystemExit("Use a private mount namespace as root, a regular input and new output file")
removed={"bin/media-ctl","bin/v4l2-ctl"}
def sha(path):
    with path.open("rb") as f:
        h=hashlib.sha256()
        for b in iter(lambda:f.read(1<<20),b""): h.update(b)
    return h.hexdigest()
def contents(root):
    result={}
    for p in [root,*root.rglob("*")]:
        n=p.relative_to(root).as_posix()
        st=p.lstat(); extra={k:os.getxattr(p,k,follow_symlinks=False) for k in os.listxattr(p,follow_symlinks=False)}
        value=os.readlink(p) if p.is_symlink() else sha(p) if p.is_file() else ""
        result[n]=(st.st_mode,st.st_uid,st.st_gid,st.st_rdev,extra,value)
    return result
with tempfile.TemporaryDirectory(dir=out.parent) as td:
    w=Path(td); old=w/"old"; new=w/"new"; old.mkdir(); new.mkdir()
    subprocess.run(["mount","-t","ext4","-o","ro,noload,loop",base,old],check=True)
    try:
        baseline=contents(old)
        assert all(n in baseline for n in removed)
        assert baseline["lib/libgallium_dri.so"][-1]=="8f225f82a0fd10912e7e8ad6d678d51da076ad4b96cbf863b3b861fc28ba3801"
        assert "ro.vndk.version=32" in (old/"build.prop").read_text()
    finally:
        subprocess.run(["umount",old],check=True)
    copy=w/"modified"; shutil.copyfile(base,copy)
    for n in sorted(removed):
        subprocess.run(["debugfs","-w","-R","rm /"+n,copy],check=True,stdout=subprocess.DEVNULL)
    compact=w/"public"
    subprocess.run(["e2image","-ra",copy,compact],check=True)
    if compact.stat().st_size!=base.stat().st_size: raise ValueError("unexpected vendor size")
    subprocess.run(["e2fsck","-fn",compact],check=True,stdout=subprocess.DEVNULL)
    subprocess.run(["mount","-t","ext4","-o","ro,noload,loop",compact,new],check=True)
    try:
        updated=contents(new)
        assert set(baseline)-set(updated)==removed and set(updated)<=set(baseline)
        assert all(updated[n]==baseline[n] for n in updated)
    finally:
        subprocess.run(["umount",new],check=True)
    compact.chmod(0o644)
    os.link(compact,out)
    print("Verified",len(updated),"vendor paths including the five graphics libraries.",sha(out))
