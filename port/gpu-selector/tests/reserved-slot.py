#!/usr/bin/env python3
"""Qualify the reserved GPU slot and first-boot expansion on regular card images."""
import argparse
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import uuid

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from slot_layout import DISK_GUID, FACTORY_LAST, LINUX_RESERVED, SECTOR, TYPE_OFFSET, reserve


def check(image):
    size = (FACTORY_LAST + 1) * SECTOR
    if not image.is_file() or image.stat().st_size != size:
        raise ValueError("Use the 7 GiB factory image")
    with image.open("rb") as stream:
        primary = stream.read(34 * SECTOR)
        stream.seek(-33 * SECTOR, 2)
        backup = stream.read()
    if (reserve(primary, backup, size) != (primary, backup) or
            primary[2 * SECTOR + TYPE_OFFSET:2 * SECTOR + TYPE_OFFSET + 16] != LINUX_RESERVED):
        raise ValueError("Mali slot could be exported by vold")
    for point in (SECTOR + 16, 2 * SECTOR + TYPE_OFFSET + 16, 2 * SECTOR + 14 * 128 + 40):
        corrupt = bytearray(primary)
        corrupt[point] ^= 1
        try:
            reserve(corrupt, backup, size)
        except ValueError:
            continue
        raise ValueError("Accepted an altered GPT copy")
    table = primary[2 * SECTOR:]
    userdata_start, = struct.unpack_from("<Q", table, 14 * 128 + 32)
    with tempfile.TemporaryDirectory() as temporary:
        gpt = Path(temporary)
        (gpt / "gpt-primary.bin").write_bytes(primary)
        (gpt / "gpt-backup.bin").write_bytes(backup)
        (gpt / "partition-layout.json").write_text(json.dumps({
            "disk_bytes": size, "disk_guid": str(uuid.UUID(bytes_le=DISK_GUID)),
            "partitions": [{"name": "userdata", "start_bytes": userdata_start * SECTOR}]
        }), encoding="utf-8")
        subprocess.run([sys.executable, HERE.parents[1] / "public-image/test-grow.py", gpt], check=True)
    print("Reserved driver slot, both GPTs and userdata expansion passed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    check(parser.parse_args().image)
