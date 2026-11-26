#!/usr/bin/env python3
"""Verify Android's storage view and the live GLES renderer on a physical Pixel 2."""
import argparse
import re
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--serial")
    parser.add_argument("--expect", choices=("mesa", "trial", "kept", "forced"), required=True)
    args = parser.parse_args()
    target = ["-s", args.serial] if args.serial else ["-d"]

    def shell(command):
        return subprocess.check_output([args.adb, *target, "shell", command], timeout=25,
                                       encoding="utf-8", errors="replace").strip()

    if shell("getprop sys.boot_completed") != "1":
        sys.exit("Android has not finished booting")
    mode = shell("getprop ro.boot.pixel2gpu")
    if mode != args.expect:
        sys.exit("Expected " + args.expect + ", got " + mode)
    if shell("cat /sys/class/block/mmcblk0/device/type") != "SD":
        sys.exit("Physical boot SD card not found")
    number = shell("cat /sys/class/block/mmcblk0p10/dev")
    if not re.fullmatch(r"\d+:\d+", number):
        sys.exit("Missing Mali block device")
    public_id = "public:" + number.replace(":", ",")
    volumes = shell("sm list-volumes all").splitlines()
    if any(line.split()[:1] == [public_id] for line in volumes):
        sys.exit("vold is exporting the Mali slot: " + public_id)
    mounts = [line.split() for line in shell("cat /proc/self/mountinfo").splitlines()]
    vendor = [fields for fields in mounts if len(fields) > 5 and fields[4] == "/vendor"]
    if len(vendor) != 1 or "ro" not in vendor[0][5].split(","):
        sys.exit("Expected a read-only /vendor mount")
    alternate = mode in ("trial", "kept")
    if (vendor[0][2] == number) != alternate:
        sys.exit("The boot profile and mounted vendor partition disagree")
    gles = shell("dumpsys SurfaceFlinger | grep -m 1 'GLES:'")
    if alternate:
        matched = re.search(r"GLES:\s*ARM(?:\s|,)", gles, re.IGNORECASE) and "mali" in gles.lower()
    else:
        matched = "panfrost" in gles.lower()
    if not matched:
        sys.exit("Unexpected live GLES renderer: " + gles)
    print("Boot profile", mode)
    print("Read-only /vendor", vendor[0][2])
    print("Driver slot hidden from portable storage")
    print(gles)


if __name__ == "__main__":
    main()
