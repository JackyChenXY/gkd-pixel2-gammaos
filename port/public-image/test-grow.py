#!/usr/bin/env python3
"""Test first-boot growth on sparse regular files. No block devices are opened."""
import argparse
import ctypes as c
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import uuid
import zlib

p=argparse.ArgumentParser(description=__doc__)
p.add_argument("gpt",type=Path)
a=p.parse_args()
gpt=json.loads((a.gpt/"partition-layout.json").read_text())
source=(a.gpt/"gpt-primary.bin").read_bytes()
old_backup=(a.gpt/"gpt-backup.bin").read_bytes()
size=gpt["disk_bytes"]
uid=uuid.UUID(gpt["disk_guid"]).bytes_le
crc=zlib.crc32(source[1024:])
user=next(v["start_bytes"] for v in gpt["partitions"] if v["name"]=="userdata")
with tempfile.TemporaryDirectory() as td:
    work=Path(td)
    subprocess.run(["cc","-shared","-fPIC","-Wall","-Wextra","-Werror","-O2",Path(__file__).with_name("grow-card.c"),"-o",work/"grow.so"],check=True)
    expand=c.CDLL(str(work/"grow.so")).pixel2_grow_fd
    expand.argtypes=(c.c_int,c.c_uint64,c.c_uint64,c.c_char_p,c.c_uint32,c.POINTER(c.c_uint64))
    expand.restype=c.c_int
    def make(n):
        f=open(work/"card","w+b",buffering=0)
        f.truncate(n);os.pwrite(f.fileno(),source,0);os.pwrite(f.fileno(),old_backup,size-len(old_backup))
        return f
    def run(f,ident=uid):
        start=c.c_uint64()
        return expand(f.fileno(),os.fstat(f.fileno()).st_size,size,ident,crc,c.byref(start))
    def verify(f,n):
        header=os.pread(f.fileno(),512,512)
        assert struct.unpack_from("<Q",header,32)[0]==n//512-1
        table=os.pread(f.fileno(),16384,1024)
        expected=bytearray(source[1024:]);struct.pack_into("<Q",expected,14*128+40,n//512-34)
        assert table==expected
        out=subprocess.check_output(["sgdisk","-v",f.name],text=True,stderr=subprocess.STDOUT)
        assert "No problems found" in out,out
    checks=0
    for n in (size,8*10**9,16*10**9,32*10**9,125069950976,128*10**9):
        with make(n) as f:
            assert run(f)==int(n>size)
            verify(f,n)
            assert run(f)==0
            checks+=1
    n=16*10**9
    for condition in ("different GUID","existing user data","modified partition","invalid backup"):
        with make(n) as f:
            params={}
            if condition=="different GUID": params["ident"]=b"X"*16
            if condition=="existing user data": os.pwrite(f.fileno(),b"existing",user+1024)
            if condition=="modified partition": os.pwrite(f.fileno(),b"X",1024+40)
            if condition=="invalid backup": os.pwrite(f.fileno(),b"X",size-512)
            before=os.pread(f.fileno(),len(source),0)
            assert run(f,**params)==0 and os.pread(f.fileno(),len(source),0)==before
            assert os.pread(f.fileno(),512,n-512)==bytes(512)
            checks+=1
    with make(n) as f:
        assert run(f)==1
        final=os.pread(f.fileno(),len(source),0)
        end=os.pread(f.fileno(),len(old_backup),n-len(old_backup))
    # Recover at each boundary in backup, primary and protective MBR writes.
    writes=[(n-len(old_backup),end[:-512]),(n-512,end[-512:]),(1024,final[1024:]),(512,final[512:1024]),(0,final[:512])]
    for count in range(1,5):
        with make(n) as f:
            for off,data in writes[:count]: os.pwrite(f.fileno(),data,off)
            assert run(f)==1
            verify(f,n)
            checks+=1
    print(checks,"card geometry, repeat-boot, interrupted update and no-write cases passed")
