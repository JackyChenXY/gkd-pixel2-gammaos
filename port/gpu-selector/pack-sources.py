#!/usr/bin/env python3
"""Package current port sources and the corresponding third-party source material."""
import argparse
import hashlib
import os
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
import tempfile

def sha(path):
    h=hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda:stream.read(4<<20),b""):
            h.update(block)
    return h.hexdigest()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ("dependencies","go-source","kbase-config","output"):
        p.add_argument("--"+key,type=Path,required=True)
    p.add_argument("--commit",default="HEAD")
    a=p.parse_args()
    repo=Path(__file__).resolve().parents[2]
    if os.path.lexists(a.output):p.error("Choose a new archive name")
    if sha(a.go_source)!="73cfb8571aec0c01177687db87163d46aa20e9779672772891aa17654d9a6099":
        p.error("Expected the Go 1.27.4 source archive")
    if "CONFIG_MALI_BIFROST=y" not in a.kbase_config.read_text():p.error("Wrong kbase config")
    roots={"boot","graphics","kernel","notices","runtime","sources"}
    added={"runtime/go1.27.4.src.tar.gz","kernel/pixel2-kbase.config"}
    required={"kernel/pixel2-linux-5.10.226-source.tar.gz","boot/u-boot-v2025.10.tar.gz",
              "boot/tf-a-5103554.tar.gz","runtime/musl-1.2.5.tar.gz","boot/rkbin-LICENSE",
              "graphics/Pixel2-graphics-and-krkr2.tar.gz","sources/android-userspace-source.tar.gz",
              "sources/source-map.json","notices/system-NOTICE.xml.gz"}
    with tempfile.TemporaryDirectory(dir=a.output.parent) as tmp:
        tmp=Path(tmp)
        current=tmp/"port.tar.gz"
        subprocess.run(["git","-C",str(repo),"archive","--format=tar.gz","--prefix=gkd-pixel2-gammaos/",
                        "-o",str(current),a.commit],check=True)
        revision=subprocess.check_output(["git","-C",str(repo),"rev-parse",a.commit],text=True).strip()
        info=tmp/"README.txt"
        info.write_text("GKD Pixel 2 GammaOS v0.3.1\nPort revision "+revision+
                        "\nCurrent port and build instructions: port.tar.gz\n"+
                        "Kernel and boot sources: kernel/ and boot/\nAndroid component sources: sources/\n"+
                        "Mesa, libdrm and simulator compatibility sources: graphics/\n"+
                        "Runtime sources and third-party notices: runtime/ and notices/\n",encoding="utf-8")
        bundle=tmp/"complete.tar.gz"; found=set()
        with tarfile.open(bundle,"w:gz",compresslevel=1) as out,tarfile.open(a.dependencies,"r|*") as inp:
            for item in inp:
                path=PurePosixPath(item.name)
                if path.is_absolute() or ".." in path.parts:raise ValueError(item.name)
                if not path.parts or path.parts[0] not in roots or item.name in added:continue
                if not (item.isfile() or item.isdir()):raise ValueError("Unexpected member type: "+item.name)
                if item.name in found:raise ValueError("Duplicate member: "+item.name)
                out.addfile(item,inp.extractfile(item) if item.isfile() else None)
                found.add(item.name)
            if required-found:raise ValueError("Missing dependency sources: "+str(required-found))
            for key,path in [("port.tar.gz",current),("runtime/go1.27.4.src.tar.gz",a.go_source),
                             ("kernel/pixel2-kbase.config",a.kbase_config),("README.txt",info)]:
                out.add(path,arcname=key,recursive=False)
        os.link(bundle,a.output)
    print(sha(a.output),a.output.name)
if __name__=="__main__":main()
