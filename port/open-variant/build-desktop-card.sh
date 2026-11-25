#!/usr/bin/env bash
# Assemble a boot probe from one matching set of board and system outputs.
set -euo pipefail

if (( $# != 7 )); then
    printf 'Usage: %s SDK BOOT_PREFIX KERNEL_BUILD SYSTEM_IMG BOARD_IMAGES DISK_BYTES NEW_OUTPUT_DIRECTORY\n' "$0" >&2
    exit 2
fi

port=$(cd -- "$(dirname -- "$0")/.." && pwd)
sdk=$(realpath -e -- "$1")
prefix=$(realpath -e -- "$2")
kernel=$(realpath -e -- "$3")/out/arch/arm64/boot
system=$(realpath -e -- "$4")
board=$(realpath -e -- "$5")
size=$6
parent=$(realpath -e -- "$(dirname -- "$7")")
output="$parent/$(basename -- "$7")"
if [[ -e "$output" || -L "$output" ]]; then
    printf 'Output directory already exists: %s\n' "$output" >&2
    exit 1
fi
for tool in python3 mkimage fdtget mkfs.fat mkfs.ext4 mcopy sgdisk; do
    command -v "$tool" > /dev/null
done
for file in "$prefix" "$system" "$kernel/Image" "$kernel/dts/rockchip/rk3326s-gkd-pixel2-open.dtb" \
    "$board/ramdisk.img" "$board/cache.raw.img"; do
    test -f "$file" && test -s "$file"
done

temporary=$(mktemp -d -- "$parent/.pixel2-open-card.XXXXXXXX")
trap 'rm -rf -- "$temporary"' EXIT
stage="$temporary/result"
mkdir -- "$stage" "$temporary/compiler"
ln -s -- "$sdk/prebuilts" "$temporary/compiler/prebuilts"

python3 "$port/make-pixel2-test-gpt.py" "$size" "$stage/gpt"
mkimage -A arm64 -O linux -T ramdisk -C gzip -a 0 -e 0 \
    -n 'Pixel 2 Android board ramdisk' -d "$board/ramdisk.img" "$temporary/base-ramdisk.uimg"
ANDROID_ROOT="$temporary/compiler" python3 "$port/diagnostics/build-diagnostic-init.py" \
    --android --capture-display --reinitialize-panel --pointer --storage-log \
    --standalone-gamma --base-ramdisk "$temporary/base-ramdisk.uimg" \
    --layout "$stage/gpt/partition-layout.json" --output-dir "$temporary"
python3 "$port/open-variant/boot/prepare_boot_files.py" \
    --kernel "$kernel/Image" --dtb "$kernel/dts/rockchip/rk3326s-gkd-pixel2-open.dtb" \
    --ramdisk "$temporary/ramdisk.uimg" --output "$stage/boot"
python3 "$port/prepare-pixel2-gamma-direct-super.py" \
    --board-dir "$board" --system "$system" --tools "$sdk/out/host/linux-x86/bin" --output "$temporary/super.raw.img"
PYTHONDONTWRITEBYTECODE=1 python3 "$port/open-variant/boot/assemble-open-image.py" \
    --gpt-dir "$stage/gpt" --prefix "$prefix" --boot-dir "$stage/boot" \
    --cache "$board/cache.raw.img" \
    --super "$temporary/super.raw.img" --output "$stage/pixel2-open-desktop-probe.img"
sgdisk --verify "$stage/pixel2-open-desktop-probe.img"
mv -nT -- "$stage" "$output"
if [[ -e "$stage" ]]; then
    printf 'Another process created the output directory: %s\n' "$output" >&2
    exit 1
fi
printf 'Verified offline desktop probe at %s\n' "$output/pixel2-open-desktop-probe.img"
