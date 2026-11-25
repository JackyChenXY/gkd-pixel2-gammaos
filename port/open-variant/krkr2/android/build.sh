#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
src=${PIXEL2_AOSP:?set PIXEL2_AOSP to the built Rockchip Android 12 source tree}
cc="$src/prebuilts/clang/host/linux-x86/clang-r416183b1/bin/clang"
sys="$src/out/soong/ndk/sysroot"
prod="$src/out/target/product/gkd_pixel2/system/lib"
stub="$src/out/target/product/gkd_pixel2/obj/SHARED_LIBRARIES"
crt="$src/out/soong/.intermediates/bionic/libc"
arch=android_arm_armv8-a_cortex-a53
common=(--target=armv7a-linux-androideabi31 --sysroot="$sys" -isystem "$sys/usr/include/arm-linux-androideabi" -Wall -Wextra -Werror -Os -fPIC)
lnk=(--target=armv7a-linux-androideabi31 -fuse-ld=lld -nostdlib -L"$prod" -L"$prod/../apex/com.android.runtime/lib/bionic" -L"$stub/libc_intermediates" -L"$stub/libdl_intermediates")
mkdir -p out classes test dex
"$cc" "${common[@]}" -c bootstrap.c -o bootstrap.o
"$cc" "${lnk[@]}" -shared -Wl,-soname,libpixel2_krkr_bootstrap.so,-z,now,-z,relro,--no-undefined bootstrap.o -llog -ldl_android -ldl -lc -o out/libpixel2_krkr_bootstrap.so
"$cc" "${common[@]}" -DPIXEL2_HOST_PROBE=1 -c bootstrap.c -o probe.o
"$cc" "${lnk[@]}" -pie -Wl,--dynamic-linker,/system/bin/linker "$crt/crtbegin_dynamic/$arch/crtbegin_dynamic.o" probe.o -llog -ldl_android -ldl -lc "$crt/crtend_android/$arch/obj/bionic/libc/arch-common/bionic/crtend.o" -o probe
pub="$src/prebuilts/sdk/31/public/android.jar"
api="$src/out/soong/.intermediates/frameworks/base/framework-minus-apex/android_common/turbine-combined/framework-minus-apex.jar"
j="$src/prebuilts/jdk/jdk11/linux-x86/bin"
"$j/javac" --release 8 -classpath "$api:$pub" -d classes src/pixel2/platformtest/*.java
"$j/jar" cf compiled.jar -C classes .
"$j/java" -cp "$src/prebuilts/r8/r8.jar" com.android.tools.r8.D8 --min-api 26 --lib "$pub" --output dex compiled.jar
"$j/jar" cf out/official-software-decor.jar -C dex classes.dex
"$j/javac" --release 8 -classpath "classes:$pub" -d test GateTest.java
"$j/java" -cp "classes:test:$pub" pixel2.platformtest.GateTest
cp launch.sh out/
(cd out; sha256sum lib*.so official-software-decor.jar launch.sh > SHA256SUMS)
