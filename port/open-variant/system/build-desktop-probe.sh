#!/usr/bin/env bash
# Generate a fresh ext4 desktop-probe image from a known Pixel 2 Android build.
set -euo pipefail

if [[ $# != 2 && $# != 4 ]]; then
    printf 'Usage: %s GAMMA_SOURCE NEW_OUTPUT_DIRECTORY [SETTINGS_INSTALL_DIR SYSTEM_BYTES]\n' "$0" >&2
    exit 2
fi

gamma=$(realpath -e -- "$1")
out=$(realpath -e -- "${GAMMA_BUILD_OUT:-$gamma/out-pixel2-gamma}")
parent=$(realpath -e -- "$(dirname -- "$2")")
destination="$parent/$(basename -- "$2")"
product="$out/target/product/phhgsi_a64_ab"
prop="$product/obj/PACKAGING/systemimage_intermediates/system_image_info.txt"
host_tools="$out/host/linux-x86/bin"
pinned=b2db9cfe308c8753e3385b8ab64bcb34c3177177

if [[ -e "$destination" || -L "$destination" ]]; then
    printf 'Output directory already exists: %s\n' "$destination" >&2
    exit 1
fi
if [[ $(git -C "$gamma" rev-parse HEAD) != "$pinned" ]]; then
    printf 'Expected the pinned GammaOS source revision %s\n' "$pinned" >&2
    exit 1
fi
for tool in build_image avbtool aapt; do
    test -x "$host_tools/$tool"
done
for tool in debugfs e2fsck python3; do
    command -v "$tool" >/dev/null
done
test -f "$product/system.img"
grep -Fxq 'ro.pixel2.extra_swap.supported=true' "$product/system/build.prop"
grep -Fxq "root_dir=$product/root" "$prop"

swap=bin/pixel2-extra-swap
swap_rc=etc/init/pixel2-extra-swap.rc
zram_rc=etc/init/pixel2-zram.rc
keylayout=usr/keylayout/gkd_pixel2_joypad.kl
launcher=system_ext/priv-app/TrebuchetQuickStep/TrebuchetQuickStep.apk
notices=etc/NOTICE.xml.gz
for relative in "$swap" "$swap_rc" "$zram_rc" "$keylayout" "$launcher" "$notices"; do
    test -s "$product/system/$relative"
done

scratch=$(mktemp -d)
stage=$(mktemp -d -- "$parent/.pixel2-open-system.XXXXXXXX")
trap 'rm -rf -- "$scratch" "$stage"' EXIT
mkdir -- "$scratch/temporary" "$stage/result"
settings=
if [[ $# == 4 ]]; then
    settings=$(realpath -e -- "$3")
    if [[ ! "$4" =~ ^[1-9][0-9]{0,11}$ ]] || (( $4 % 4096 != 0 )); then
        echo 'SYSTEM_BYTES must be a positive, 4096-byte-aligned decimal length.' >&2
        exit 2
    fi
    test -s "$settings/Settings.apk"
    if grep -q '^system_size=' "$prop"; then
        echo 'The source image metadata already has a fixed system size.' >&2
        exit 1
    fi
    cp -- "$prop" "$scratch/system-image-info.txt"
    printf '\nsystem_size=%s\n' "$4" >> "$scratch/system-image-info.txt"
    prop="$scratch/system-image-info.txt"
fi
image="$stage/result/system.img"
log="$stage/result/build.log"
export TMPDIR="$scratch/temporary"
export PATH="$host_tools:$PATH"

# Copy the populated system tree into a separate directory. The original input
# stays untouched and the omitted APKs are never written to the new filesystem.
python3 - "$product/system" "$scratch/system" "$settings" <<'PY'
from pathlib import Path
import shutil
import sys
import zipfile

source, destination = map(Path, sys.argv[1:3])
omit = {"daijisho", "webview", "Jelly"}
for name in omit:
    if not (source / "product/app" / name).is_dir():
        raise SystemExit(f"Missing expected package in the pinned build: {name}")

def ignore(directory, _):
    if Path(directory) == source / "product/app":
        return omit
    return ()

shutil.copytree(source, destination, symlinks=True, ignore=ignore)
if sys.argv[3]:
    settings = Path(sys.argv[3])
    target = destination / "system_ext/priv-app/Settings"
    if not target.is_dir() or not target.resolve().is_relative_to(destination.resolve()):
        raise SystemExit("Settings path does not resolve inside the staged system tree")
    apk = settings / "Settings.apk"
    installed = target / apk.name
    if not installed.is_file() or installed.is_symlink():
        raise SystemExit("Expected the existing regular Settings APK")
    with zipfile.ZipFile(apk) as archive:
        if "classes.dex" not in archive.namelist():
            raise SystemExit("Replacement Settings APK must contain DEX")
    preopt = settings / "oat/arm"
    companion_files = [preopt / "Settings.odex", preopt / "Settings.vdex"]
    has_preopt = [item.is_file() and item.stat().st_size for item in companion_files]
    if any(has_preopt) and not all(has_preopt):
        raise SystemExit("Replacement Settings preopt output is incomplete")
    installed_oat = target / "oat"
    if installed_oat.is_symlink():
        raise SystemExit("Unexpected symlink for the staged Settings preopt path")
    if installed_oat.exists():
        shutil.rmtree(installed_oat)
    if all(has_preopt):
        (installed_oat / "arm").mkdir(parents=True)
        for companion in companion_files:
            shutil.copyfile(companion, installed_oat / "arm" / companion.name)
    shutil.copyfile(apk, installed)
prop = destination / "build.prop"
properties = prop.read_text(encoding="utf-8").splitlines()
identity = {"ro.build.user": "pixel2", "ro.build.host": "pixel2-builder"}
rewritten = []
for line in properties:
    key, _, _ = line.partition("=")
    if key in identity:
        line = f"{key}={identity.pop(key)}"
    rewritten.append(line)
if identity:
    raise SystemExit("Missing Android build identity fields")
rewritten.extend(("", "ro.pixel2.open_system_probe=true"))
prop.write_text("\n".join(rewritten) + "\n", encoding="utf-8")
PY

cd -- "$gamma"
if ! "$host_tools/build_image" "$scratch/system" "$prop" "$image" "$product" > "$log" 2>&1; then
    tail -n 70 "$log"
    exit 1
fi

if [[ -n "$settings" ]]; then
    test "$(stat -c%s "$image")" = "$4"
    settings_path=/system/system_ext/priv-app/Settings
    debugfs -R "dump $settings_path/Settings.apk $scratch/Settings.apk" "$image" 2>/dev/null
    cmp -- "$settings/Settings.apk" "$scratch/Settings.apk"
    for preopt in Settings.odex Settings.vdex; do
        if [[ -f "$settings/oat/arm/$preopt" ]]; then
            debugfs -R "dump $settings_path/oat/arm/$preopt $scratch/$preopt" "$image" 2>/dev/null
            cmp -- "$settings/oat/arm/$preopt" "$scratch/$preopt"
        else
            debugfs -R "stat $settings_path/oat/arm/$preopt" "$image" 2>&1 | grep -F 'File not found'
        fi
    done
    debugfs -R "ea_list $settings_path/Settings.apk" "$image" 2>/dev/null \
        | grep -F 'u:object_r:system_file:s0' | tee -a "$log"
fi
e2fsck -fn "$image" | tee -a "$log"
"$host_tools/avbtool" verify_image --image "$image" \
    --key external/avb/test/data/testkey_rsa2048.pem | tee -a "$log"
for omit in daijisho webview Jelly; do
    debugfs -R "stat /system/product/app/$omit" "$image" 2>&1 | grep -F 'File not found' >> "$log"
done
for relative in "$swap" "$swap_rc" "$zram_rc" "$keylayout" "$launcher" "$notices"; do
    name=$(basename -- "$relative")
    debugfs -R "dump /system/$relative $scratch/$name" "$image" 2>/dev/null
    cmp -- "$product/system/$relative" "$scratch/$name"
done
"$host_tools/aapt" dump xmltree "$scratch/$(basename -- "$launcher")" AndroidManifest.xml \
    | grep -F 'android.intent.category.HOME' | tee -a "$log"
debugfs -R 'cat /system/build.prop' "$image" 2>/dev/null > "$scratch/build.prop"
grep -Fx 'ro.pixel2.open_system_probe=true' "$scratch/build.prop"
grep -Fx 'ro.build.user=pixel2' "$scratch/build.prop"
grep -Fx 'ro.build.host=pixel2-builder' "$scratch/build.prop"
grep -Fx 'ro.pixel2.extra_swap.supported=true' "$scratch/build.prop"
debugfs -R "ea_list /system/$swap" "$image" 2>/dev/null \
    | grep -F 'u:object_r:pixel2_extra_swap_exec:s0' | tee -a "$log"
debugfs -R 'stat /product' "$image" 2>/dev/null | grep -F 'Fast link dest: "/system/product"'
debugfs -R 'stat /system_ext' "$image" 2>/dev/null | grep -F 'Fast link dest: "/system/system_ext"'
(cd -- "$stage/result" && sha256sum system.img > SHA256SUMS)
mv -nT -- "$stage/result" "$destination"
if [[ -e "$stage/result" ]]; then
    printf 'Another process created the output directory: %s\n' "$destination" >&2
    exit 1
fi
cat -- "$destination/SHA256SUMS"
printf 'Prepared experimental system image at %s/system.img\n' "$destination"
