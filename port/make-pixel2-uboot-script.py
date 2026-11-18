#!/usr/bin/env python3
"""Wrap text as a SCRIPT image with this stock vendor's 0xffffffff sentinel."""

import hashlib
import pathlib
import struct
import sys
import zlib


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: make-pixel2-uboot-script.py SCRIPT_TEXT OUTPUT_IMAGE")
    source, target = map(pathlib.Path, sys.argv[1:])
    script = source.read_text(encoding="utf-8-sig").encode("utf-8")
    if not script or b"\0" in script:
        raise SystemExit("Expected a nonempty text script, not an existing image")
    # Vendor include/image.h defines IMAGE_PARAM_INVAL as 0xffffffff.
    # Vendor tools/mkimage.c writes it; the actual stock source parser scans for
    # that exact word (0x208fd4..0x208fe4), not the upstream zero terminator.
    # A single final component is copied with pad=0: no trailing four-byte pad.
    payload = struct.pack(">II", len(script), 0xFFFFFFFF) + script
    header = bytearray(64)
    struct.pack_into(
        ">7I4B32s", header, 0,
        0x27051956, 0, 0, len(payload), 0, 0,
        zlib.crc32(payload) & 0xFFFFFFFF,
        5, 22, 6, 0,  # Linux, ARM64, SCRIPT, no compression.
        b"GKD Pixel 2 Android boot".ljust(32, b"\0"),
    )
    struct.pack_into(">I", header, 4, zlib.crc32(header) & 0xFFFFFFFF)
    image = header + payload
    target.write_bytes(image)
    print(f"Created {target.name}: {len(image)} bytes; script {len(script)} bytes")
    print("SHA256 " + hashlib.sha256(image).hexdigest())


if __name__ == "__main__":
    main()
