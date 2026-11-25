#!/usr/bin/env python3
"""Assemble a standalone Pixel 2 GammaOS card image without opening a device."""

from contextlib import contextmanager, suppress
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import struct
import subprocess
import tempfile
import uuid
import zlib


SECTOR = 512
MIB = 1024 * 1024
BOOT_OFFSET = 16 * MIB
ENTRY_BYTES = 128 * 128
PRIMARY_SIZE = 2 * SECTOR + ENTRY_BYTES
BACKUP_SIZE = ENTRY_BYTES + SECTOR
BASIC_DATA = uuid.UUID("EBD0A0A2-B9E5-4433-87C0-68B6B72699C7").bytes_le
LINUX_DATA = uuid.UUID("0FC63DAF-8483-4772-8E79-3D69D8477DE4").bytes_le
# The physical reference and make-pixel2-test-gpt.py use this exact layout.
PARTITION_SIZES = (
    ("bootfiles", 128), ("security", 4), ("uboot", 4), ("trust", 4),
    ("misc", 4), ("dtbo", 4), ("vbmeta", 1), ("boot", 40),
    ("recovery", 108), ("backup", 372), ("cache", 384), ("metadata", 16),
    ("baseparameter", 1), ("super", 2400),
)


@contextmanager
def regular_input(path):
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError(f"Input must be a regular file: {path}")
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError(f"Input must be a regular file: {path}")
        yield stream


def bounded_input(path, limit):
    with regular_input(path) as stream:
        value = stream.read(limit + 1)
    if not value or len(value) > limit:
        raise ValueError(f"Input size out of range: {path}")
    return value


def gpt_header(header, current, alternate, last, entries_lba, disk_guid, entries):
    values = struct.unpack_from("<8sIIIIQQQQ16sQIII", header)
    signature, version, size, checksum, reserved, *geometry = values
    if signature != b"EFI PART" or version != 0x10000 or size != 92 or reserved != 0:
        raise ValueError("Invalid GPT header")
    payload = bytearray(header[:size])
    struct.pack_into("<I", payload, 16, 0)
    if zlib.crc32(payload) != checksum:
        raise ValueError("GPT header checksum mismatch")
    expected = [current, alternate, 34, last, disk_guid.bytes_le, entries_lba,
                128, 128, zlib.crc32(entries)]
    if geometry != expected:
        raise ValueError("GPT header differs from the declared disk geometry")


def read_layout(directory):
    layout = json.loads(bounded_input(directory / "partition-layout.json", 64 * 1024))
    disk_size = layout["disk_bytes"]
    if type(disk_size) is not int or disk_size <= 0 or disk_size % SECTOR:
        raise ValueError("Layout disk size must be a positive multiple of 512")
    total_sectors = disk_size // SECTOR
    if (layout["sector_size"], layout["total_sectors"], layout["first_partition_start_lba"]) != (
        SECTOR, total_sectors, BOOT_OFFSET // SECTOR
    ):
        raise ValueError("Layout header geometry is invalid")
    disk_guid = uuid.UUID(layout["disk_guid"])
    if disk_guid.int == 0 or len(layout["partitions"]) != len(PARTITION_SIZES) + 1:
        raise ValueError("Unexpected Pixel 2 GPT layout")
    primary = bounded_input(directory / "gpt-primary.bin", PRIMARY_SIZE)
    backup = bounded_input(directory / "gpt-backup.bin", BACKUP_SIZE)
    if len(primary) != PRIMARY_SIZE or len(backup) != BACKUP_SIZE:
        raise ValueError("GPT files have the wrong length")
    if (primary[510:512] != b"\x55\xaa" or primary[450] != 0xEE
            or struct.unpack_from("<II", primary, 454) != (1, min(total_sectors - 1, 0xFFFFFFFF))):
        raise ValueError("Protective MBR is invalid")
    entries = primary[2 * SECTOR:]
    if entries != backup[:ENTRY_BYTES]:
        raise ValueError("Primary and backup GPT entries differ")
    last_usable = total_sectors - 34
    gpt_header(primary[SECTOR:2 * SECTOR], 1, total_sectors - 1, last_usable, 2, disk_guid, entries)
    gpt_header(backup[ENTRY_BYTES:], total_sectors - 1, 1, last_usable,
               total_sectors - 33, disk_guid, entries)

    start = BOOT_OFFSET // SECTOR
    partitions = {}
    guids = {disk_guid.bytes_le, b"\0" * 16}
    for index, (name, size_mib) in enumerate((*PARTITION_SIZES, ("userdata", None)), 1):
        sectors = size_mib * MIB // SECTOR if size_mib is not None else last_usable - start + 1
        end = start + sectors - 1
        expected_fields = {
            "number": index, "name": name, "start_lba": start, "end_lba": end,
            "start_bytes": start * SECTOR, "size_sectors": sectors, "size_bytes": sectors * SECTOR,
        }
        type_guid, part_guid, found_start, found_end, flags, encoded_name = struct.unpack_from(
            "<16s16sQQQ72s", entries, (index - 1) * 128
        )
        if (layout["partitions"][index - 1] != expected_fields or end > last_usable
                or sectors < MIB // SECTOR or (found_start, found_end, flags) != (start, end, 0)
                or part_guid in guids or type_guid != (BASIC_DATA if index == 1 else LINUX_DATA)
                or encoded_name != name.encode("utf-16le").ljust(72, b"\0")):
            raise ValueError(f"Unexpected GPT entry or layout geometry for {name}")
        guids.add(part_guid)
        partitions[name] = (start * SECTOR, sectors * SECTOR)
        start = end + 1
    if any(entries[len(partitions) * 128:]):
        raise ValueError("GPT contains extra partition entries")
    return disk_size, disk_guid, partitions, primary, backup


def probe_image(path, max_size, signatures, *, exact=False):
    with regular_input(path) as stream:
        size = os.fstat(stream.fileno()).st_size
        if not size or size > max_size or (exact and size != max_size):
            raise ValueError(f"Unexpected raw image size: {path.name}")
        for offset, signature in signatures:
            stream.seek(offset)
            if stream.read(len(signature)) != signature:
                raise ValueError(f"Unexpected signature in {path.name} at byte {offset}; check image format")
    return size


def checked_run(*args):
    subprocess.run(args, check=True)


def write_boot_volume(directory, size, copies):
    fat = directory / "boot-fat.img"
    with fat.open("xb") as stream:
        stream.truncate(size)
    checked_run("mkfs.fat", "-F", "32", "-S", "512", "-s", "2",
                "-h", str(BOOT_OFFSET // SECTOR), "-n", "PIXEL2BOOT", fat)
    for path, target in copies:
        checked_run("mcopy", "-i", fat, path, f"::/{target}")
    readback = directory / "fat-readback"
    for path, target in copies:
        checked_run("mcopy", "-i", fat, f"::/{target}", readback)
        if readback.read_bytes() != path.read_bytes():
            raise ValueError(f"FAT file readback failed: {target}")
        readback.unlink()
    return fat


def hash_range(stream, offset, size):
    stream.seek(offset)
    checksum = hashlib.sha256()
    remaining = size
    while remaining:
        chunk = stream.read(min(remaining, MIB))
        if not chunk:
            raise ValueError("Short read during image verification")
        checksum.update(chunk)
        remaining -= len(chunk)
    return checksum.digest()


def write_region(output, name, start, source, size):
    checksum = hashlib.sha256()
    zeroes = bytes(MIB)
    for offset in range(0, size, MIB):
        chunk = source.read(min(size - offset, MIB))
        if len(chunk) != min(size - offset, MIB):
            raise ValueError(f"Short read while copying {name}")
        checksum.update(chunk)
        if chunk != zeroes[:len(chunk)]:
            output.seek(start + offset)
            output.write(chunk)
    if hash_range(output, start, size) != checksum.digest():
        raise ValueError(f"SHA-256 readback mismatch: {name}")
    print(f"Verified {name} ({size} bytes)", flush=True)


def write_card_image(args, layout, build_boot_volume, firmware):
    size, _, partitions, primary, backup = layout
    board_images = {
        "cache": (args.cache, [(1080, b"\x53\xef")], True),
        "super": (args.super, [(4096, b"gDla"), (8192, b"gDla")], True),
    }
    image_sizes = {
        name: probe_image(path, partitions[name][1], signatures, exact=exact)
        for name, (path, signatures, exact) in board_images.items()
    }
    with tempfile.TemporaryDirectory(prefix=".pixel2-build-", dir=args.output.parent) as temporary:
        directory = Path(temporary)
        fat = build_boot_volume(directory, partitions["bootfiles"][1])
        metadata = directory / "metadata.img"
        with metadata.open("xb") as image:
            image.truncate(partitions["metadata"][1])
        checked_run("mkfs.ext4", "-F", "-q", metadata)
        probe_image(metadata, partitions["metadata"][1], [(1080, b"\x53\xef")], exact=True)

        # Exclusive creation prevents opening an existing file or device.
        with args.output.open("x+b") as output:
            identity = os.fstat(output.fileno())
            try:
                output.truncate(size)
                for name, start, payload in (
                    ("primary GPT", 0, primary),
                    ("backup GPT", size - BACKUP_SIZE, backup),
                    *firmware,
                ):
                    write_region(output, name, start, io.BytesIO(payload), len(payload))
                images = {name: path for name, (path, _, _) in board_images.items()}
                images.update({"bootfiles": fat, "metadata": metadata})
                for name, path in images.items():
                    length = image_sizes[name] if name in image_sizes else partitions[name][1]
                    with regular_input(path) as source:
                        write_region(output, name, partitions[name][0], source, length)
                start, _ = partitions["userdata"]
                output.seek(start)
                if output.read(MIB) != bytes(MIB):
                    raise ValueError("New image userdata header is not blank")
                output.flush()
                os.fsync(output.fileno())
                if os.fstat(output.fileno()).st_size != size:
                    raise ValueError("The final image has the wrong disk size")
            except BaseException:
                # Clean up only the file this process created, if still in place.
                with suppress(FileNotFoundError):
                    if os.path.samestat(identity, args.output.lstat()):
                        args.output.unlink()
                raise
