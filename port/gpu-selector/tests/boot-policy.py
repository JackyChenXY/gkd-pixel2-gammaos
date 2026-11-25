#!/usr/bin/env python3
"""Exercise the shipping Hush script with file-backed MMC commands. No card devices."""
import argparse,os,struct,subprocess,sys,tempfile
from pathlib import Path
SECTOR=319504*512
script=Path(__file__).resolve().parents[1]/"boot.cmd"
def block(s):
    return struct.pack("<4sIII",b"P2G2",0x30201,s,s^0xffffffff).ljust(512,b"\0")
shim=r'''
devtype=mmc; devnum=0; distro_bootpart=1
setenv(){ local key=$1; shift; printf -v "$key" '%s' "$*"; }
function test { if [[ "$1" == -e && "$2" == mmc ]]; then [[ "$forced" == 1 ]]; else builtin test "$@"; fi; }
part(){ if [[ "$4" != misc ]]; then return 1; fi; if [[ "$1" == start ]]; then setenv "$5" "$geometry"; else setenv "$5" 2000; fi; }
mmc(){
  case $1 in dev) return 0;;
    read) [[ $3 == 4e010 && $4 == 1 ]] || return 1; dd if="$disk" of="$temp/$2" bs=512 skip=319504 count=1 status=none;;
    write) [[ $3 == 4e010 && $4 == 1 && "$writeok" == 1 ]] || return 1; dd if="$temp/$2" of="$disk" bs=512 seek=319504 count=1 conv=notrunc,fsync status=none;;
  esac
}
function itest.l {
  local val=$1 a
  if [[ "$val" == \** ]]; then a=$((16#\${val:1} - 16#01800000)); val=$(od -An -tx4 -j "$a" -N4 "$temp/01800000" | tr -d ' '); fi
  ((16#$val == 16#$3))
}
function mw.l {
  python3 -c 'import sys,struct;f=open(sys.argv[1],"r+b");f.seek(int(sys.argv[2],16)-0x1800000);f.write(struct.pack("<I",int(sys.argv[3],16)))' "$temp/01800000" "$1" "$2"
}
function cmp.b { [[ "$3" == 200 ]] && cmp -s "$temp/$1" "$temp/$2"; }
load(){ if [[ "$4" == /mali.img && "$filesok" == 0 ]]; then return 1; fi; filesize=1400; return 0; }
booti(){ echo "MODE \${bootargs##*androidboot.pixel2gpu=}"; exit 0; }
source "$bootcmd"
'''.replace(r"\$", "$")
def select(disk,forced=False,write=True,files=True,geometry="4e000"):
    disk=Path(disk)
    if not disk.is_file() or disk.is_symlink():raise ValueError("Regular virtual image only")
    with tempfile.TemporaryDirectory() as tmp:
        env=dict(os.environ,disk=str(disk),temp=tmp,bootcmd=str(script),forced=str(int(forced)),writeok=str(int(write)),filesok=str(int(files)),geometry=geometry)
        result=subprocess.check_output(["bash","-c",shim],env=env,text=True)
        return next(s[5:] for s in result.splitlines() if s.startswith("MODE "))
def test():
    with tempfile.TemporaryDirectory() as d:
        img=Path(d)/"virtual";img.touch()
        cases=[(0x20,"mesa",0x20,{}),(0x21,"mesa",0x21,{}),(0x22,"trial",0x24,{}),(0x23,"kept",0x25,{}),
               (0x24,"mesa",0x24,{}),(0x25,"mesa",0x25,{}),(0x22,"forced",0x22,dict(forced=True)),
               (0x22,"mesa",0x22,dict(write=False)),(0x23,"mesa",0x25,dict(files=False)),(0x22,"mesa",0x22,dict(geometry="4e001"))]
        for state,mode,nxt,flags in cases:
            with img.open("r+b") as f:f.seek(SECTOR);f.write(block(state))
            assert select(img,**flags)==mode,(state,mode,flags)
            with img.open("rb") as f:f.seek(SECTOR);assert f.read(512)==block(nxt)
        for pos in (0,4,12):
            s=bytearray(block(0x22));s[pos]^=1
            with img.open("r+b") as f:f.seek(SECTOR);f.write(s)
            assert select(img)=="mesa"
        print("13 boot-script cases passed")
if __name__=="__main__":
    if len(sys.argv)==2:print(select(sys.argv[1]))
    else:test()
