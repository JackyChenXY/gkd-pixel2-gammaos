#!/usr/bin/env python3
"""Create an empty, valid OEM ext4 filesystem and the byte map for local personalization."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
from zipfile import ZipFile

BLOCK = 4096
FS_SIZE = 32 << 20
PACKAGE_SIZE = 12272145
PACKAGE_SHA = "b2fa0343e903ad01c3854999dba70335ba4df5f5522dd931ed9d7189cf841a7d"
WALL = "res/raw/rgsp_wallpaper.jpg"
LIB = "lib/armeabi-v7a/libandroidx.graphics.path.so"
FILES = (
    ("AT4K.apk", "", PACKAGE_SIZE, PACKAGE_SHA),
    ("H700-wallpaper.jpg", WALL, 1324045, "0d99ad08346620e240fa6eb7e765bb55996d4a311c8141a209626e08cad88997"),
    ("lib/arm/libandroidx.graphics.path.so", LIB, 7252, "41399eba6fc2a60f6f14642375c1824f3cf25eb8fec7397d753730a3ceda3e2b"),
)
HERE = Path(__file__).resolve().parent
EPOCH = 1735689600
ENV = {**os.environ, "LC_ALL": "C", "E2FSPROGS_FAKE_TIME": str(EPOCH)}

def sha(data):
    return hashlib.sha256(data).hexdigest()

def debug(image, cmd):
    return subprocess.check_output(["debugfs", "-R", cmd, image], text=True, stderr=subprocess.DEVNULL, env=ENV)

def extents(image, path, size):
    out = []
    used = 0
    for line in debug(image, "dump_extents -l " + path).splitlines()[1:]:
        vals = re.fullmatch(r"\s*(\d+)/\s*(\d+)\s+\d+/\s*\d+\s+(\d+)\s*-\s*(\d+)\s+(\d+)\s*-\s*(\d+)\s+(\d+)\s*", line)
        if not vals:
            raise ValueError("Unrecognized ext4 extent: " + line)
        level, depth, a, b, start, end, blocks = map(int, vals.groups())
        if level != depth or a * BLOCK != used or b-a+1 != blocks or end-start+1 != blocks:
            raise ValueError("Unexpected holes or ext4 extent tree")
        n = min(size-used, blocks*BLOCK)
        if n <= 0 or (start*BLOCK+n) > FS_SIZE:
            raise ValueError("Extent out of bounds")
        out.append([start*BLOCK, n])
        used += n
    if used != size:
        raise ValueError("Incomplete file extent mapping")
    return out

def make(args):
    for path in (args.empty, args.full, args.map):
        if os.path.lexists(path):
            raise ValueError("Choose new outputs: " + str(path))
    if args.apk.stat().st_size != PACKAGE_SIZE or sha(args.apk.read_bytes()) != PACKAGE_SHA:
        raise ValueError("Expected signed H700 AT4K 1.2")
    blob = args.apk.read_bytes()
    with ZipFile(args.apk) as apk:
        inputs = [blob, apk.read(WALL), apk.read(LIB)]
    for (_, _, size, digest), data in zip(FILES, inputs, strict=True):
        if (len(data), sha(data)) != (size, digest):
            raise ValueError("Unexpected package resource")
    with tempfile.TemporaryDirectory(dir=args.empty.parent) as td:
        root = Path(td)
        tree = root/"tree"
        pref = tree/"off/preferred-apps"
        pref.mkdir(parents=True)
        shutil.copyfile(HERE/"at4k-home.xml", pref/"at4k-home.xml")
        for name, _, size, _ in FILES:
            dst = tree/"pad/AT4K"/name
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(b"Z"*size)  # allocate every data block without importing external contents
        for path in [tree, *tree.rglob("*")]:
            path.chmod(0o755 if path.is_dir() else 0o644)
            os.utime(path, (EPOCH, EPOCH))
        image = root/"oem"
        with image.open("xb") as f:
            f.truncate(FS_SIZE)
        subprocess.run(["mke2fs","-q","-F","-t","ext4","-b","4096","-I","256","-N","256","-m","0",
                        "-O","none,extent,filetype,sparse_super,large_file","-E","lazy_itable_init=0,nodiscard,root_owner=0:0",
                        "-U","af1a88b3-675e-4d54-aa04-27d8968d0301","-L","PIXEL2HOME","-d",tree,image],
                       env=ENV,check=True)
        # Do not inherit the builder's uid or gid from mke2fs -d.
        cmds = "".join("set_inode_field /%s %s 0\n" % (p.relative_to(tree), fld)
                       for p in sorted(tree.rglob("*")) for fld in ("uid","gid"))
        subprocess.run(["debugfs","-w","-f","-",image],input=cmds,text=True,
                       stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=ENV,check=True)
        blank = bytearray(image.read_bytes())
        root_blocks = debug(image,"blocks /").split()
        if len(root_blocks) != 1:
            raise ValueError("Expected one root directory block")
        base = int(root_blocks[0])*BLOCK
        directories = []
        pos = 0
        while pos < BLOCK:
            inode, length, n, kind = struct.unpack_from("<IHBB",blank,base+pos)
            if length < 8 or length % 4 or pos+length > BLOCK or n > length-8:
                raise ValueError("Invalid root directory")
            start = base+pos+8
            label = bytes(blank[start:start+n])
            if inode and kind == 2 and label in (b"pad",b"off"):
                directories.append({"offset":start,"before":label.decode(),"after":"app" if label==b"pad" else "etc"})
            pos += length
        if len(directories)!=2 or len({x["before"] for x in directories})!=2:
            raise ValueError("OEM activation directories missing")
        files = []
        for name, entry, size, digest in FILES:
            dst = extents(image,"/pad/AT4K/"+name,size)
            for off,n in dst:
                if blank[off:off+n]!=b"Z"*n:
                    raise ValueError("Bad allocation map")
                blank[off:off+n]=bytes(n)
            files.append({"path":name,"entry":entry,"size":size,"hash":digest,"dest":dst})
        filled = blank.copy()
        for d in directories:
            at=d["offset"]; filled[at:at+3]=d["after"].encode()
        for file,data in zip(files,inputs,strict=True):
            cursor=0
            for at,n in file["dest"]:
                filled[at:at+n]=data[cursor:cursor+n]; cursor+=n
        profile={"size":FS_SIZE,"empty_sha256":sha(blank),"full_sha256":sha(filled),
                 "directories":directories,"files":files}
        for name,content,active in [("empty",blank,False),("full",filled,True)]:
            fs=root/name
            fs.write_bytes(content)
            subprocess.run(["e2fsck","-fn",fs],env=ENV,stdout=subprocess.DEVNULL,check=True)
            names = debug(fs,"ls -p /")
            if ("/app/" in names)!=active or ("/etc/" in names)!=active:
                raise ValueError("Incorrect package visibility")
            if active:
                for file in files:
                    extracted=root/"check"
                    debug(fs,"dump /app/AT4K/"+file["path"]+" "+str(extracted))
                    if sha(extracted.read_bytes())!=file["hash"]:
                        raise ValueError("Filesystem content mismatch")
                    extracted.unlink()
                if debug(fs,"cat /etc/preferred-apps/at4k-home.xml")!=(HERE/"at4k-home.xml").read_text():
                    raise ValueError("Wrong default HOME")
        for name,out in [("empty",args.empty),("full",args.full)]:
            with out.open("xb") as dest, (root/name).open("rb") as src:
                shutil.copyfileobj(src,dest)
        with args.map.open("x") as dest:
            json.dump(profile,dest,indent=2); dest.write("\n")
        print("OEM",profile["empty_sha256"],profile["full_sha256"],flush=True)

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ("apk","empty","full","map"):
        parser.add_argument("--"+key,required=True,type=Path)
    make(parser.parse_args())
