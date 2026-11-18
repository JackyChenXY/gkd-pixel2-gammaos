#!/usr/bin/env python3
"""Prepare the pinned GammaOS Android 12 A64 source for a GKD Pixel 2 build."""

import argparse
import difflib
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


UPSTREAM = "b2db9cfe308c8753e3385b8ab64bcb34c3177177"
TREBLE = "device/phh/treble"
SYSTEMUI = "frameworks/base/packages/SystemUI"
DAIJISHO = f"{TREBLE}/gammaos/daijisho/399.apk"
DONOR_TILES = {
    "performance", "fan", "abxy", "dpadAnalogToggle", "analogsensitivity",
    "analogaxis", "rightanalogaxis",
}
TILE_LISTS = {
    "quick_settings_tiles_default",
    "quick_settings_tiles_stock",
    "quick_settings_tiles_retail_mode",
}


def replace_once(text, old, new, description):
    if text.count(old) != 1:
        raise ValueError(f"expected one {description} in upstream source")
    return text.replace(old, new, 1)


def trim_make_assignments(text, excluded):
    """Remove literal RHS entries while keeping untouched assignments byte-for-byte."""
    lines = iter(text.splitlines(keepends=True))
    result = []
    removed = set()
    for line in lines:
        if not re.match(r"^PRODUCT_[A-Z_]+\s*(?:\+=|:=) \\\n$", line):
            result.append(line)
            continue

        entries = []
        for entry in lines:
            continued = entry.rstrip().endswith("\\")
            value = entry.strip().removesuffix("\\").rstrip()
            entries.append((entry, value))
            if not continued:
                break

        keep = []
        for entry, value in entries:
            name = value.split(":", 1)[0]
            if name in excluded:
                removed.add(name)
            else:
                keep.append((entry, value))
        if len(keep) == len(entries):
            result.append(line)
            result.extend(entry for entry, _ in entries)
        elif keep:
            result.append(line)
            for entry, value in keep[:-1]:
                result.append(entry)
            result.append(keep[-1][0].rstrip().removesuffix("\\").rstrip() + "\n")

    if removed != excluded:
        missing = ", ".join(sorted(excluded - removed))
        raise ValueError(f"missing expected upstream build entries: {missing}")
    return "".join(result)


def adapt_base(text):
    start = text.index("# GammaOS Customizations\n")
    end = text.index("PRODUCT_PACKAGES += \\\n\ttreble-environ-rc", start)
    upstream_gamma = text[start:end]
    launcher = f"        {DAIJISHO}:system/product/app/daijisho/399.apk"
    if upstream_gamma.count(launcher) != 1:
        raise ValueError("upstream GammaOS Daijisho package did not match")
    text = (
        text[:start]
        + "# GammaOS launcher for the Pixel 2 build.\n"
        + "PRODUCT_COPY_FILES += \\\n"
        + launcher + "\n\n"
        + text[end:]
    )
    return trim_make_assignments(
        text,
        {
            "ro.adb.secure=0",
            "persist.sys.usb.config=adb",
            "resetprop_phh",
            *(f"{TREBLE}/{name}" for name in (
                "vndk-detect", "rw-system.sh", "phh-on-data.sh", "phh-on-boot.sh",
                "phh-prop-handler.sh", "phh-securize.sh", "files/adbd.rc", "files/ota.sh",
                "remote/dbclient", "remote/phh-remotectl.rc", "remote/phh-remotectl.sh",
                "twrp/twrp.rc", "twrp/twrp.sh", "twrp/busybox-armv7l",
            )),
        },
    )


def adapt_vndk_init(text):
    for marker in (
        "on post-fs\n", "/system/bin/vndk-detect", "/system/bin/rw-system.sh",
        "service phh_on_boot", "service rgp2xbox_on_boot",
        "on property:sys.phh.uninstall-ota=true",
        "setprop qemu.hw.mainkeys ${persist.sys.phh.mainkeys}",
    ):
        if marker not in text:
            raise ValueError(f"upstream VNDK init is missing {marker!r}")
    # The existing Rockchip vendor supplies ro.vndk.version=32. Keep the generic
    # linker and navigation settings, without rewriting system/vendor mounts.
    return (
        "# Pixel 2 uses its existing vendor VNDK and HAL declarations.\n"
        "on post-fs\n"
        "    export LD_PRELOAD :\n"
        "\n"
        "on property:persist.sys.phh.mainkeys=*\n"
        "    setprop qemu.hw.mainkeys ${persist.sys.phh.mainkeys}\n"
    )


def adapt_quick_settings(text):
    root = ET.fromstring(text)
    seen = set()
    for node in root.findall("string"):
        name = node.get("name")
        if name not in TILE_LISTS:
            continue
        if name in seen or node.text is None:
            raise ValueError(f"invalid upstream quick settings list {name}")
        seen.add(name)
        before = node.text.strip()
        tiles = before.split(",")
        if DONOR_TILES.isdisjoint(tiles):
            raise ValueError(f"missing upstream hardware tiles in {name}")
        after = ",".join(tile for tile in tiles if tile not in DONOR_TILES)
        text = replace_once(text, before, after, name)
    if seen != TILE_LISTS:
        raise ValueError("missing one or more upstream quick settings lists")
    ET.fromstring(text)
    return text


def adapt_product(text):
    for marker in ("aosp_arm.mk", "PRODUCT_NAME := lineage_a64_bvN",
                   "PRODUCT_DEVICE := phhgsi_a64_ab"):
        if marker not in text:
            raise ValueError(f"upstream A64 vanilla product is missing {marker!r}")
    return replace_once(
        text, "PRODUCT_MODEL := Phh-Treble vanilla",
        "PRODUCT_MODEL := GKD Pixel 2 (GammaOS)", "A64 vanilla model",
    ) + "\n$(call inherit-product-if-exists, device/phh/treble/pixel2/product.mk)\n"


def adapt_system_properties(text):
    return replace_once(text, "ro.adb.secure=0\n", "ro.adb.secure=1\n", "ADB property")


def adapt_gsi_system_properties(text):
    return replace_once(
        text, "# GSI always disables adb authentication\nro.adb.secure=0\n",
        "# ADB authentication follows the device product setting.\n",
        "generic GSI ADB property",
    )


def adapt_lineage(text):
    return replace_once(
        text,
        "PRODUCT_SYSTEM_DEFAULT_PROPERTIES += \\\n"
        "    ro.system.ota.json_url=https://downloads.sourceforge.net/project/"
        "andyyan-gsi/lineage-19.x/ota.json\n",
        "# This device-specific DSU build has no generic GSI OTA source.\n",
        "generic GSI updater endpoint",
    )


def adapt_lineage_common(text):
    text = replace_once(text, 'PRODUCT_SYSTEM_DEFAULT_PROPERTIES += ro.adb.secure=0\n', "", "Lineage ADB override")
    return trim_make_assignments(
        text,
        {"Updater", "vendor/lineage/prebuilt/common/etc/init/init.lineage-updater.rc"},
    )


def adapt_build_manifest(text):
    manifest = (
        '<manifest><remote name="gammaos" fetch="https://github.com/TheGammaSqueeze" />'
        f'<project name="GammaOSDistribution" path="gammaos" remote="gammaos" revision="{UPSTREAM}">'
        '<annotation name="build-profile" value="gkd-pixel2-gamma-a64" />'
        '</project></manifest>'
    )
    return replace_once(
        text,
        '\tpython3 .repo/repo/repo manifest -o - -r | grep -Ev "proprietary_$(MANIFEST_EXCLUDES)" > $@\n',
        f"\tprintf '%s\\n' '{manifest}' > $@\n",
        "repo-only provenance recipe",
    )



EDITS = {
    f"{TREBLE}/base.mk": adapt_base,
    f"{TREBLE}/lineage.mk": adapt_lineage,
    f"{TREBLE}/lineage_a64_bvN.mk": adapt_product,
    f"{TREBLE}/system.prop": adapt_system_properties,
    "build/make/target/board/gsi_system_ext.prop": adapt_gsi_system_properties,
    f"{TREBLE}/vndk.rc": adapt_vndk_init,
    f"{SYSTEMUI}/res/values/config.xml": adapt_quick_settings,
    "vendor/lineage/config/common.mk": adapt_lineage_common,
    "vendor/lineage/config/Android.mk": adapt_build_manifest,
}


def git(tree, *args):
    return subprocess.check_output(("git", "-C", str(tree), *args)).decode("utf-8")


def plan(tree):
    if Path(git(tree, "rev-parse", "--show-toplevel").strip()).resolve() != tree:
        raise ValueError("pass the root of the dedicated GammaOS checkout")
    revision = git(tree, "rev-parse", "HEAD").strip()
    if revision != UPSTREAM:
        raise ValueError(f"expected GammaOS HEAD {UPSTREAM}, found {revision}")

    changes = []
    for relative, transform in EDITS.items():
        path = tree / relative
        if path.resolve() != path or not path.is_file():
            raise ValueError(f"expected a regular checkout file at {relative}")
        upstream = git(tree, "show", f"{UPSTREAM}:{relative}")
        desired = transform(upstream)
        actual = path.read_bytes().decode("utf-8")
        if actual == desired:
            continue
        if actual != upstream:
            raise ValueError(f"{relative} has local changes; refusing to overwrite them")
        changes.append((path, upstream, desired))
    return changes


def apply_changes(changes):
    for path, _, desired in changes:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
            temporary = Path(output.name)
        try:
            temporary.write_bytes(desired.encode("utf-8"))
            temporary.chmod(path.stat().st_mode & 0o777)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", type=Path, help="dedicated checkout at the pinned GammaOS revision")
    parser.add_argument("--apply", action="store_true", help="write the changes; default prints a diff")
    args = parser.parse_args()
    tree = args.checkout.resolve()
    try:
        changes = plan(tree)
        if args.apply:
            apply_changes(changes)
            print(f"Prepared {len(changes)} files in GammaOS {UPSTREAM} for lineage_a64_bvN")
        else:
            for path, before, after in changes:
                name = str(path.relative_to(tree))
                sys.stdout.writelines(
                    difflib.unified_diff(
                        before.splitlines(keepends=True), after.splitlines(keepends=True),
                        fromfile=f"a/{name}", tofile=f"b/{name}",
                    )
                )
            if not changes:
                print(f"GammaOS {UPSTREAM} is already prepared for lineage_a64_bvN")
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"{parser.prog}: {error}\n")


if __name__ == "__main__":
    main()
