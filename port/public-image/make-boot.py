#!/usr/bin/env python3
"""Compile a portable, offline-first Pixel 2 init and make the standard U-Boot ramdisk."""
import argparse
import gzip
import importlib.util
import json
import struct
import subprocess
import tempfile
import uuid
import zlib
from pathlib import Path

here=Path(__file__).resolve().parent
port=here.parent
spec=importlib.util.spec_from_file_location("pixel2_ramdisk",port/"diagnostics/build-diagnostic-init.py")
ramdisk=importlib.util.module_from_spec(spec)
spec.loader.exec_module(ramdisk)
p=argparse.ArgumentParser(description=__doc__)
for name in ("gpt","musl-cc","kernel-headers","output"):
    p.add_argument("--"+name,type=Path,required=True)
mode=p.add_mutually_exclusive_group(required=True)
mode.add_argument("--base-ramdisk",type=Path,help="Base vendor ramdisk for a full U-Boot image")
mode.add_argument("--init-only",action="store_true",help="Output just the board-specific executable")
a=p.parse_args()
layout=json.loads((a.gpt/"partition-layout.json").read_text())
parts={part["name"]:part for part in layout["partitions"]}
guid=uuid.UUID(layout["disk_guid"])
primary=(a.gpt/"gpt-primary.bin").read_bytes()
table=primary[1024:1024+16384]
assert len(table)==16384 and zlib.crc32(table)==struct.unpack_from("<I",primary,512+88)[0]
assert a.output.parent.is_dir()
with tempfile.TemporaryDirectory(dir=a.output.parent) as temporary:
    work=Path(temporary)
    h=["#define EXPECTED_DISK_BYTES %dULL"%layout["disk_bytes"],
       "#define EXPECTED_P1_START %dULL"%parts["bootfiles"]["start_lba"],
       "#define EXPECTED_P1_SECTORS %dULL"%parts["bootfiles"]["size_sectors"],
       "#define EXPECTED_METADATA_PARTITION %d"%parts["metadata"]["number"],
       "#define EXPECTED_USERDATA_PARTITION %d"%parts["userdata"]["number"],
       '#define EXPECTED_GUID_TEXT "%s"'%guid,
       'static const char public_image_guid[] __attribute__((used))=EXPECTED_GUID_TEXT;',
       "static const unsigned char expected_disk_guid[16]={%s};"%",".join(map(str,guid.bytes_le)),
       "#define PIXEL2_GPT_CRC %dU"%zlib.crc32(table)]
    (work/"diagnostic_expect.h").write_text("\n".join(h)+"\n")
    binary=work/"p2-init"
    subprocess.run([a.musl_cc,"-std=gnu11","-Os","-static","-s","-Wall","-Wextra","-Werror",
                    "-I",work,"-idirafter",a.kernel_headers,"-DPIXEL2_ANDROID_BOOT","-DPIXEL2_CAPTURE_DISPLAY",
                    "-DPIXEL2_REINITIALIZE_PANEL","-DPIXEL2_POINTER","-DPIXEL2_PUBLIC_CARD",
                    port/"diagnostics/pixel2-init.c",port/"diagnostics/pixel2-pointer.c",here/"grow-card.c","-o",binary],check=True)
    elf=binary.read_bytes()
    assert elf[:5]==b"\x7fELF\x02" and struct.unpack_from("<H",elf,18)[0]==183
    assert guid.bytes_le in elf and str(guid).encode() in elf
    if a.init_only:
        with a.output.open("xb") as out:
            out.write(elf)
        raise SystemExit(0)
    base=work/"base.uimg"
    base.write_bytes(ramdisk.legacy_ramdisk(gzip.decompress(a.base_ramdisk.read_bytes()),b"Pixel 2 board ramdisk"))
    archive=ramdisk.append_android_probe(elf,base,standalone=True)
    with a.output.open("xb") as f:
        f.write(ramdisk.legacy_ramdisk(archive,b"Pixel 2 community RAM disk"))
