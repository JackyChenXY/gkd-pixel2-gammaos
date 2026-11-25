#!/usr/bin/env bash
# Run inside the private SDK overlay once the module build is complete.
set -eo pipefail

if [[ $# -ne 1 || -z "${PIXEL2_OVERLAY_UPPER:-}" ]] ||
    ! findmnt -n -o OPTIONS --mountpoint "$PWD" | tr ',' '\n' |
        grep -Fx "upperdir=$PIXEL2_OVERLAY_UPPER" >/dev/null; then
    printf 'Run from the SDK root inside its verified private overlay: %s NEW_EXPORT_DIRECTORY\n' "$0" >&2
    exit 2
fi
export_dir=$(realpath -m -- "$1")
board=out/target/product/gkd_pixel2
board_root=$(realpath -e -- "$board")
if [[ "$board_root" != "$PWD/$board" || -e "$export_dir" || -L "$export_dir" ]]; then
    printf 'Expected the in-overlay product staging directory and a new export directory.\n' >&2
    exit 1
fi
partitions=(vendor odm vendor_dlkm odm_dlkm cache)
# Incremental module installation can leave removed binary blobs in the old
# staging trees. Reinstall the complete product selection before packaging.
for part in vendor odm vendor_dlkm odm_dlkm; do
    if [[ "$(realpath -m -- "$board/$part")" != "$board_root/$part" ]]; then
        printf 'Refusing to clear redirected staging path: %s\n' "$board/$part" >&2
        exit 1
    fi
    rm -rf -- "$board/$part"
    rm -f -- "$board/$part.img"
done

source build/envsetup.sh
lunch gkd_pixel2-userdebug
m -j8 vendorimage odmimage vendor_dlkmimage odm_dlkmimage \
    cacheimage bootimage recoveryimage "$board/ramdisk.img"

temporary=$(mktemp -d -- "$(dirname -- "$export_dir")/.pixel2-vendor-export.XXXXXXXX")
trap 'rm -rf -- "$temporary"' EXIT
for part in "${partitions[@]}"; do
    source_image="$board/$part.img"
    raw_image="$temporary/$part.raw.img"
    if [[ "$(od -An -tx1 -N4 "$source_image" | xargs)" == '3a ff 26 ed' ]]; then
        out/host/linux-x86/bin/simg2img "$source_image" "$raw_image"
    else
        cp --sparse=always -- "$source_image" "$raw_image"
    fi
    e2fsck -nf "$temporary/$part.raw.img"
done
for file in boot.img recovery.img ramdisk.img rebuild-dtbo.img; do
    install -m 0644 -- "$board/$file" "$temporary/$file"
done
gzip -t "$temporary/ramdisk.img"

(
    cd "$temporary"
    sha256sum -- ./*.img > SHA256SUMS
)
mv -nT -- "$temporary" "$export_dir"
if [[ -e "$temporary" ]]; then
    printf 'Export path already exists: %s\n' "$export_dir" >&2
    exit 1
fi
printf 'Prepared diagnostic vendor images and boot payloads in %s\n' "$export_dir"
