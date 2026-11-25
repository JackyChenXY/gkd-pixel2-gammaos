#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

if (( $# != 2 )); then
    echo "Usage: $0 /path/to/mesa-22.3.7 /path/to/output" >&2
    exit 2
fi
port=$(cd "$(dirname "$0")" && pwd)
mesa=$(realpath "$1")
[[ $(cat "$mesa/VERSION") == 22.3.7 ]]
mkdir -p "$2"
out=$(cd "$2" && pwd)
mkdir -p "$out/generated"
python3 "$mesa/src/panfrost/lib/genxml/gen_pack.py" "$mesa/src/panfrost/lib/genxml/v7.xml" >"$out/generated/v7_pack.h"

if [[ -n ${ANDROID_NDK_HOME:-} ]]; then
    tool="$ANDROID_NDK_HOME/toolchains/llvm/prebuilt/linux-x86_64/bin"
    compiler=("$tool/armv7a-linux-androideabi31-clang")
    so_start=(); so_end=(); exe_start=(); exe_end=()
elif [[ -n ${PIXEL2_ANDROID_SDK:-} ]]; then
    sdk=$(realpath "$PIXEL2_ANDROID_SDK")
    clang="$sdk/prebuilts/clang/host/linux-x86/clang-r416183b1"
    sysroot="$sdk/out/soong/ndk/sysroot"
    product="$sdk/out/target/product/gkd_pixel2/system/lib"
    bionic="$sdk/out/soong/.intermediates/bionic/libc"
    arch=android_arm_armv8-a_cortex-a53
    compiler=("$clang/bin/clang" --target=armv7a-linux-androideabi31
              "--sysroot=$sysroot" -isystem "$sysroot/usr/include/arm-linux-androideabi")
    builtins="$clang/lib64/clang/12.0.7/lib/linux/libclang_rt.builtins-arm-android.a"
    stubs="$sdk/out/target/product/gkd_pixel2/obj/SHARED_LIBRARIES"
    linker=(-fuse-ld=lld -nostdlib -Wl,--as-needed "-L$product" "-L$stubs/libc_intermediates"
            "-L$stubs/libm_intermediates" "-L$stubs/libdl_intermediates")
    so_start=("${linker[@]}" "$bionic/crtbegin_so/$arch/crtbegin_so.o")
    so_end=("$builtins" -lc -lm -ldl "$bionic/crtend_so/$arch/obj/bionic/libc/arch-common/bionic/crtend_so.o")
    exe_start=("${linker[@]}" "$bionic/crtbegin_dynamic/$arch/crtbegin_dynamic.o")
    exe_end=("$builtins" -lc -lm -ldl "$bionic/crtend_android/$arch/obj/bionic/libc/arch-common/bionic/crtend.o")
else
    echo 'Set ANDROID_NDK_HOME to a Linux NDK or PIXEL2_ANDROID_SDK to the built Pixel 2 Android SDK.' >&2
    exit 2
fi

flags=(-std=gnu11 -O2 -fPIC -Wall -Wextra -Werror -DNDEBUG -DHAVE_ENDIAN_H
       -isystem "$out/generated" -isystem "$mesa/include" -isystem "$mesa/include/drm-uapi"
       -isystem "$mesa/src" -isystem "$mesa/src/gallium/include" -isystem "$mesa/src/panfrost/include")
"${compiler[@]}" "${flags[@]}" -c "$port/g31.c" -o "$out/g31.o"
"${compiler[@]}" -shared -Wl,-soname,libpixel2_g31.so -Wl,--no-undefined "${so_start[@]}" "$out/g31.o" "${so_end[@]}" -o "$out/libpixel2_g31.so"
"${compiler[@]}" "${flags[@]}" -c "$port/selftest.c" -o "$out/selftest.o"
"${compiler[@]}" -pie "${exe_start[@]}" "$out/selftest.o" "-L$out" -lpixel2_g31 "${exe_end[@]}" -o "$out/pixel2-g31-test"

# The hardware-buffer adapter consumes this board's allocator ABI.
if [[ -n ${PIXEL2_ANDROID_SDK:-} ]]; then
    board=$(realpath "$PIXEL2_ANDROID_SDK")
    android_flags=(-isystem "$board/frameworks/native/libs/nativewindow/include"
                   -isystem "$board/system/core/libcutils/include"
                   -isystem "$board/external/minigbm/cros_gralloc")
    "${compiler[@]}" "${flags[@]}" -x c++ -std=c++17 -fno-exceptions -fno-rtti -nostdinc++ \
        -isystem "$board/external/libcxx/include" "${android_flags[@]}" -c "$port/android_surface.cpp" -o "$out/android_surface.o"
    board_libs="-L$board/out/target/product/gkd_pixel2/system/lib"
    "${compiler[@]}" -shared -Wl,-soname,libpixel2_g31_android.so -Wl,--no-undefined "${so_start[@]}" \
        "$out/android_surface.o" "-L$out" -lpixel2_g31 "$board_libs" -lnativewindow "${so_end[@]}" -o "$out/libpixel2_g31_android.so"
    "${compiler[@]}" "${flags[@]}" -c "$port/android_benchmark.c" -o "$out/android_benchmark.o"
    "${compiler[@]}" -pie "${exe_start[@]}" "$out/android_benchmark.o" "-L$out" -lpixel2_g31_android -lpixel2_g31 \
        "$board_libs" -lEGL -lGLESv2 -lnativewindow "${exe_end[@]}" -o "$out/pixel2-g31-bench"
fi
