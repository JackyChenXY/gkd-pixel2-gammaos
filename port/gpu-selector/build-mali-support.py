#!/usr/bin/env python3
"""Build the rc.2 Windows downloader's public support archive from a pinned Pixel 2 Android SDK build."""
import argparse
import hashlib
import json
import re
import subprocess
import tempfile
import os
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent

# The proprietary EGL driver and both downloaded init files deliberately have no entry here.
MODULES = {
    "bin/hw/android.hardware.graphics.allocator@4.0-service": "hardware/rockchip/libgralloc/bifrost/service/4.x",
    "bin/hw/android.hardware.graphics.composer@2.1-service": "hardware/interfaces/graphics/composer/2.1/default",
    "lib/arm.graphics-V3-ndk_platform.so": "hardware/rockchip/libgralloc/bifrost/interfaces/aidl",
    "lib/hw/android.hardware.graphics.allocator@4.0-impl-bifrost.so": "hardware/rockchip/libgralloc/bifrost/src/4.x",
    "lib/hw/android.hardware.graphics.mapper@4.0-impl-bifrost.so": "hardware/rockchip/libgralloc/bifrost/src/4.x",
    "lib/hw/hwcomposer.rk30board.so": "hardware/rockchip/hwcomposer/drmhwc",
    "lib/librga.so": "hardware/rockchip/librga",
    "lib/libsync_vendor.so": "system/core/libsync",
}
DIRECT_SOURCES = tuple(dict.fromkeys(MODULES.values()))
HEADERS = (
    "hardware/rockchip/libgralloc/bifrost/src",
    "hardware/rockchip/libgralloc/bifrost/service/4.x",
    "hardware/rockchip/libgralloc/bifrost/interfaces/aidl/arm",
    "hardware/rockchip/hwcomposer/drmhwc",
    "hardware/rockchip/librga/core",
    "hardware/rockchip/librga/include",
    "hardware/rockchip/librga/im2d_api",
    "hardware/interfaces/graphics/composer/2.1/default",
    "system/core/libsync",
)
NOTICES = (
    "hardware/interfaces/NOTICE", "system/core/libsync/NOTICE", "hardware/rockchip/librga/COPYING",
    "frameworks/native/NOTICE", "system/libhidl/NOTICE", "external/tinyxml2/LICENSE.txt",
    "external/libxml2/Copyright", "external/zlib/LICENSE", "external/libcxx/LICENSE.TXT",
    "external/compiler-rt/LICENSE.TXT", "bionic/libc/NOTICE",
    "prebuilts/clang/host/linux-x86/clang-r416183b1/NOTICE",
)
PREAMBLE = """GKD Pixel 2 GammaOS rc.2 — companion files for the Windows driver downloader

Arm Limited, the Android Open Source Project and Fuzhou Rockchip Electronics supplied the
source for these eight Android files. See SOURCES.json for individual binary hashes,
the upstream source revisions and build coordinates. The build uses the upstream
Apache-2.0-marked gralloc, graphics service, HWC, RGA and sync sources. Source comments
also credit ChenZhen for the gralloc logging header. Original component and toolchain
notices, including third-party static dependencies, follow below.

This archive contains no Mali EGL library. The end user's Windows process fetches the
original, pinned EGL input and two init configuration files from their upstream repositories.
The upstream terms continue to apply to those files. The open component licenses
listed here do not grant a license to the separately supplied Mali EGL driver.
"""

def git(directory, *args):
    return subprocess.check_output(["git", "-C", directory, *args], text=True).strip()

def gather(sdk):
    build = sdk / "out/target/product/gkd_pixel2/vendor"
    board = json.loads((HERE / "reference.json").read_text())
    known = {row["path"]: row for row in board["files"]}
    if set(known) - MODULES.keys() != {
        "lib/egl/libGLES_mali.so", "etc/init/android.hardware.graphics.allocator@4.0-service.rc",
        "etc/init/android.hardware.graphics.composer@2.1-service.rc",
    }:
        raise ValueError("Unexpected rc.2 profile")
    projects = {p.get("path", p.get("name")): p for p in
                ET.parse(REPO / "manifests/rockchip-android12-pixel2.xml").getroot().findall("project")}
    project_list = {}
    for path in (*DIRECT_SOURCES, *HEADERS, *NOTICES):
        prefix = max((p for p in projects if path == p or path.startswith(p + "/")), key=len)
        if prefix in project_list:
            continue
        project = projects[prefix]
        sha = project.get("revision")
        if git(sdk / prefix, "rev-parse", "HEAD") != sha:
            raise ValueError("Wrong SDK revision for " + prefix)
        project_list[prefix] = f"https://github.com/{project.get('name')}/tree/{sha}"

    entries, files = {}, {}
    for name, source in MODULES.items():
        data = (build / name).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if len(data) != known[name]["size"] or digest != known[name]["hash"] or not data.startswith(b"\x7fELF\x01"):
            raise ValueError("Incorrect ARM32 build output: " + name)
        entries[name] = data
        files[name] = dict(source=source, sha256=digest, size=len(data))

    chunks = [PREAMBLE]
    seen = set()
    def include(origin, body):
        clean = body.replace("\r\n", "\n").strip()
        if clean and clean not in seen:
            chunks.append(origin + "\n\n" + clean)
            seen.add(clean)

    include("Apache License 2.0", (REPO / "LICENSES/Apache-2.0.txt").read_text())
    for name in NOTICES:
        include(name, (sdk / name).read_text(encoding="utf-8", errors="replace"))
    for base in HEADERS:
        for source in sorted((sdk / base).rglob("*")):
            if not source.is_file() or source.suffix not in {".h", ".c", ".cpp", ".hpp", ".aidl"}:
                continue
            header = re.match(r"\s*(/\*.*?\*/)", source.read_text(encoding="utf-8", errors="replace"), re.S)
            if header and re.search(r"copyright|SPDX-License|permission is hereby granted", header[1], re.I):
                include(source.relative_to(sdk).as_posix(), header[1])
    entries["NOTICE.txt"] = ("\n\n" + ("-" * 72) + "\n\n").join(chunks).encode("utf-8") + b"\n"
    data = dict(target="gkd_pixel2-userdebug", firmware="v0.3.0-rc.2", components=files, upstream=project_list,
                manifest="manifests/rockchip-android12-pixel2.xml")
    entries["SOURCES.json"] = (json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    return entries

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    entries = gather(args.sdk.resolve())
    with tempfile.TemporaryDirectory(dir=args.output.parent) as scratch:
        archive = Path(scratch) / "support.zip"
        with zipfile.ZipFile(archive, "w") as out:
            for name, value in sorted(entries.items()):
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                # Store verbatim for a reproducible digest independently of the host's compression library.
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                out.writestr(info, value)
        with zipfile.ZipFile(archive) as source:
            if set(source.namelist()) != set(entries) or source.testzip() is not None:
                raise ValueError("Public archive verification failed")
        os.link(archive, args.output)
    print(args.output.stat().st_size, hashlib.sha256(args.output.read_bytes()).hexdigest())

if __name__ == "__main__":
    main()
