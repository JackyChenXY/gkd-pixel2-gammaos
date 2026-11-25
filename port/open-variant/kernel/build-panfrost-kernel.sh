#!/usr/bin/env bash
set -euo pipefail

if (( $# < 3 || $# > 4 )); then
    printf 'Usage: %s ANDROID_SDK KERNEL_SOURCE_BUNDLE NEW_BUILD_DIRECTORY [engineering|fcm6-probe]\n' "$0" >&2
    exit 2
fi

variant=$(cd -- "$(dirname -- "$0")" && pwd)
port=$(cd -- "$variant/../.." && pwd)
case "${4:-engineering}" in
    engineering) requirements= ;;
    fcm6-probe) requirements="$variant/android12-fcm6.config" ;;
    *)
        printf 'Unknown kernel profile: %s\n' "$4" >&2
        exit 2
        ;;
esac
sdk=$(realpath -e -- "$1")
bundle=$(realpath -e -- "$2")
parent=$(realpath -e -- "$(dirname -- "$3")")
output="$parent/$(basename -- "$3")"
clang="$sdk/prebuilts/clang/host/linux-x86/clang-r416183b1/bin"
cross="$sdk/prebuilts/gcc/linux-x86/aarch64/gcc-linaro-6.3.1-2017.05-x86_64_aarch64-linux-gnu/bin/aarch64-linux-gnu-"

if [[ ! -x "$clang/clang" || ! -x "${cross}gcc" ]]; then
    printf 'The SDK must contain the same Clang and GCC prebuilts as the Pixel 2 BSP kernel.\n' >&2
    exit 1
fi

printf '%s  %s\n' 70fbf33005141def3d4da4e4dd175d150be46e131f5c7ebfddfb50aecdfef156 "$bundle" | sha256sum --check
mkdir -- "$output"
tar -xzf "$bundle" --strip-components=1 -C "$output"
source="$output/source"
build="$output/out"
dt_directory="$source/arch/arm64/boot/dts/rockchip"
dtb_name=rk3326s-gkd-pixel2-open
mkdir -- "$build"
install -m 644 "$port/kernel-inputs/rk3326s-gkd-pixel2.dts" "$dt_directory/rk3326s-gkd-pixel2.dts"
install -m 644 "$variant/$dtb_name.dts" "$dt_directory/$dtb_name.dts"
cp -- "$output/pixel2-release.config" "$build/.config"

bash "$source/scripts/config" --file "$build/.config" \
    --disable MALI_BIFROST --disable MALI_MIDGARD --enable DRM_PANFROST \
    --enable CRYPTO_CHACHA20POLY1305 \
    --set-str LOCALVERSION '-pixel2-panfrost' --disable LOCALVERSION_AUTO
if [[ -n "$requirements" ]]; then
    ARCH=arm64 "$source/scripts/kconfig/merge_config.sh" -m -O "$build" "$build/.config" "$requirements"
fi
export PATH="$clang:$PATH"
export KBUILD_BUILD_USER=pixel2-build KBUILD_BUILD_HOST=pixel2-builder KBUILD_BUILD_VERSION=1
export KBUILD_BUILD_TIMESTAMP='Thu Jan 1 00:00:00 UTC 1970'
make_kernel=(make -C "$source" O="$build" ARCH=arm64 CROSS_COMPILE="$cross" LLVM=1 LLVM_IAS=1)
"${make_kernel[@]}" olddefconfig

for option in DRM_PANFROST DRM_ROCKCHIP DRM_PANEL_SIMPLE KEYBOARD_GPIO \
    ANDROID_BINDER_IPC ANDROID_BINDERFS EXT4_FS F2FS_FS FS_ENCRYPTION_INLINE_CRYPT \
    DM_DEFAULT_KEY CRYPTO_CHACHA20POLY1305 BPF_SYSCALL CGROUP_BPF SECURITY_SELINUX; do
    grep -Fx "CONFIG_$option=y" "$build/.config"
done
for option in MALI_BIFROST MALI_MIDGARD; do
    grep -Fx "# CONFIG_$option is not set" "$build/.config"
done
grep -Fx 'CONFIG_EXTRA_FIRMWARE=""' "$build/.config"

"${make_kernel[@]}" -j"${JOBS:-8}" Image "rockchip/$dtb_name.dtb"
dtb="$build/arch/arm64/boot/dts/rockchip/$dtb_name.dtb"
test "$(fdtget -t s "$dtb" / model)" = 'GameKiddy GKD Pixel2'
test "$(fdtget -t s "$dtb" /aliases mmc0)" = /dwmmc@ff370000
test "$(fdtget -t s "$dtb" /gpu@ff400000 compatible)" = 'rockchip,px30-mali arm,mali-bifrost'
test "$(fdtget -t s "$dtb" /gpu@ff400000 interrupt-names)" = 'gpu mmu job'
test "$(fdtget -t s "$dtb" /gpu@ff400000 status)" = 'okay'
test "$(fdtget -t s "$dtb" /rocknix-singleadc-joypad compatible)" = gpio-keys
test "$(fdtget -t s "$dtb" /rocknix-singleadc-joypad label)" = gkd_pixel2_joypad
test "$(fdtget -t u "$dtb" /rocknix-singleadc-joypad/sw9 linux,code)" = 704
test "$(fdtget -t u "$dtb" /dsi@ff450000/panel@0 rotation)" = 90
test "$(fdtget -t u "$dtb" /dsi@ff450000/panel@0/display-timings/timing0 hactive)" = 480
test "$(fdtget -t u "$dtb" /dsi@ff450000/panel@0/display-timings/timing0 vactive)" = 640

for table in cpu0-opp-table px30s-cpu0-opp-table; do
    nodes=$(fdtget -l "$dtb" "/$table")
    grep -qx 'opp-1416000000' <<< "$nodes"
    if grep -qx 'opp-1512000000' <<< "$nodes"; then
        printf 'Unexpected 1.512 GHz entry in /%s.\n' "$table" >&2
        exit 1
    fi
done
sha256sum "$build/arch/arm64/boot/Image" "$dtb"
