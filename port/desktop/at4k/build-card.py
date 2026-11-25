#!/usr/bin/env python3
"""Build a flashable desktop release by replacing two checked ranges of the v0.3.0 card."""
import argparse
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("pixel2_gpu_assembly",HERE.parent.parent/"gpu-selector/assemble.py")
gpu=importlib.util.module_from_spec(spec)
spec.loader.exec_module(gpu)
SIZE=7516192768
INPUT={"public":"44835475571d1b41fc9677a3feafb9a331769bfcbfa9a13d56853684f432d205",
       "desktop":"126c33c22301ecdcbde3b2f3ddf6d1a64b1ce2cf16ef7e3cce9dd728d6b76786"}
OLD_SYSTEM="722647bc0ded58548435645c8d2cf740f0b712116a8871cd0d74719f37887560"
BLOCK=4<<20
ZERO=bytes(BLOCK)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--kind",choices=INPUT,required=True)
    for n in ("base","system","oem","output"):
        p.add_argument("--"+n,type=Path,required=True)
    a=p.parse_args()
    if os.path.lexists(a.output) or not all(f.is_file() for f in (a.base,a.system,a.oem)):
        p.error("Use regular inputs and a new output file")
    oem=json.loads((HERE.parent.parent/"gpu-selector/backend/card/oem.json").read_text())
    key="empty_sha256" if a.kind=="public" else "full_sha256"
    if a.oem.stat().st_size!=oem["size"] or gpu.sha(a.oem)!=oem[key]:
        raise ValueError("Wrong OEM image for this output")
    with (gzip.open(a.base,"rb") if a.base.suffix==".gz" else a.base.open("rb")) as src:
        parts=gpu.parts(src)
        off,n=parts["recovery"]
        system,size=gpu.extent(src,parts["super"][0],0,"system")
        if (off,n)!=(214958080,113246208) or size!=a.system.stat().st_size or gpu.extent(src,parts["super"][0],1,"system")!=(system,size):
            raise ValueError("Unexpected board layout")
        ranges=[(off,oem["size"],a.oem), (system,size,a.system)]
        with tempfile.TemporaryDirectory(dir=a.output.parent) as tmp:
            raw=Path(tmp)/"card.img"; src.seek(0)
            original=hashlib.sha256(); final=hashlib.sha256()
            with raw.open("xb") as dst:
                def transfer(count, replacement=None, zero=False):
                    before=hashlib.sha256()
                    rem=count
                    while rem:
                        want=min(BLOCK,rem); data=src.read(want)
                        if len(data)!=want:raise EOFError("Truncated base")
                        original.update(data)
                        if replacement:
                            before.update(data)
                            if zero and data!=ZERO[:want]:raise ValueError("OEM destination already in use")
                            data=replacement.read(want)
                            if len(data)!=want:raise EOFError("Truncated replacement")
                        final.update(data)
                        if data==ZERO[:want]:dst.seek(want,1)
                        else:dst.write(data)
                        rem-=want
                    return before.hexdigest()
                for start,count,path in ranges:
                    transfer(start-dst.tell())
                    with path.open("rb") as f:
                        old=transfer(count,f,path==a.oem)
                    if path==a.system and old!=OLD_SYSTEM:raise ValueError("Unexpected original system")
                transfer(SIZE-dst.tell())
                if src.read(1) or original.hexdigest()!=INPUT[a.kind]:raise ValueError("Original card checksum mismatch")
                dst.truncate(SIZE);dst.flush();os.fsync(dst.fileno())
            if gpu.sha(raw)!=final.hexdigest():raise ValueError("Complete output readback failed")
            os.link(raw,a.output)
            print(a.kind,SIZE,final.hexdigest(),flush=True)
if __name__=="__main__":
    main()
