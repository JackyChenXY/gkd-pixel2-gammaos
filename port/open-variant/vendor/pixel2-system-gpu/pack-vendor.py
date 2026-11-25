#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Assemble and check the Pixel 2 vendor partition with the complete GPU driver."""
import argparse
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

BASE_HASH = "3bde0866c8ad3bdd87356db208ff0605e5a80809de927e48ccdd32a869fa3047"
SIZE = 54_906_880
LIBS = ("lib/egl/libEGL_mesa.so", "lib/egl/libGLESv1_CM_mesa.so",
        "lib/egl/libGLESv2_mesa.so", "lib/libglapi.so", "lib/libgallium_dri.so")
DRI = "lib/dri/libgallium_dri.so"
DRI_TARGET = "../libgallium_dri.so"
HAL_LABEL = "u:object_r:same_process_hal_file:s0"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def debugfs(image, *args):
    result = subprocess.run(["debugfs", *args, str(image)], capture_output=True, check=True)
    errors = [line for line in result.stderr.splitlines() if not line.startswith(b"debugfs ")]
    if len(args) == 2 and args[0] == "-R" and args[1].startswith("rdump / "):
        # Unprivileged rdump cannot chown host copies to Android UID/GID.
        # Only bytes and link targets are read from those host copies.
        errors = [line for line in errors if not re.match(
            rb"^(rdump|dump_file): Operation not permitted while changing ownership of /", line)]
    if errors:
        raise RuntimeError(b"\n".join(errors[:5]).decode(errors="replace"))
    return result.stdout


def catalog(image, dest):
    dest.mkdir()
    debugfs(image, "-R", f'rdump / "{dest}"')
    result = {}
    for p in dest.rglob("*"):
        key = p.relative_to(dest).as_posix()
        if p.is_symlink():
            result[key] = ("link", os.readlink(p))
        elif p.is_dir():
            result[key] = ("directory", "")
        elif p.is_file():
            result[key] = ("file", digest(p))
        else:
            raise ValueError(p)
    return result


def check_elf(path):
    info = subprocess.check_output(["readelf", "-Whd", path], text=True)
    for field, value in (("Class", "ELF32"), ("Machine", "ARM"), ("Type", "DYN")):
        if not re.search(rf"^\s*{field}:\s*{value}\b", info, re.M):
            raise ValueError(f"Incorrect Android ARM32 library: {path}")
    if re.search(r"\((?:RPATH|RUNPATH)\)", info) or f"Library soname: [{path.name}]" not in info:
        raise ValueError(f"Invalid runtime search path or SONAME in {path}")
    notes = subprocess.check_output(["readelf", "-Wn", path], text=True)
    if not re.search(r"Build ID: [0-9a-f]{40}\b", notes):
        raise ValueError(f"Missing 20-byte shader-cache build ID in {path}")
    return set(re.findall(r"\(NEEDED\).*?\[(.*?)\]", info))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("built_lib_directory", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    baseline = args.baseline.resolve(strict=True)
    output = args.output.absolute()
    if baseline.stat().st_size != SIZE or digest(baseline) != BASE_HASH:
        parser.error("Expected the verified Mesa 22.3.7 Pixel 2 vendor partition")
    if output.exists() or output.is_symlink():
        parser.error("Choose a new output file")
    payload = {p: (args.built_lib_directory / Path(p).name).resolve(strict=True) for p in LIBS}
    for p, source in payload.items():
        deps = check_elf(source)
        if "libdrm.so" in deps:
            raise ValueError(f"The board's older dynamic libdrm leaked into {p}")
        if p.endswith("libEGL_mesa.so") and not {"libgallium_dri.so", "libglapi.so"} <= deps:
            raise ValueError("EGL does not link to the candidate 3D stack")
    with tempfile.TemporaryDirectory(prefix="pixel2-vendor-", dir=output.parent) as tmp:
        work = Path(tmp)
        before = catalog(baseline, work / "old")
        if before[DRI][0] != "file" or LIBS[-1] in before:
            raise ValueError("Unexpected vendor library layout")
        after = before.copy()
        image = work / "vendor.img"
        shutil.copyfile(baseline, image)
        label = work / "hal-label"
        label.write_bytes(HAL_LABEL.encode() + b"\0")
        commands = [f'rm /{DRI}']
        for p, source in payload.items():
            if p in before:
                commands.append(f'rm /{p}')
            commands += [f'write "{source}" /{p}', f'sif /{p} mode 0100644',
                         f'sif /{p} uid 0', f'sif /{p} gid 0',
                         f'ea_set -f "{label}" /{p} security.selinux']
            after[p] = ("file", digest(source))
        commands += [f'symlink /{DRI} {DRI_TARGET}', f'sif /{DRI} uid 0',
                     f'sif /{DRI} gid 0', f'ea_set -f "{label}" /{DRI} security.selinux']
        after[DRI] = ("link", DRI_TARGET)
        # Android exposes this value to PackageManager independently of glGetString.
        old_props = (work / "old/build.prop").read_bytes()
        props, changed = re.subn(rb"(?m)^ro\.opengles\.version=131072$",
                                 b"ro.opengles.version=196609", old_props)
        if changed != 1 or props.count(b"ro.opengles.version=") != 1:
            raise ValueError("Unexpected GLES feature declaration")
        prop_file = work / "build.prop"
        prop_file.write_bytes(props)
        vendor_label = work / "vendor-label"
        vendor_label.write_bytes(b"u:object_r:vendor_file:s0\0")
        commands += ["rm /build.prop", f'write "{prop_file}" /build.prop',
                     "sif /build.prop mode 0100600", "sif /build.prop uid 0",
                     "sif /build.prop gid 0",
                     f'ea_set -f "{vendor_label}" /build.prop security.selinux']
        after["build.prop"] = ("file", digest(prop_file))
        script = work / "debugfs.txt"
        script.write_text("\n".join(commands) + "\n")
        debugfs(image, "-w", "-f", str(script))
        subprocess.run(["e2fsck", "-fn", image], check=True)
        if image.stat().st_size != SIZE or catalog(image, work / "new") != after:
            raise RuntimeError("Vendor tree or size differs from the expected result")
        for p in (*LIBS, DRI):
            attrs = debugfs(image, "-R", f"ea_list /{p}")
            if (HAL_LABEL + r"\000").encode() not in attrs:
                raise RuntimeError(f"Missing graphics HAL label: {p}")
            metadata = debugfs(image, "-R", f"stat /{p}")
            if not re.search(rb"User:\s+0\s+Group:\s+0\b", metadata):
                raise RuntimeError(f"Unexpected ownership: {p}")
            if p != DRI and not re.search(rb"Mode:\s+0644\b", metadata):
                raise RuntimeError(f"Unexpected mode: {p}")
        props_stat = debugfs(image, "-R", "stat /build.prop")
        if (not re.search(rb"Mode:\s+0600\b", props_stat)
                or not re.search(rb"User:\s+0\s+Group:\s+0\b", props_stat)
                or b"u:object_r:vendor_file:s0" not in debugfs(image, "-R", "ea_list /build.prop")):
            raise RuntimeError("Unexpected Android properties file metadata")
        os.link(image, output)
        print(f"Compared {len(after)} entries; verified five ARM32 graphics libraries, DRI link, GLES 3.1 feature declaration and labels")
        print(f"{digest(output)}  {output.name}")


if __name__ == "__main__":
    main()
