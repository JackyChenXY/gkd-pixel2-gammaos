#!/usr/bin/env python3
"""Pack and verify a Pixel 2 direct-boot super from a raw GammaOS system.

The matching first-stage ramdisk must leave /product and /system_ext to the
links inside the GammaOS filesystem.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


SECTOR = 512
BLOCK_SIZE = 4096
ALIGNMENT = 1024 * 1024
SUPER_SIZE = 2_516_582_400
METADATA_SIZE = 65_536
METADATA_SLOTS = 2
GROUP_NAME = "rockchip_dynamic_partitions"
GROUP_SIZE = 2_512_388_096
RETAINED = ("vendor", "vendor_dlkm", "odm", "odm_dlkm")
EMBEDDED = ("product", "system_ext")
CHUNK_SIZE = 8 * 1024 * 1024

PARTITION_ENTRY = re.compile(
    r"^  Name: ([a-z_]+)\n"
    rf"  Group: {GROUP_NAME}\n"
    r"  Attributes: readonly\n"
    r"  Extents:\n"
    r"((?:    .+\n)+)",
    re.MULTILINE,
)
LINEAR_EXTENT = re.compile(r"    (\d+) \.\. (\d+) linear super (\d+)")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def tool_output(*command):
    return subprocess.check_output(command, text=True)


def read_layout(lpdump, image, expected_partitions):
    require(image.stat().st_size == SUPER_SIZE,
            f"{image} has the wrong raw super size")
    info = json.loads(tool_output(lpdump, "--json", image))
    devices = info["block_devices"]
    require(len(devices) == 1 and devices[0] == {
        "name": "super",
        "size": str(SUPER_SIZE),
        "block_size": str(BLOCK_SIZE),
        "alignment": str(ALIGNMENT),
    }, f"{image} has unexpected super geometry")
    require(info["groups"] == [
        {"name": "default"},
        {"name": GROUP_NAME, "maximum_size": str(GROUP_SIZE)},
    ], f"{image} has unexpected partition groups")
    sizes = {
        part["name"]: int(part["size"])
        for part in info["partitions"]
        if part["group_name"] == GROUP_NAME and part["is_dynamic"]
    }
    require(set(sizes) == set(expected_partitions)
            and len(sizes) == len(info["partitions"]),
            f"{image} has unexpected logical partitions: {sorted(sizes)}")

    layouts = []
    for slot in range(METADATA_SLOTS):
        dump = tool_output(lpdump, f"--slot={slot}", image)
        require("Metadata version: 10.0\n" in dump
                and f"Metadata max size: {METADATA_SIZE} bytes\n" in dump
                and f"Metadata slot count: {METADATA_SLOTS}\n" in dump
                and "Header flags: none\n" in dump,
                f"{image} slot {slot} has unexpected metadata")
        partition_table = dump.split("Super partition layout:\n", 1)[0]
        entries = PARTITION_ENTRY.findall(partition_table)
        require(len(entries) == len(sizes)
                and {name for name, _ in entries} == set(sizes),
                f"{image} slot {slot} has unexpected partition attributes")
        layout = {}
        occupied = []
        for name, extent_list in entries:
            offset = 0
            layout[name] = []
            for line in extent_list.splitlines():
                extent = LINEAR_EXTENT.fullmatch(line)
                require(extent is not None, f"{image} has a non-linear {name} extent")
                first, last, physical = map(int, extent.groups())
                require(first == offset and last >= first,
                        f"{image} has invalid logical sectors for {name}")
                start = physical * SECTOR
                length = (last - first + 1) * SECTOR
                require(start >= ALIGNMENT and start + length <= SUPER_SIZE
                        and start % BLOCK_SIZE == 0 and length % BLOCK_SIZE == 0,
                        f"{image} has an invalid super range for {name}")
                layout[name].append((start, length))
                occupied.append((start, start + length))
                offset = last + 1
            require(offset * SECTOR == sizes[name] and offset > 0,
                    f"{image} has inconsistent size for {name}")
        occupied.sort()
        require(all(left[1] <= right[0] for left, right in zip(occupied, occupied[1:])),
                f"{image} slot {slot} has overlapping partition extents")
        layouts.append(layout)
    require(layouts[0] == layouts[1], f"{image} metadata slots differ")
    return sizes, layouts[0]


def read_partition(source, extents, destination=None):
    digest = hashlib.sha256()
    for offset, length in extents:
        source.seek(offset)
        while length:
            block = source.read(min(length, CHUNK_SIZE))
            require(bool(block), "Unexpected end of input image")
            digest.update(block)
            if destination is not None:
                destination.write(block)
            length -= len(block)
    return digest.hexdigest()


def validate_system(image):
    size = image.stat().st_size
    require(image.is_file() and size > 0 and size % BLOCK_SIZE == 0,
            "GammaOS system must be a block-aligned raw image")
    with image.open("rb") as data:
        data.seek(1024 + 56)
        require(data.read(2) == b"\x53\xef", "GammaOS system must be raw ext4")
        checksum = read_partition(data, [(0, size)])
    for name in EMBEDDED:
        target = f"/system/{name}"
        link = tool_output("debugfs", "-R", f"stat /{name}", image)
        properties = tool_output("debugfs", "-R", f"stat {target}/etc/build.prop", image)
        require(f'Fast link dest: "{target}"' in link and "Type: regular" in properties,
                f"GammaOS system is missing its embedded {name} filesystem")
    return size, checksum


def pack(base, system, output, tools):
    require(base.is_file(), "Pixel 2 base super must be a regular image file")
    require(not output.exists() and not output.is_symlink(),
            f"Output already exists: {output}")
    lpmake = tools / "lpmake"
    lpdump = tools / "lpdump"
    require(os.access(lpmake, os.X_OK) and os.access(lpdump, os.X_OK),
            f"Android Linux host tools lpmake and lpdump are required in {tools}")

    original_sizes, original_layout = read_layout(
        lpdump, base, ("system", *RETAINED, *EMBEDDED))
    system_size, system_hash = validate_system(system)
    sizes = {"system": system_size, **{name: original_sizes[name] for name in RETAINED}}

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".gamma-super-", dir=output.parent) as temporary:
        staging = Path(temporary)
        images = {"system": system}
        expected_hashes = {"system": system_hash}
        with base.open("rb") as original:
            for name in RETAINED:
                images[name] = staging / f"{name}.img"
                with images[name].open("xb") as extracted:
                    expected_hashes[name] = read_partition(
                        original, original_layout[name], extracted)

        install_super(staging, output, lpmake, lpdump, images, expected_hashes, sizes)


def install_super(staging, output, lpmake, lpdump, images, expected_hashes, sizes):
    require(sum(sizes.values()) <= GROUP_SIZE, "Images exceed the Rockchip partition group size")
    packed = staging / "super.raw.img"
    command = [
        lpmake, f"--metadata-size={METADATA_SIZE}", f"--metadata-slots={METADATA_SLOTS}",
        f"--device-size={SUPER_SIZE}", f"--block-size={BLOCK_SIZE}",
        f"--alignment={ALIGNMENT}", f"--group={GROUP_NAME}:{GROUP_SIZE}",
        f"--output={packed}",
    ]
    for name, size in sizes.items():
        command.extend([
            f"--partition={name}:readonly:{size}:{GROUP_NAME}",
            f"--image={name}={images[name]}",
        ])
    subprocess.run(command, check=True)

    packed_sizes, packed_layout = read_layout(lpdump, packed, sizes)
    require(packed_sizes == sizes, "Packed logical partition sizes differ from inputs")
    with packed.open("rb") as raw:
        for name, size in sizes.items():
            digest = read_partition(raw, packed_layout[name])
            require(digest == expected_hashes[name], f"Readback of {name} differs from input")
            print(f"{digest}  {name}  {size} bytes")
        packed_hash = read_partition(raw, [(0, SUPER_SIZE)])

    # Publish only a verified image, and fail if another build won the output path.
    os.link(packed, output)
    print(f"{packed_hash}  {output}  {SUPER_SIZE} bytes")


def pack_board_files(board, system, output, tools):
    """Pack four board partitions from a matching device build, without a base super."""
    require(board.is_dir(), "Expected a directory containing the board partition images")
    require(not os.path.lexists(output), f"Output already exists: {output}")
    lpmake, lpdump, simg2img = (tools / name for name in ("lpmake", "lpdump", "simg2img"))
    require(all(os.access(tool, os.X_OK) for tool in (lpmake, lpdump, simg2img)),
            f"Android Linux host tools lpmake, lpdump and simg2img are required in {tools}")
    system_size, system_hash = validate_system(system)
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=".gamma-super-", dir=output.parent) as temporary:
        staging = Path(temporary)
        sizes = {"system": system_size}
        images = {"system": system}
        hashes = {"system": system_hash}
        for name in RETAINED:
            original = board / f"{name}.raw.img"
            if not original.is_file():
                original = board / f"{name}.img"
            require(original.is_file(), f"Missing board partition: {original}")
            image = original
            with original.open("rb") as source:
                magic = source.read(4)
            if magic == bytes.fromhex("3aff26ed"):
                image = staging / original.name
                subprocess.run([simg2img, original, image], check=True)
            size = image.stat().st_size
            require(size and size % BLOCK_SIZE == 0 and size <= GROUP_SIZE,
                    f"Expected a block-aligned board partition: {image}")
            with image.open("rb") as stream:
                stream.seek(1080)
                require(stream.read(2) == bytes.fromhex("53ef"), f"Expected an ext4 partition: {image}")
                hashes[name] = read_partition(stream, [(0, size)])
            images[name] = image
            sizes[name] = size
        install_super(staging, output, lpmake, lpdump, images, hashes, sizes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    boards = parser.add_mutually_exclusive_group(required=True)
    boards.add_argument("--base-super", type=Path, help="canonical Pixel 2 raw Android super image")
    boards.add_argument("--board-dir", type=Path, help="directory with vendor, vendor_dlkm, odm and odm_dlkm images")
    parser.add_argument("--system", type=Path, required=True,
                        help="raw GammaOS ext4 system image")
    parser.add_argument("--output", type=Path, required=True,
                        help="path for the verified raw direct-boot super image")
    parser.add_argument("--tools", type=Path, default=Path.home() /
                        "android/gkd-pixel2/out/host/linux-x86/bin",
                        help="directory containing Linux host lpmake and lpdump")
    args = parser.parse_args()
    try:
        if args.base_super is not None:
            pack(args.base_super, args.system, args.output, args.tools.resolve())
        else:
            pack_board_files(args.board_dir, args.system, args.output, args.tools.resolve())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"{parser.prog}: {error}\n")


if __name__ == "__main__":
    main()
