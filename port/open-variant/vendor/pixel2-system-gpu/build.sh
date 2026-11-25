#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

if (( $# < 5 )); then
    echo "Usage: $0 SDK AOSP_ARM32_CROSS MESA_TAR_XZ LIBDRM_TAR_XZ NEW_DIRECTORY [SDK_UPPER ...]" >&2
    exit 2
fi
here=$(cd -- "$(dirname -- "$0")" && pwd)
sdk=$(realpath -e -- "$1")
cross=$(realpath -e -- "$2")
mesa=$(realpath -e -- "$3")
drm=$(realpath -e -- "$4")
work=$(realpath -m -- "$5")
shift 5
upper=()
for layer in "$@"; do upper+=(--upper "$(realpath -e -- "$layer")"); done
rgb_handle="$sdk/external/minigbm/cros_gralloc/cros_gralloc_handle.h"
verify() { printf '%s  %s\n' "$1" "$2" | sha256sum --check --status; }
verify e641ae27191d387599219694560d221b7feaa91c900bcec46bf444218ed66025 "$mesa"
verify a2b98567a149a74b0f50e91e825f9c0315d86e7be9b74394dae8b298caadb79e "$drm"
verify 02efa29f9d598e0d02fb3d103f5c4b0e339d193eb57b9cd9d7897500815638f1 "$rgb_handle"
mkdir -- "$work"
cd -- "$work"
tar -xf "$drm"
tar -xf "$mesa"
src="$work/mesa-24.3.4"
patch --batch --fuzz=0 -p1 -d "$src" < "$here/pixel2-mesa24.patch"
patch --batch --fuzz=0 -p1 -d "$src" < "$here/pixel2-es100-uniforms.patch"
cp -- "$here/pixel2-linear-rgb.cpp" "$rgb_handle" "$src/src/egl/drivers/dri2/"
python3 "$here/prepare-cross.py" "$sdk" "$cross" "$work" "${upper[@]}"
meson=(python3 -m mesonbuild.mesonmain)
ninja=${NINJA:-ninja}
jobs=${JOBS:-8}
"${meson[@]}" setup drm-build libdrm-2.4.123 --cross-file android-arm.ini \
    --buildtype=release --prefix="$work/drm-install" --libdir=lib \
    --default-library=static -Dauto_features=disabled -Dtests=false \
    -Dinstall-test-programs=false -Dudev=false
"$ninja" -C drm-build -j"$jobs" install
"${meson[@]}" setup mesa-build "$src" --cross-file android-arm.ini \
    --buildtype=release --prefix=/vendor --libdir=lib -Dauto_features=disabled \
    -Dplatforms=android -Dplatform-sdk-version=32 -Dgallium-drivers=panfrost \
    -Dvulkan-drivers= -Degl=enabled -Dgles1=enabled -Dgles2=enabled -Dgbm=enabled \
    -Dopengl=true -Dglx=disabled -Dllvm=disabled -Dshared-glapi=enabled \
    -Dshader-cache=enabled -Dandroid-libbacktrace=disabled -Dcpp_rtti=false \
    -Degl-lib-suffix=_mesa -Dgles-lib-suffix=_mesa
"$ninja" -C mesa-build -j"$jobs"
"${meson[@]}" install -C mesa-build --no-rebuild --strip --destdir "$work/install"

stage="$work/install/vendor/lib"
for lib in libEGL_mesa libGLESv1_CM_mesa libGLESv2_mesa libglapi libgallium_dri; do
    test -f "$stage/$lib.so"
    if readelf -d "$stage/$lib.so" | grep -E '\((RPATH|RUNPATH)\)'; then
        echo "Unwanted build-time library path in $lib" >&2
        exit 1
    fi
done
(cd "$stage" && sha256sum libEGL_mesa.so libGLESv1_CM_mesa.so libGLESv2_mesa.so libglapi.so libgallium_dri.so) > "$work/graphics.sha256"
cat "$work/graphics.sha256"
