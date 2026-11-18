#!/usr/bin/env bash
set -euo pipefail

android_root=${ANDROID_ROOT:?Set ANDROID_ROOT to your Rockchip Android SDK checkout}
project=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
build="$android_root/work/build/pixel2-kernel-5.10-bsp"
source="$build/source"
out="$build/out"
android_base="$build/android12-5.10-base.config"
export PATH="$android_root/prebuilts/clang/host/linux-x86/clang-r416183b1/bin:$PATH"
cross="$android_root/prebuilts/gcc/linux-x86/aarch64/gcc-linaro-6.3.1-2017.05-x86_64_aarch64-linux-gnu/bin/aarch64-linux-gnu-"

cd -- "$build"
sha256sum --check <<'EOF'
a0225d92b51c4a46ca0415afc3b39e726ef5ee8918559970731f68c8be0bc919  pixel2-bsp.config
bc61b7eb6facbbc253c98de2943d2c49b36298b2d2b63b79c8efd146b6257a9b  rk3326s-gkd-pixel2.dts
1299f2a7f997995eedd1597f064d70788b721ce58325ecf44f8ecec1aa5264b1  android12-5.10-base.config
EOF

for patch_file in "$project/pixel2-primary-scanout.patch" "$project/pixel2-rk817-dsoc.patch"; do
    if patch --dry-run --silent --batch --forward --fuzz=0 -d "$source" -p1 < "$patch_file" > /dev/null 2>&1; then
        patch --batch --forward --fuzz=0 -d "$source" -p1 < "$patch_file"
    else
        patch --dry-run --silent --batch --forward --reverse --fuzz=0 -d "$source" -p1 < "$patch_file"
    fi
done

mkdir -p -- "$out"
dt_source="$source/arch/arm64/boot/dts/rockchip/rk3326s-gkd-pixel2.dts"
cat rk3326s-gkd-pixel2.dts > "$dt_source"
# Some Pixel 2 units reset at 1.512 GHz. Limit both selectable CPU tables.
cat >> "$dt_source" <<'EOF'

&cpu0_opp_table {
	/delete-node/ opp-1512000000;
};

&px30s_cpu0_opp_table {
	/delete-node/ opp-1512000000;
};
EOF

make_kernel=(make -C "$source" O="$out" ARCH=arm64 CROSS_COMPILE="$cross" LLVM=1 LLVM_IAS=1)
# Enable the networking features required by the pinned Android 12 kernel config.
grep -E '^CONFIG_(DUMMY|PACKET|TUN|VETH|(BPF|CGROUP_BPF|INET6?|IP6|IP|IPV6|NF|NETFILTER|NET|XFRM)(_[A-Z0-9]+)*)=y$' \
    "$android_base" > "$out/android-network.config"
"$source/scripts/kconfig/merge_config.sh" -m -O "$out" \
    "$build/pixel2-bsp.config" "$out/android-network.config" "$project/pixel2-android-5.10.config"
"${make_kernel[@]}" olddefconfig

# Check built-in drivers after Kconfig resolves dependencies.
for option in ARM64 COMPAT BLK_DEV_INITRD RD_GZIP DEVTMPFS EFI_PARTITION \
    MMC MMC_BLOCK MMC_DW MMC_DW_ROCKCHIP VFAT_FS NLS_CODEPAGE_437 NLS_ISO8859_1 \
    VT FRAMEBUFFER_CONSOLE DRM_ROCKCHIP ROCKCHIP_DW_MIPI_DSI DRM_PANEL_SIMPLE \
    ANDROID_BINDER_IPC ANDROID_BINDERFS ASHMEM SECURITY_SELINUX MEMCG BPF_SYSCALL \
    BLK_DEV_DM DM_DEFAULT_KEY EXT4_FS F2FS_FS FS_ENCRYPTION_INLINE_CRYPT \
    USB_DWC2 USB_CONFIGFS USB_CONFIGFS_F_FS \
    IP_MULTIPLE_TABLES IPV6_MULTIPLE_TABLES INET_DIAG INET_DIAG_DESTROY \
    IP_NF_FILTER IP_NF_RAW IP_NF_MANGLE IP_NF_NAT IP6_NF_FILTER IP6_NF_RAW IP6_NF_MANGLE \
    NETFILTER_NETLINK NETFILTER_NETLINK_LOG NETFILTER_XT_TARGET_NFLOG NETFILTER_XT_MATCH_QUOTA2_LOG \
    NETFILTER_XT_MATCH_BPF NETFILTER_XT_MATCH_MARK BLK_CGROUP INCREMENTAL_FS; do
    if ! grep -qx "CONFIG_$option=y" "$out/.config"; then
        printf 'Missing required built-in CONFIG_%s\n' "$option" >&2
        exit 1
    fi
done
if ! grep -Eq '^CONFIG_LSM="([^"]*,)?selinux(,[^"]*)?"$' "$out/.config"; then
    printf 'SELinux is missing from the enabled security module list.\n' >&2
    exit 1
fi

"${make_kernel[@]}" -j"${JOBS:-24}" rockchip/rk3326s-gkd-pixel2.dtb Image
