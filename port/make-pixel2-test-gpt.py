#!/usr/bin/env python3
"""Create GPT metadata for a Pixel 2 SD card, leaving the first 16 MiB for U-Boot."""

import json
import math
import pathlib
import struct
import sys
import uuid
import zlib

SECTOR = 512
MIB = 1024 * 1024
ALIGN_SECTORS = MIB // SECTOR
ENTRY_COUNT = 128
ENTRY_SIZE = 128
ENTRY_BYTES = ENTRY_COUNT * ENTRY_SIZE
ENTRY_SECTORS = ENTRY_BYTES // SECTOR
GPT_HEADER_SIZE = 92
GPT_BASIC_DATA = uuid.UUID("EBD0A0A2-B9E5-4433-87C0-68B6B72699C7")
GPT_LINUX_DATA = uuid.UUID("0FC63DAF-8483-4772-8E79-3D69D8477DE4")
GPT_LINUX_RESERVED = uuid.UUID("8DA63339-0007-60C0-C436-083AC8230908")


def crc32(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


def align_up(value: int, alignment: int) -> int:
    return (value + alignment - 1) // alignment * alignment


def make_header(
    current_lba: int,
    backup_lba: int,
    first_usable: int,
    last_usable: int,
    disk_guid: uuid.UUID,
    entries_lba: int,
    entries_crc: int,
) -> bytes:
    header = bytearray(SECTOR)
    struct.pack_into(
        "<8sIIIIQQQQ16sQIII",
        header,
        0,
        b"EFI PART",
        0x00010000,
        GPT_HEADER_SIZE,
        0,
        0,
        current_lba,
        backup_lba,
        first_usable,
        last_usable,
        disk_guid.bytes_le,
        entries_lba,
        ENTRY_COUNT,
        ENTRY_SIZE,
        entries_crc,
    )
    struct.pack_into("<I", header, 16, crc32(header[:GPT_HEADER_SIZE]))
    return bytes(header)


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: make-pixel2-test-gpt.py DISK_BYTES OUTPUT_DIRECTORY")

    disk_bytes = int(sys.argv[1])
    output = pathlib.Path(sys.argv[2])
    if disk_bytes % SECTOR:
        raise SystemExit("disk size must be a multiple of 512 bytes")
    output.mkdir(parents=True, exist_ok=True)

    total_sectors = disk_bytes // SECTOR
    first_usable = 2 + ENTRY_SECTORS
    last_usable = total_sectors - ENTRY_SECTORS - 2
    disk_guid = uuid.uuid4()

    # The first partition starts exactly where the stock card's FAT partition
    # starts. Keep the original Rockchip loader sectors before it intact.
    fixed_partitions = [
        ("bootfiles", 128, GPT_BASIC_DATA),
        ("security", 4, GPT_LINUX_DATA),
        ("uboot", 4, GPT_LINUX_DATA),
        ("trust", 4, GPT_LINUX_DATA),
        ("misc", 4, GPT_LINUX_DATA),
        ("dtbo", 4, GPT_LINUX_DATA),
        ("vbmeta", 1, GPT_LINUX_DATA),
        ("boot", 40, GPT_LINUX_DATA),
        ("recovery", 108, GPT_LINUX_DATA),
        ("backup", 372, GPT_LINUX_RESERVED),
        ("cache", 384, GPT_LINUX_DATA),
        ("metadata", 16, GPT_LINUX_DATA),
        ("baseparameter", 1, GPT_LINUX_DATA),
        ("super", 2400, GPT_LINUX_DATA),
    ]

    entries = bytearray(ENTRY_BYTES)
    layout = []
    cursor = 32768
    for number, (name, size_mib, type_guid) in enumerate(fixed_partitions, 1):
        if number > 1:
            cursor = align_up(cursor, ALIGN_SECTORS)
        start_lba = cursor
        size_sectors = size_mib * ALIGN_SECTORS
        end_lba = start_lba + size_sectors - 1
        partition_guid = uuid.uuid4()
        name_bytes = name.encode("utf-16le")
        if len(name_bytes) > 72:
            raise SystemExit(f"GPT partition name too long: {name}")
        entry = struct.pack(
            "<16s16sQQQ72s",
            type_guid.bytes_le,
            partition_guid.bytes_le,
            start_lba,
            end_lba,
            0,
            name_bytes.ljust(72, b"\0"),
        )
        offset = (number - 1) * ENTRY_SIZE
        entries[offset : offset + ENTRY_SIZE] = entry
        layout.append(
            {
                "number": number,
                "name": name,
                "start_lba": start_lba,
                "end_lba": end_lba,
                "size_sectors": size_sectors,
                "start_bytes": start_lba * SECTOR,
                "size_bytes": size_sectors * SECTOR,
            }
        )
        cursor = end_lba + 1

    userdata_number = len(fixed_partitions) + 1
    userdata_start = align_up(cursor, ALIGN_SECTORS)
    if userdata_start > last_usable:
        raise SystemExit("card is too small for the Pixel 2 Android partition layout")
    userdata_end = last_usable
    userdata_size = userdata_end - userdata_start + 1
    userdata_guid = uuid.uuid4()
    userdata_name = "userdata"
    userdata_entry = struct.pack(
        "<16s16sQQQ72s",
        GPT_LINUX_DATA.bytes_le,
        userdata_guid.bytes_le,
        userdata_start,
        userdata_end,
        0,
        userdata_name.encode("utf-16le").ljust(72, b"\0"),
    )
    offset = (userdata_number - 1) * ENTRY_SIZE
    entries[offset : offset + ENTRY_SIZE] = userdata_entry
    layout.append(
        {
            "number": userdata_number,
            "name": userdata_name,
            "start_lba": userdata_start,
            "end_lba": userdata_end,
            "size_sectors": userdata_size,
            "start_bytes": userdata_start * SECTOR,
            "size_bytes": userdata_size * SECTOR,
        }
    )

    entries_crc = crc32(entries)
    primary_header = make_header(
        1, total_sectors - 1, first_usable, last_usable,
        disk_guid, 2, entries_crc,
    )
    backup_header = make_header(
        total_sectors - 1, 1, first_usable, last_usable,
        disk_guid, total_sectors - ENTRY_SECTORS - 1, entries_crc,
    )

    mbr = bytearray(SECTOR)
    mbr[446:462] = struct.pack(
        "<B3sB3sII", 0, b"\x00\x02\x00", 0xEE, b"\xff\xff\xff",
        1, min(total_sectors - 1, 0xFFFFFFFF),
    )
    mbr[510:512] = b"\x55\xaa"

    (output / "gpt-primary.bin").write_bytes(mbr + primary_header + entries)
    (output / "gpt-backup.bin").write_bytes(entries + backup_header)
    (output / "partition-layout.json").write_text(
        json.dumps(
            {
                "disk_bytes": disk_bytes,
                "sector_size": SECTOR,
                "total_sectors": total_sectors,
                "disk_guid": str(disk_guid),
                "first_partition_start_lba": 32768,
                "partitions": layout,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"disk: {disk_bytes} bytes, {total_sectors} sectors")
    print(f"GPT primary: {(output / 'gpt-primary.bin').stat().st_size} bytes")
    print(f"GPT backup: {(output / 'gpt-backup.bin').stat().st_size} bytes")
    for part in layout:
        print(
            f"p{part['number']:02} {part['name']:<13} "
            f"start={part['start_lba']} size={part['size_sectors']} sectors "
            f"({part['size_bytes'] / MIB:.1f} MiB)"
        )


if __name__ == "__main__":
    main()
