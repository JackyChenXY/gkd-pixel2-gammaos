#!/usr/bin/env bash
# Build the Pixel 2 virtual-memory update against the prepared GammaOS source.
set -eo pipefail
project=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
gamma=${GAMMA_SOURCE:?Set GAMMA_SOURCE to your prepared GammaOS checkout}
sdk=${PIXEL2_SDK:?Set PIXEL2_SDK to your Rockchip Android SDK checkout}
output=${PIXEL2_SWAP_OUTPUT:-"$project/build-output/gammaos/virtual-memory"}
assets="$project/pixel2-device/extra-swap"
patches=("$project/pixel2-gamma-extra-swap-settings.patch" "$project/pixel2-gamma-extra-swap-shutdown.patch")
board=device/phh/treble/pixel2
policy=device/phh/treble/sepolicy

cd "$gamma"
test "$(git rev-parse HEAD)" = b2db9cfe308c8753e3385b8ab64bcb34c3177177
git apply --check "${patches[@]}"
mkdir -p -- "$output"
test ! -e "$output/system.img"
modified=("$board/product.mk" "$board/pixel2-zram.rc" "$policy/file_contexts" "$policy/property_contexts")
added=("$board/Android.mk" "$board/pixel2-extra-swap" "$board/pixel2-extra-swap.rc" "$policy/pixel2_extra_swap.te")
for path in "${added[@]}"; do
    test ! -e "$path"
done
saved=$(mktemp -d)
patch_applied=false
cleanup() {
    local code=$?
    trap - EXIT
    if $patch_applied; then git apply --reverse "${patches[@]}" || code=1; fi
    for path in "${modified[@]}"; do
        if [[ -f "$saved/$path" ]]; then cp -p -- "$saved/$path" "$path" || code=1; fi
    done
    rm -f -- "${added[@]}"
    rm -rf -- "$saved"
    exit "$code"
}
trap cleanup EXIT
for path in "${modified[@]}"; do cp -p --parents -- "$path" "$saved"; done

gcc="$sdk/prebuilts/gcc/linux-x86/aarch64/gcc-arm-10.2-2020.11-x86_64-aarch64-none-linux-gnu/bin/aarch64-none-linux-gnu-gcc"
"$gcc" -std=gnu17 -Wall -Wextra -Wformat=2 -Werror -Os -static -s \
    -idirafter "$sdk/bionic/libc/kernel/uapi" "$assets/pixel2-extra-swap.c" -o "$board/pixel2-extra-swap"
readelf -h "$board/pixel2-extra-swap" | grep -q 'Machine:.*AArch64'
cp -- "$assets/pixel2-extra-swap.rc" "$board/"
cp -- "$assets/policy/pixel2_extra_swap.te" "$policy/"
for name in file_contexts property_contexts; do
    printf '\n' >> "$policy/$name"
    cat -- "$assets/policy/$name" >> "$policy/$name"
done

cat > "$board/Android.mk" <<'MAKE'
LOCAL_PATH := $(call my-dir)

include $(CLEAR_VARS)
LOCAL_MODULE := pixel2-extra-swap
LOCAL_MODULE_CLASS := EXECUTABLES
LOCAL_MODULE_TAGS := optional
LOCAL_SRC_FILES := pixel2-extra-swap
LOCAL_STRIP_MODULE := false
LOCAL_CHECK_ELF_FILES := false
include $(BUILD_PREBUILT)
MAKE
cat >> "$board/product.mk" <<'MAKE'

PRODUCT_PACKAGES += pixel2-extra-swap
PRODUCT_SYSTEM_PROPERTIES += ro.pixel2.extra_swap.supported=true
PRODUCT_COPY_FILES += \
    device/phh/treble/pixel2/pixel2-extra-swap.rc:system/etc/init/pixel2-extra-swap.rc
MAKE
sed -i 's/property:ro.gsid.image_running=1 && //g' "$board/pixel2-zram.rc"
cmp -- "$board/pixel2-zram.rc" "$project/gamma-board/standalone-zram.rc"
git apply "${patches[@]}"
patch_applied=true

export OUT_DIR="$gamma/out-pixel2-gamma"
export BUILD_NUMBER=GKD20261118G4
export OVERRIDE_BUILD_NUMBER="$BUILD_NUMBER"
source build/envsetup.sh
lunch lineage_a64_bvN-userdebug
"$OUT_DIR/host/linux-x86/bin/host_init_verifier" "$board/pixel2-extra-swap.rc"
if ! m -j8 systemimage > "$output/build.log" 2>&1; then
    tail -n 70 "$output/build.log"
    exit 1
fi
tail -n 14 "$output/build.log"
image="$OUT_DIR/target/product/phhgsi_a64_ab/system.img"
stage="$output/system.img.building"
test ! -e "$stage"
cp -- "$image" "$stage"
cmp -- "$image" "$stage"
for pair in "bin/pixel2-extra-swap pixel2-extra-swap" \
            "etc/init/pixel2-extra-swap.rc pixel2-extra-swap.rc" \
            "etc/init/pixel2-zram.rc pixel2-zram.rc"; do
    read -r path name <<< "$pair"
    debugfs -R "dump /system/$path $saved/check-$name" "$stage" 2>/dev/null
    cmp -- "$board/$name" "$saved/check-$name"
done
debugfs -R 'cat /system/build.prop' "$stage" 2>/dev/null > "$saved/build.prop"
grep -Fx 'ro.pixel2.extra_swap.supported=true' "$saved/build.prop"
e2fsck -fn "$stage"
mv -T -- "$stage" "$output/system.img"
sha256sum "$output/system.img"
