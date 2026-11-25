#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 || $# -gt 3 ]] || (( EUID != 0 )); then
    printf 'Usage: run as root: %s SDK SCRATCH [--images|--resume-images]\n' "$0" >&2
    exit 2
fi

sdk=$(realpath -e -- "$1")
parent=$(realpath -e -- "$2")
scripts=$(realpath -- "$(dirname -- "$0")")
builder=$(stat -c '%U' -- "$sdk")
mode=$(if [[ $# -eq 3 ]]; then printf '%s' "$3"; else printf '%s' --modules; fi)
if [[ "$mode" != --modules && "$mode" != --images && "$mode" != --resume-images ]]; then
    printf 'Unknown stage: %s\n' "$mode" >&2
    exit 2
fi
if [[ ! -f "$sdk/build/envsetup.sh" || ! -d "$parent" || "$builder" == root ]]; then
    printf 'Expected a configured SDK owned by the non-root build user and an existing scratch directory.\n' >&2
    exit 1
fi
if [[ "$parent/" == "$sdk/"* || "$sdk" == *[:,]* || "$parent" == *[:,]* ]]; then
    printf 'Use a scratch path outside the SDK. Overlay paths cannot contain colons or commas.\n' >&2
    exit 1
fi

if [[ "$mode" == --resume-images ]]; then
    scratch=$parent
    if [[ ! -d "$scratch/upper" || ! -d "$scratch/work" || ! -f "$scratch/sdk-path.txt" ]] ||
        [[ "$(cat "$scratch/sdk-path.txt")" != "$sdk" ]] ||
        ! grep -q 'build completed successfully' "$scratch/build.log"; then
        printf 'Expected the scratch directory of a successful module build for this SDK.\n' >&2
        exit 1
    fi
else
    scratch=$(mktemp -d "$parent/pixel2-vendor.XXXXXXXX")
    chmod 0755 "$scratch"
    mkdir "$scratch/upper" "$scratch/work"
    chown "$builder" "$scratch" "$scratch/upper"
    printf '%s\n' "$sdk" > "$scratch/sdk-path.txt"
fi
exec 9>"$scratch/build.lock"
flock -n 9 || {
    printf 'Another build uses %s\n' "$scratch" >&2
    exit 1
}
printf 'Isolated build output: %s\n' "$scratch"

unshare -m --propagation private -- bash -s -- "$sdk" "$scratch" "$scripts" "$builder" "$mode" <<'NAMESPACE'
set -euo pipefail
sdk=$1
scratch=$2
scripts=$3
builder=$4
mode=$5
mount -t overlay overlay -o "lowerdir=$sdk,upperdir=$scratch/upper,workdir=$scratch/work" "$sdk"
trap 'umount -- "$sdk"' EXIT

# Establish that the private mount redirects writes before changing source.
probe=".pixel2-overlay-$(basename -- "$scratch")"
runuser -u "$builder" -- touch -- "$sdk/$probe"
test -f "$scratch/upper/$probe"
runuser -u "$builder" -- rm -- "$sdk/$probe"

if [[ "$mode" != --resume-images ]]; then
    runuser -u "$builder" -- python3 "$scripts/apply-profile.py" --apply "$sdk"

    if [[ "$mode" == --images ]]; then
        runuser -u "$builder" -- python3 "$scripts/apply-profile.py" --apply --prune "$sdk"
        touch -- "$scratch/pruned.txt"
    fi
    runuser -u "$builder" -- env OUT_DIR=out PIXEL2_SDK="$sdk" PIXEL2_SCRATCH="$scratch" bash -s <<'BUILD'
set -eo pipefail
cd "$PIXEL2_SDK"
source build/envsetup.sh
lunch gkd_pixel2-userdebug
vendor=out/target/product/gkd_pixel2/vendor
m -j8 "$vendor/bin/hw/android.hardware.graphics.allocator@4.0-service.minigbm" \
    "$vendor/lib/hw/android.hardware.graphics.mapper@4.0-impl.minigbm.so" \
    "$vendor/bin/hw/android.hardware.graphics.composer@2.4-service" \
    "$vendor/lib/hw/hwcomposer.drm_minigbm.so" \
    "$vendor/bin/hw/android.hardware.keymaster@4.0-service" \
    "$vendor/bin/hw/android.hardware.gatekeeper@1.0-service.software" \
    "$vendor/lib/egl/libEGL_swiftshader.so" "$vendor/lib/egl/libGLESv1_CM_swiftshader.so" \
    "$vendor/lib/egl/libGLESv2_swiftshader.so" \
    > "$PIXEL2_SCRATCH/build.log" 2>&1 || {
    tail -60 "$PIXEL2_SCRATCH/build.log"
    exit 1
}
tail -25 "$PIXEL2_SCRATCH/build.log"
BUILD
fi

if [[ "$mode" != --modules ]]; then
    if [[ ! -f "$scratch/pruned.txt" ]]; then
        runuser -u "$builder" -- python3 "$scripts/apply-profile.py" --apply --prune "$sdk"
        touch -- "$scratch/pruned.txt"
    fi
    cd -- "$sdk"
    runuser -u "$builder" -- env OUT_DIR=out PIXEL2_OVERLAY_UPPER="$scratch/upper" \
        bash "$scripts/emit-partitions.sh" "$scratch/export" > "$scratch/images.log" 2>&1 || {
        tail -70 "$scratch/images.log"
        exit 1
    }
    tail -30 "$scratch/images.log"
    # Leave the mounted working directory before the EXIT unmount.
    cd /
fi
NAMESPACE
