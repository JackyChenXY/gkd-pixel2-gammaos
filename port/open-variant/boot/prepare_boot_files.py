#!/usr/bin/env python3
"""Prepare files for the standard U-Boot FAT boot partition."""
import argparse
import gzip
import io
from pathlib import Path
import shutil
import struct
import subprocess
import zlib


MIB = 1024 * 1024
BOOT_SOURCE = Path(__file__).with_name("boot.cmd")


def payload(path, image_type, compression):
    with path.open("rb") as source:
        data = source.read(64 * MIB + 1)
    if not 64 <= len(data) <= 64 * MIB:
        raise ValueError(f"Unexpected U-Boot image size: {path.name}")
    magic, header_crc, _, size, _, _, checksum, os_id, arch, kind, compress, _ = struct.unpack_from(
        ">7I4B32s", data
    )
    header = data[:4] + bytes(4) + data[8:64]
    body = data[64:]
    if (magic, size, os_id, arch, kind, compress) != (
        0x27051956, len(body), 5, 22, image_type, compression
    ) or zlib.crc32(header) != header_crc or zlib.crc32(body) != checksum:
        raise ValueError(f"Unexpected U-Boot header or CRC: {path.name}")
    return body


def prepare(kernel, dtb, ramdisk, output):
    if not all(item.is_file() for item in (kernel, dtb, ramdisk)):
        raise ValueError("The kernel, board DTB and ramdisk must be regular input files.")
    with kernel.open("rb") as stream:
        stream.seek(56)
        if stream.read(4) != b"ARMd" or kernel.stat().st_size > 64 * MIB:
            raise ValueError("Expected an uncompressed AArch64 Image of at most 64 MiB.")
    controller = subprocess.check_output(["fdtget", "-t", "s", dtb, "/aliases", "mmc0"], text=True).strip()
    if controller != "/dwmmc@ff370000":
        raise ValueError("The board DTB does not retain the Pixel 2 boot SD controller.")
    compressed = payload(ramdisk, image_type=3, compression=1)
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
        archive = stream.read(64 * MIB + 1)
    if len(archive) > 64 * MIB or not archive.startswith(b"070701") or b"p2-init\0" not in archive:
        raise ValueError("The ramdisk does not contain the expected Android diagnostic init.")

    output.mkdir()
    try:
        shutil.copyfile(kernel, output / "Image")
        shutil.copyfile(dtb, output / "pixel2.dtb")
        (output / "initramfs.cpio.gz").write_bytes(compressed)
        script = output / "boot.scr"
        subprocess.run(
            ["mkimage", "-A", "arm64", "-O", "linux", "-T", "script", "-C", "none",
             "-n", "Pixel 2 GammaOS open boot", "-d", BOOT_SOURCE, script],
            check=True,
        )
        source = BOOT_SOURCE.read_bytes()
        if payload(script, image_type=6, compression=0) != struct.pack(">II", len(source), 0) + source:
            raise ValueError("mkimage did not emit the expected standard U-Boot script.")
    except BaseException:
        shutil.rmtree(output)
        raise
    print(f"Prepared the standard U-Boot files in {output}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("kernel", "dtb", "ramdisk", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    try:
        prepare(args.kernel, args.dtb, args.ramdisk, args.output)
    except (OSError, ValueError, EOFError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"{parser.prog}: {error}\n")


if __name__ == "__main__":
    main()
