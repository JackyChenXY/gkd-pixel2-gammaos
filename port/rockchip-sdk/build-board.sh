#!/usr/bin/env bash
# Build the SDK board images in a dedicated pinned Rockchip Android checkout.
set -euo pipefail

if [[ $# -ne 1 ]]; then
    printf 'Usage: ANDROID_ROOT=/path/to/rockchip-sdk %s STOCK_PIXEL2.dtb\n' "$0" >&2
    exit 2
fi

board_source=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
sdk=$(cd -- "${ANDROID_ROOT:?Set ANDROID_ROOT to a dedicated Rockchip SDK checkout}" && pwd)
kernel="$sdk/kernel-4.19"
out="$sdk/work/build/pixel2-kernel-4.19-android12"
device="$sdk/device/gamekiddy/gkd_pixel2"
cross="$sdk/prebuilts/gcc/linux-x86/aarch64/gcc-linaro-6.3.1-2017.05-x86_64_aarch64-linux-gnu/bin/aarch64-linux-gnu-"
jobs=${JOBS:-8}
config_dir="$sdk/mkcombinedroot/configs"
patch="$board_source/rk3326-sdk-kernel.patch"

if [[ $(git -C "$kernel" rev-parse HEAD) != c1ddb442bd74c81a515f8688cbb5730b51a807df ]]; then
    printf 'Unexpected SDK kernel revision. Sync the pinned manifest first.\n' >&2
    exit 1
fi
if [[ ! -x "${cross}gcc" ]]; then
    printf 'SDK GCC is absent or still stored as a Git LFS pointer.\n' >&2
    exit 1
fi

mkdir -p -- "$out"
stage=$(mktemp -d "$out/stage.XXXXXXXX")
trap 'rm -rf -- "$stage"' EXIT
python3 "$board_source/render-board-dts.py" "$1" "$stage/rk3326-gkd-pixel2.dts"

install_file() {
    local source=$1 destination=$2
    if [[ -e "$destination" ]] && ! cmp -s -- "$source" "$destination"; then
        printf 'Conflicting SDK file: %s\n' "$destination" >&2
        return 1
    fi
    if [[ ! -f "$destination" ]]; then
        install -D -m 0644 -- "$source" "$destination"
    fi
}

if git -C "$kernel" apply --check "$patch" 2>/dev/null; then
    git -C "$kernel" apply "$patch"
else
    git -C "$kernel" apply --reverse --check "$patch"
fi

while IFS= read -r -d '' file; do
    install_file "$file" "$device/${file#"$board_source/device/"}"
done < <(find "$board_source/device" -type f -print0)
install_file "$sdk/device/rockchip/rk3326/rk3326_sgo/media_profiles_default.xml" \
    "$device/media_profiles_default.xml"
install_file "$board_source/gkd_pixel2.config" "$config_dir/gkd_pixel2.config"
install_file "$stage/rk3326-gkd-pixel2.dts" "$kernel/arch/arm64/boot/dts/rockchip/rk3326-gkd-pixel2.dts"

make_kernel=(make -C "$kernel" O="$out" ARCH=arm64 CROSS_COMPILE="$cross")
"${make_kernel[@]}" rockchip_defconfig
ARCH=arm64 "$kernel/scripts/kconfig/merge_config.sh" -m -O "$out" \
    "$out/.config" "$config_dir/android-11-go.config" \
    "$config_dir/disable_incfs.config" "$config_dir/gkd_pixel2.config"
"${make_kernel[@]}" olddefconfig
warn_flags='-Wno-error=unused-function -Wno-error=unused-variable -Wno-error=declaration-after-statement'
"${make_kernel[@]}" -j"$jobs" KCFLAGS="$warn_flags" Image rockchip/rk3326-gkd-pixel2.dtb

kernel_image=arch/arm64/boot/Image
dtb=arch/arm64/boot/dts/rockchip/rk3326-gkd-pixel2.dtb
"$out/scripts/resource_tool" --pack --image="$stage/resource.img" "$out/$dtb"
install_file "$out/$kernel_image" "$kernel/$kernel_image"
install_file "$out/$dtb" "$kernel/$dtb"
install_file "$stage/resource.img" "$kernel/resource.img"

(
    cd -- "$sdk"
    # The pinned Android shell helpers refer to optional variables without defaults.
    set +u
    source build/envsetup.sh
    lunch gkd_pixel2-userdebug
    m -j"$jobs" droid simg2img lpmake lpdump lpunpack unpack_bootimg
)
