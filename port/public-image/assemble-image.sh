#!/usr/bin/env bash
# Build a fresh whole-card image from regular files, without opening a card reader.
set -euo pipefail
if (( $# != 10 )); then
  echo "Usage: $0 SDK BOOT_PREFIX KERNEL DTB BOARD_IMAGES SYSTEM VENDOR MUSL_CC LINUX_HEADERS NEW_OUTPUT_DIR" >&2
  exit 2
fi
here=$(cd -- "$(dirname -- "$0")" && pwd)
port=$(cd "$here/.." && pwd)
sdk=$(realpath -e "$1"); prefix=$(realpath -e "$2"); kernel=$(realpath -e "$3"); dtb=$(realpath -e "$4")
board=$(realpath -e "$5"); system=$(realpath -e "$6"); vendor=$(realpath -e "$7")
musl_cc=$(realpath -e "$8"); headers=$(realpath -e "$9")
output=$(realpath -m "${10}")
mkdir -- "$output"
mkdir "$output/board"
for name in cache.raw.img vendor_dlkm.raw.img odm.raw.img odm_dlkm.raw.img; do
  ln -s -- "$board/$name" "$output/board/$name"
done
ln -s -- "$vendor" "$output/board/vendor.raw.img"
python3 "$port/make-pixel2-test-gpt.py" 7516192768 "$output/gpt" > "$output/layout.log"
python3 "$here/make-boot.py" --gpt "$output/gpt" --musl-cc "$musl_cc" --kernel-headers "$headers" \
  --base-ramdisk "$board/ramdisk.img" --output "$output/ramdisk.uimg"
python3 "$port/open-variant/boot/prepare_boot_files.py" --kernel "$kernel" --dtb "$dtb" \
  --ramdisk "$output/ramdisk.uimg" --output "$output/boot"
python3 "$port/prepare-pixel2-gamma-direct-super.py" --board-dir "$output/board" --system "$system" \
  --tools "$sdk/out/host/linux-x86/bin" --output "$output/super.raw.img"
PYTHONDONTWRITEBYTECODE=1 python3 "$port/open-variant/boot/assemble-open-image.py" \
  --gpt-dir "$output/gpt" --prefix "$prefix" --boot-dir "$output/boot" --cache "$board/cache.raw.img" \
  --super "$output/super.raw.img" --output "$output/GKD-Pixel2-GammaOS.img"
sgdisk -v "$output/GKD-Pixel2-GammaOS.img"
