#!/usr/bin/env python3
"""Install the cold-start selector and release marker in the signed v0.3.1 system."""
import argparse
import hashlib
import importlib.util
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("desktop_system", HERE.parent / "desktop/at4k/build-system.py")
desktop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(desktop)
SYSTEM = "e92d3c5fb8f086f89ff18238cc368828b68e40c5cebe15a14c9ddfeb65525308"
APK = "/system/priv-app/Pixel2GpuSelector/Pixel2GpuSelector.apk"
OLD_APK = "12648eb1095a3a88a452829dd7bf766318059824a6502767190214cca102e9e8"
MARKER = "/system/etc/pixel2-release"


def ext4(image, command):
    return subprocess.check_output(["debugfs", "-R", command, image], stderr=subprocess.DEVNULL)


def replace_payloads(image, entries):
    """The two release files retain their lengths, inodes and SELinux labels."""
    block_size = int(re.search(rb"(?m)^Block size:\s*(\d+)$", ext4(image, "stats"))[1])
    used = set()
    with image.open("r+b") as disk:
        for path, original, content in entries:
            if len(original) != len(content) or ext4(image, "cat " + path) != original:
                raise ValueError("Expected the matching fixed-length release file: " + path)
            for index, start in enumerate(range(0, len(content), block_size)):
                location = int(ext4(image, f"bmap {path} {index}").strip())
                if location <= 0 or location in used:
                    raise ValueError("Missing or overlapping ext4 data block")
                used.add(location)
                offset = location * block_size
                size = min(block_size, len(content) - start)
                disk.seek(offset)
                if disk.read(size) != original[start:start + size]:
                    raise ValueError("Invalid ext4 extent for " + path)
                disk.seek(offset)
                disk.write(content[start:start + size])
            disk.flush()
            if ext4(image, "cat " + path) != content:
                raise OSError("Failed filesystem readback for " + path)
        os.fsync(disk.fileno())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("baseline", "gamma", "apk", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    if not args.baseline.is_file() or not args.apk.is_file():
        parser.error("Supply the released system image and signed GPU settings APK")
    if os.path.lexists(args.output) or desktop.digest(args.baseline) != SYSTEM:
        parser.error("Use the released v0.3.1 system and a new output filename")
    gamma = args.gamma.resolve()
    host = gamma / "out-pixel2-gamma/host/linux-x86/bin"
    key = gamma / "external/avb/test/data/testkey_rsa2048.pem"
    env = dict(os.environ, LC_ALL="C", PATH=str(host) + ":" + os.environ["PATH"])
    desktop.verify_signer(gamma, env, args.apk, gamma / "build/make/target/product/security/platform.x509.pem")
    aapt = gamma / "prebuilts/sdk/tools/linux/bin/aapt"
    info = subprocess.check_output([aapt, "dump", "badging", args.apk], text=True,
                                   env=dict(env, LD_LIBRARY_PATH=str(gamma / "prebuilts/sdk/tools/linux/lib64")))
    if "package: name='org.gkdpixel2.gpu' versionCode='3' versionName='0.3.2'" not in info:
        raise ValueError("Unexpected driver settings APK")
    if not desktop.has_compiled_strings(args.apk, [b"com.android.internal.intent.action.REQUEST_SHUTDOWN"]):
        raise ValueError("Missing the power-off action")
    def avb(*cmd):
        return subprocess.check_output([host / "avbtool", *cmd], env=env, text=True)
    with tempfile.TemporaryDirectory(dir=args.output.resolve().parent) as tmp:
        image = Path(tmp) / "system.img"
        shutil.copyfile(args.baseline, image)
        avb("verify_image", "--image", image, "--key", key)
        description = avb("info_image", "--image", image)
        def field(name):
            return re.search(r"(?m)^\s*" + name + r":\s*(\S+)", description)[1]
        props = []
        for prop, value in re.findall(r"(?m)^\s*Prop: (.*?) -> '(.*?)'$", description):
            props.extend(["--prop", prop + ":" + value])
        avb("erase_footer", "--image", image)
        old = ext4(image, "cat " + APK)
        if hashlib.sha256(old).hexdigest() != OLD_APK:
            raise ValueError("Unexpected original GPU settings")
        replace_payloads(image, [(APK, old, args.apk.read_bytes()),
                         (MARKER, b"GKD Pixel 2 community TF image 0.3.1\n", b"GKD Pixel 2 community TF image 0.3.2\n")])
        subprocess.run(["e2fsck", "-fn", image], stdout=subprocess.DEVNULL, check=True)
        avb("add_hashtree_footer", "--image", image, "--partition_name", "system",
            "--partition_size", str(args.baseline.stat().st_size), "--algorithm", field("Algorithm"),
            "--hash_algorithm", field("Hash Algorithm"), "--key", key, "--salt", field("Salt"),
            "--rollback_index", field("Rollback Index"), *props)
        avb("verify_image", "--image", image, "--key", key)
        checksum = desktop.digest(image)
        os.link(image, args.output)
        print(checksum, args.output.name, flush=True)


if __name__ == "__main__":
    main()
