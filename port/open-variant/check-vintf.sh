#!/usr/bin/env bash
# Check the Android 12 compatibility matrix against the proposed board and kernel.
set -euo pipefail

if (( $# != 4 )); then
    printf 'Usage: %s ANDROID_SDK KERNEL_BUILD SYSTEM_IMG BOARD_IMAGES\n' "$0" >&2
    exit 2
fi

sdk=$(realpath -e -- "$1")
kernel=$(realpath -e -- "$2")/out
system=$(realpath -e -- "$3")
board=$(realpath -e -- "$4")
scratch=$(mktemp -d)
trap 'rm -rf -- "$scratch"' EXIT
for name in system product system_ext vendor odm; do
    mkdir -p "$scratch/$name/etc"
done

debugfs -R "rdump /system/etc/vintf $scratch/system/etc" "$system" >/dev/null 2>&1
for name in product system_ext; do
    debugfs -R "rdump /system/$name/etc/vintf $scratch/$name/etc" "$system" >/dev/null 2>&1
done
for name in vendor odm; do
    debugfs -R "rdump /etc/vintf $scratch/$name/etc" "$board/$name.raw.img" >/dev/null 2>&1
done
test -f "$scratch/vendor/etc/vintf/manifest.xml"
test -f "$scratch/system/etc/vintf/manifest.xml"

args=(--check-compat --property ro.product.first_api_level=32 \
    --kernel "$kernel/include/config/kernel.release:$kernel/.config")
for name in system product system_ext vendor odm; do
    args+=(--dirmap "/$name:$scratch/$name")
done
"$sdk/out/host/linux-x86/bin/checkvintf" "${args[@]}"
