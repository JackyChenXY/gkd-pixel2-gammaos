#!/usr/bin/env python3
"""Check the factory desktop and controller settings on an unlocked GKD Pixel 2."""
import argparse
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--serial", help="ADB serial number instead of the attached USB device")
    args = parser.parse_args()
    device = [args.adb, "-s", args.serial] if args.serial else [args.adb, "-d"]

    def shell(*command):
        return subprocess.check_output(
            [*device, "shell", *command], timeout=18, text=True, errors="replace"
        ).strip()

    failures = []

    def check(label, ok):
        print(("PASS " if ok else "FAIL ") + label)
        if not ok:
            failures.append(label)

    version = shell("cat", "/system/etc/pixel2-release")
    if version != "GKD Pixel 2 community TF image 0.3.1":
        sys.exit("This checker expects the GKD Pixel 2 v0.3.1 image.")
    check("Android boot completed", shell("getprop", "sys.boot_completed") == "1")
    check("Upstream AT4K is preinstalled",
          shell("pm", "path", "com.overdevs.at4k") == "package:/oem/app/AT4K/AT4K.apk")
    home = shell("cmd", "package", "resolve-activity", "--brief", "--user", "0",
                 "-a", "android.intent.action.MAIN", "-c", "android.intent.category.HOME")
    check("HOME resolves directly to AT4K", home.splitlines()[-1:] == ["com.overdevs.at4k/.MainActivity"])
    wallpaper = "/oem/app/AT4K/H700-wallpaper.jpg"
    check("H700 default wallpaper is selected", shell("getprop", "ro.config.wallpaper") == wallpaper)
    check("Original wallpaper matches",
          shell("sha256sum", wallpaper).split()[:1] == [
              "0d99ad08346620e240fa6eb7e765bb55996d4a311c8141a209626e08cad88997"])
    check("Hardware-key mode hides the Android navigation bar",
          shell("getprop", "persist.sys.phh.mainkeys") == "1" and shell("getprop", "qemu.hw.mainkeys") == "1")
    check("Factory controller settings are present", shell("getprop", "ro.pixel2.handheld_navigation") == "1")
    services = shell("settings", "--user", "0", "get", "secure", "enabled_accessibility_services").split(":")
    check("Controller service enabled for the owner",
          shell("settings", "--user", "0", "get", "secure", "accessibility_enabled") == "1" and
          any(value in services for value in (
              "org.gkdpixel2.padnavigation/.PadNavigationService",
              "org.gkdpixel2.padnavigation/org.gkdpixel2.padnavigation.PadNavigationService")))
    check("Settings report the built-in controller service as bound",
          any("Bound services:" in line and ("Pixel 2 手柄导航" in line or "pixel 2 gamepad navigation" in line.lower())
              for line in shell("dumpsys", "accessibility").splitlines()))
    return int(bool(failures))


if __name__ == "__main__":
    sys.exit(main())
