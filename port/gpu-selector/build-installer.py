#!/usr/bin/env python3
"""Build the Windows x64 image assistant from the Go sources and pinned support archive."""
import argparse
import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE / "backend"
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--go", default="go")
parser.add_argument("--support", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
expected = (BACKEND / "online/bundle/support.sha256").read_text().strip()
if hashlib.sha256(args.support.read_bytes()).hexdigest() != expected:
    parser.error("Incorrect public support archive")
if os.path.lexists(args.output):
    parser.error("Choose a new output filename")
go = shutil.which(args.go)
if not go:
    parser.error("Go is not available")
with tempfile.TemporaryDirectory(dir=args.output.resolve().parent) as tmp:
    root = Path(tmp) / "src"
    shutil.copytree(BACKEND, root, ignore=shutil.ignore_patterns("*.zip", "*.exe"))
    shutil.copyfile(args.support, root / "online/bundle/Pixel2-Mali-Support.zip")
    target = Path(tmp) / "Pixel2-Setup.exe"
    env = dict(os.environ,GOOS="windows",GOARCH="amd64",CGO_ENABLED="0",GOWORK="off",GOPROXY="off")
    subprocess.run([go,"build","-trimpath","-buildvcs=false","-ldflags=-s -w -buildid=",
                    "-o",str(target),"./cmd/setup"],cwd=root,env=env,check=True)
    os.link(target,args.output)
print(hashlib.sha256(args.output.read_bytes()).hexdigest(),args.output.name)
