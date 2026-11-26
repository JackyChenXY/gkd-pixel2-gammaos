#!/usr/bin/env python3
"""Build the reserved-slot distribution from a verified v0.3.1 raw card file."""
import argparse
import gzip
import hashlib
import json
import os
import shutil
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import uuid

import assemble
from slot_layout import DISK_GUID, FACTORY_LAST, SECTOR, reserve

HERE = Path(__file__).resolve().parent
SIZE = (FACTORY_LAST + 1) * SECTOR
BOOT = 16 << 20
BOOT_SIZE = 128 << 20
SLOT = 641024 * SECTOR
BASE = {
    "95e6b744b9b3480b04bf0d54b58490829dcfd23209b21e02f61fa309d55fa556": "empty_hash",
    "0bd96facdf47b3670c5e362fe40456ba85976e72f8bc22ecbbd47355ecb05e17": "full_hash",
}
EPOCH = 946684800
RAMDISKS = ("initramfs.cpio.gz", "mali.gz")


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for data in iter(lambda: stream.read(4 << 20), b""):
            result.update(data)
    return result.hexdigest()


def build_init(directory, primary, args):
    directory.mkdir()
    table = primary[2 * SECTOR:]
    partitions = []
    for i in range(128):
        entry = table[i * 128:(i + 1) * 128]
        if not any(entry[:16]):
            continue
        first, last = struct.unpack_from("<QQ", entry, 32)
        partitions.append({"number": i + 1, "name": entry[56:].decode("utf-16le").rstrip("\0"),
                           "start_lba": first, "size_sectors": last - first + 1})
    layout = {"disk_bytes": SIZE, "disk_guid": str(uuid.UUID(bytes_le=DISK_GUID)), "partitions": partitions}
    (directory / "partition-layout.json").write_text(json.dumps(layout), encoding="utf-8")
    (directory / "gpt-primary.bin").write_bytes(primary)
    executable = directory / "p2-init"
    subprocess.run([sys.executable, HERE.parent / "public-image/make-boot.py",
                    "--gpt", directory, "--musl-cc", args.musl_cc, "--kernel-headers", args.kernel_headers,
                    "--init-only", "--output", executable], check=True)
    return executable.read_bytes()


def replace_init(compressed, before, after):
    if len(before) != len(after) or before == after:
        raise ValueError("Unexpected size or contents of the rebuilt init")
    archive = bytearray(gzip.decompress(compressed))
    position = 0
    found = 0
    while archive[position:position + 6] == b"070701":
        namesize = int(archive[position + 94:position + 102], 16)
        length = int(archive[position + 54:position + 62], 16)
        name_end = position + 110 + namesize
        start = (name_end + 3) & ~3
        end = start + length
        if namesize < 1 or name_end > len(archive) or archive[name_end - 1] != 0 or end > len(archive):
            raise ValueError("Invalid initramfs entry bounds")
        if archive[position + 110:name_end - 1] == b"p2-init":
            if archive[start:end] != before:
                raise ValueError("The old init must rebuild byte for byte with this toolchain")
            archive[start:end] = after
            found += 1
        position = (end + 3) & ~3
    if found != 1 or any(archive[position:]):
        raise ValueError("Unexpected Android ramdisk layout")
    return gzip.compress(bytes(archive), mtime=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("base", "system", "musl-cc", "kernel-headers", "output"):
        parser.add_argument("--" + arg, required=True, type=Path)
    args = parser.parse_args()
    if not args.base.is_file() or args.base.stat().st_size != SIZE or os.path.lexists(args.output):
        parser.error("Use a regular v0.3.1 image and a new output filename")
    args.musl_cc = args.musl_cc.resolve()
    args.kernel_headers = args.kernel_headers.resolve()
    if not args.system.is_file() or args.system.stat().st_size != 1879048192:
        parser.error("Use the signed 0.3.2 Android system image from cold-system.py")
    marker = subprocess.check_output(["debugfs", "-R", "cat /system/etc/pixel2-release", args.system],
                                     stderr=subprocess.DEVNULL)
    if marker != b"GKD Pixel 2 community TF image 0.3.2\n":
        parser.error("Wrong Android system release")
    system_hash = digest(args.system)
    profile = json.loads((HERE / "backend/profile/profile.json").read_text())
    env = dict(os.environ, TZ="UTC", SOURCE_DATE_EPOCH=str(EPOCH))
    with tempfile.TemporaryDirectory(dir=args.output.resolve().parent) as tmp:
        tmp = Path(tmp)
        image = tmp / "card.img"
        # Own and verify the private copy before modifying any bytes.
        subprocess.run(["cp", "--reflink=auto", "--sparse=always", "--", args.base, image], check=True)
        kind = BASE.get(digest(image))
        if kind is None:
            raise ValueError("Unknown v0.3.1 image")
        with image.open("r+b") as card:
            primary = card.read(34 * SECTOR)
            card.seek(-33 * SECTOR, 2)
            backup = card.read()
            new_primary, new_backup = reserve(primary, backup, SIZE)
            old_init = build_init(tmp / "original", primary, args)
            new_init = build_init(tmp / "reserved", new_primary, args)
            card.seek(BOOT)
            boot = tmp / "boot.fat"
            boot.write_bytes(card.read(BOOT_SIZE))
            for name in RAMDISKS:
                src, dst, check = (tmp / (prefix + name) for prefix in ("src-", "new-", "check-"))
                subprocess.run(["mcopy", "-i", boot, "::/" + name, src], env=env, check=True)
                dst.write_bytes(replace_init(src.read_bytes(), old_init, new_init))
                os.utime(dst, (EPOCH, EPOCH))
                subprocess.run(["mcopy", "-o", "-m", "-i", boot, dst, "::/" + name], env=env, check=True)
                subprocess.run(["mcopy", "-i", boot, "::/" + name, check], env=env, check=True)
                if dst.read_bytes() != check.read_bytes():
                    raise OSError("Failed boot file readback: " + name)
            partitions = assemble.parts(card)
            super_start = partitions["super"][0]
            system_offset, system_size = assemble.extent(card, super_start, 0, "system")
            if (system_offset, system_size) != assemble.extent(card, super_start, 1, "system") or system_size != args.system.stat().st_size:
                raise ValueError("Unexpected system extent in super")
            if assemble.digest(card, system_offset, system_size) != "e92d3c5fb8f086f89ff18238cc368828b68e40c5cebe15a14c9ddfeb65525308":
                raise ValueError("Unexpected v0.3.1 system partition")
            card.seek(system_offset)
            with args.system.open("rb") as source:
                shutil.copyfileobj(source, card, length=4 << 20)
            card.flush()
            if assemble.digest(card, system_offset, system_size) != system_hash:
                raise OSError("Signed system readback differs")
            card.seek(0)
            card.write(new_primary)
            card.seek(BOOT)
            card.write(boot.read_bytes())
            card.seek(-len(new_backup), 2)
            card.write(new_backup)
            card.flush()
            os.fsync(card.fileno())
            card.seek(SLOT)
            if hashlib.sha256(card.read(128 << 20)).hexdigest() != profile[kind]:
                raise ValueError("Driver slot checksum changed")
        result = subprocess.check_output(["sgdisk", "-v", image], text=True, env=dict(env, LC_ALL="C"))
        if "No problems found" not in result:
            raise ValueError("Invalid output GPT: " + result)
        checksum = digest(image)
        os.link(image, args.output)
        print(checksum, args.output.name, flush=True)


if __name__ == "__main__":
    main()
