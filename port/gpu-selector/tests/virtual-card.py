#!/usr/bin/env python3
"""Install a disposable test fixture on a COPY of the public image; never open a block device."""
from pathlib import Path
import argparse, importlib.util, os, shutil, subprocess, tempfile
here=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("assembly",here.parent/"assemble.py")
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
p=argparse.ArgumentParser(description=__doc__)
for n in ("image","odm","client","private-pack","output"):p.add_argument("--"+n,type=Path,required=True)
args=p.parse_args()
if args.output.is_symlink() or args.output.exists() or not all(f.is_file() for f in (args.image,args.odm,args.client,args.private_pack)):p.error("Expected regular files and a new virtual disk")
def run(*cmd):subprocess.run(cmd,check=True,stdout=subprocess.DEVNULL)
with tempfile.TemporaryDirectory(dir=args.output.parent) as temp:
    t=Path(temp);disk=t/"disk";run("cp","--reflink=auto","--sparse=always","--",args.image,disk)
    odm=t/"odm";shutil.copyfile(args.odm,odm)
    for s in ("rm /etc/package_performance.xml","rm /etc/NOTICE.xml.gz","mkdir /etc/init","write "+str(here/"guest.rc")+" /etc/init/p2-gpu-qualification.rc","set_inode_field /etc/init/p2-gpu-qualification.rc mode 0100644"):
        run("debugfs","-w","-R",s,odm)
    if subprocess.check_output(["debugfs","-R","cat /etc/init/p2-gpu-qualification.rc",odm],stderr=subprocess.DEVNULL)!=(here/"guest.rc").read_bytes():raise ValueError("Test init missing")
    tree=t/"fixture";tree.mkdir();shutil.copy2(args.client,tree/"client");(tree/"client").chmod(0o755)
    shutil.copyfile(args.private_pack,tree/"driver.zip");(tree/"bad").write_text("invalid test input\n")
    fs=t/"fixture.img"
    with fs.open("xb") as f:f.truncate(64<<20)
    run("mke2fs","-q","-F","-t","ext4","-b","4096","-O","none,ext_attr,dir_index,filetype,extent,sparse_super,large_file,huge_file,uninit_bg,dir_nlink,extra_isize","-d",tree,fs)
    with disk.open("r+b") as f:
        points=a.parts(f);start,size=a.extent(f,points["super"][0],0,"odm")
        if size!=odm.stat().st_size or a.digest(f,start,size)!=a.sha(args.odm):raise ValueError("Unexpected base ODM")
        for (off,bound),src in (((start,size),odm),(points["recovery"],fs)):
            if src.stat().st_size>bound:raise ValueError("Fixture exceeds its partition")
            f.seek(off)
            with src.open("rb") as srcfile:shutil.copyfileobj(srcfile,f)
        f.flush();os.fsync(f.fileno())
    os.link(disk,args.output)
print("Prepared private diagnostic disk; production system, boot files and GPU slot unchanged.")
