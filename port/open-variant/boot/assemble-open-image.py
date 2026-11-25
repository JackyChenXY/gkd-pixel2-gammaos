#!/usr/bin/env python3
"""Assemble an offline test card using the open Pixel 2 boot chain."""
import argparse
import gzip
import importlib.util
import io
import os
from pathlib import Path
import struct
import subprocess

from prepare_boot_files import BOOT_SOURCE, payload


PORT = Path(__file__).resolve().parents[2]
LBA = 512
PREFIX_START = 64 * LBA
MIB = 1024 * 1024
PREFIX_END = 16 * MIB
BOOT_FILES = ("boot.scr", "Image", "pixel2.dtb", "initramfs.cpio.gz")


def load_disk_assembler():
    spec = importlib.util.spec_from_file_location("pixel2_disk", PORT / "make-pixel2-card-image.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_inputs(args, disk, guid):
    prefix = disk.bounded_input(args.prefix, PREFIX_END - PREFIX_START)
    uboot_offset = 8 * MIB - PREFIX_START
    trust_offset = 12 * MIB - PREFIX_START
    if (len(prefix) != PREFIX_END - PREFIX_START or not any(prefix[:LBA])
            or prefix[uboot_offset:uboot_offset + 8] != b"LOADER  "
            or prefix[trust_offset:trust_offset + 4] != b"BL3X"):
        raise ValueError("Expected the new boot prefix from build-open-boot.sh.")
    boot_files = [(args.boot_dir / name, name) for name in BOOT_FILES]
    for path, _ in boot_files:
        if not path.is_file():
            raise ValueError(f"Missing boot file: {path.name}")
    source = BOOT_SOURCE.read_bytes()
    if payload(args.boot_dir / "boot.scr", 6, 0) != struct.pack(">II", len(source), 0) + source:
        raise ValueError("Expected the standard boot.scr from prepare_boot_files.py.")
    kernel = disk.bounded_input(args.boot_dir / "Image", 64 * MIB)
    if kernel[56:60] != b"ARMd":
        raise ValueError("The boot kernel is not an uncompressed AArch64 Image.")
    dtb = args.boot_dir / "pixel2.dtb"
    mmc = subprocess.check_output(["fdtget", "-t", "s", dtb, "/aliases", "mmc0"], text=True).strip()
    if mmc != "/dwmmc@ff370000":
        raise ValueError("The supplied DTB does not describe the Pixel 2 boot SD controller.")
    ramdisk = disk.bounded_input(args.boot_dir / "initramfs.cpio.gz", 64 * MIB)
    with gzip.GzipFile(fileobj=io.BytesIO(ramdisk)) as stream:
        archive = stream.read(64 * MIB + 1)
    if (len(archive) > 64 * MIB or not archive.startswith(b"070701")
            or str(guid).encode() not in archive or guid.bytes_le not in archive):
        raise ValueError("Use the diagnostic ramdisk built for this exact GPT.")
    return prefix, boot_files, uboot_offset, trust_offset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("gpt-dir", "prefix", "boot-dir", "cache", "super", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    if os.path.lexists(args.output):
        parser.error("--output must be a new file.")
    try:
        disk = load_disk_assembler()
        layout = disk.read_layout(args.gpt_dir)
        _, guid, partitions, _, _ = layout
        prefix, boot_files, uboot_offset, trust_offset = read_inputs(args, disk, guid)
        firmware = (
            ("open Rockchip boot prefix", PREFIX_START, prefix),
            ("open U-Boot", partitions["uboot"][0], prefix[uboot_offset:trust_offset]),
            ("open trust", partitions["trust"][0], prefix[trust_offset:]),
        )
        disk.write_card_image(
            args, layout, lambda directory, size: disk.write_boot_volume(directory, size, boot_files),
            firmware
        )
    except (OSError, ValueError, KeyError, TypeError, EOFError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"{parser.prog}: {error}\n")
    print(f"Created {args.output} with the open boot chain. Android board images came from the inputs.")


if __name__ == "__main__":
    main()
