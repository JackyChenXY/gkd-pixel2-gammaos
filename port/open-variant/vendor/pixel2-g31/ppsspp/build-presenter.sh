#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail
if [[ $# != 3 ]]; then
    echo "Usage: $0 <built Android board sources> <built pixel2-g31 directory> <jniLibs/armeabi-v7a destination>" >&2
    exit 2
fi
sdk=$(realpath "$1")
driver=$(realpath "$2")
mkdir -p "$3"
out=$(realpath "$3")
src=$(cd "$(dirname "$0")" && pwd)
compiler="$sdk/prebuilts/clang/host/linux-x86/clang-r416183b1"
sysroot="$sdk/out/soong/ndk/sysroot"
bionic="$sdk/out/soong/.intermediates/bionic/libc"
arch=android_arm_armv8-a_cortex-a53
system_lib="$sdk/out/target/product/gkd_pixel2/system/lib"
libc_stubs="$sdk/out/target/product/gkd_pixel2/obj/SHARED_LIBRARIES/libc_intermediates"
"$compiler/bin/clang" --target=armv7a-linux-androideabi31 --sysroot="$sysroot" \
    -isystem "$sysroot/usr/include/arm-linux-androideabi" -I"$src/.." \
    -isystem "$sdk/frameworks/native/libs/nativewindow/include" -isystem "$sdk/system/core/libsystem/include" \
    -isystem "$sdk/frameworks/native/libs/nativebase/include" -isystem "$sdk/system/core/libcutils/include" \
    -Wall -Wextra -Werror -std=gnu11 -O2 -fPIC \
    -fuse-ld=lld -shared -nostdlib -Wl,--as-needed -Wl,--no-undefined -Wl,-soname,libpixel2_ppsspp.so \
    "$bionic/crtbegin_so/$arch/crtbegin_so.o" "$src/presenter.c" \
    -L"$driver" -L"$system_lib" -L"$libc_stubs" -lpixel2_g31_android -lpixel2_g31 \
    -lmediandk -landroid -lnativewindow -llog "$compiler/lib64/clang/12.0.7/lib/linux/libclang_rt.builtins-arm-android.a" -lc \
    "$bionic/crtend_so/$arch/obj/bionic/libc/arch-common/bionic/crtend_so.o" -o "$out/libpixel2_ppsspp.so"
cp "$driver/libpixel2_g31.so" "$driver/libpixel2_g31_android.so" "$out/"
