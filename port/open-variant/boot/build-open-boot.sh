#!/usr/bin/env bash
# Build standard U-Boot and the source-based PX30 TF-A boot prefix.
set -euo pipefail

if (( $# != 1 )); then
    printf 'Usage: CROSS_COMPILE=aarch64-linux-gnu- %s BUILD_DIRECTORY\n' "$0" >&2
    exit 2
fi
export CROSS_COMPILE="${CROSS_COMPILE:-aarch64-linux-gnu-}"
command -v "${CROSS_COMPILE}gcc" > /dev/null
for tool in curl wget make swig python3 sha256sum; do command -v "$tool" > /dev/null; done
python3 -c 'import elftools'
mkdir -p -- "$1"
root=$(realpath "$1")
# The pinned upstream recipes use literal absolute paths without consistently quoting them.
if [[ "$root" =~ [^a-zA-Z0-9_./-] ]]; then
    printf 'Choose a Linux build directory without spaces or shell characters.\n' >&2
    exit 2
fi
project="$root/plastron"
work="$root/build"
commit=b897f7c55ac0aa96601365467e34de3e422122f1
archive="$root/plastron-$commit.tar.gz"
digest=e27117be7a4233921d753575d2b4f29d45f1d3955751d44c1ca97c08436fa776
if [[ ! -f "$archive" ]]; then
    curl -fLsS --retry 1 --connect-timeout 15 --max-time 180 \
        "https://codeload.github.com/ericreinsmidt/plastron/tar.gz/$commit" -o "$archive.download"
    printf '%s  %s\n' "$digest" "$archive.download" | sha256sum --check
    mv -T -- "$archive.download" "$archive"
fi
printf '%s  %s\n' "$digest" "$archive" | sha256sum --check
if [[ ! -d "$project" ]]; then
    mkdir -- "$project"
    tar -xzf "$archive" -C "$project" --strip-components=1
fi

mkdir -p -- "$work"
jobs="${JOBS:-8}"
[[ "$jobs" =~ ^[1-9][0-9]*$ ]]
for script in build-bootloader pack-bootloader; do
    sed -e 's@/src@__PLASTRON_SRC__@g' -e 's@/work@__BOOT_WORK__@g' \
        -e "s@__PLASTRON_SRC__@$project@g" -e "s@__BOOT_WORK__@$work@g" \
        -e "s/\$(nproc)/$jobs/g" "$project/scripts/$script.sh" > "$work/$script.sh"
done
bash "$work/build-bootloader.sh"
config="$work/bootloader/u-boot-v2025.10/.config"
for option in BOOTSTD BOOTMETH_SCRIPT CMD_BOOTI EFI_PARTITION FS_FAT HUSH_PARSER; do
    grep -Fx "CONFIG_$option=y" "$config"
done
bash "$work/pack-bootloader.sh"

prefix="$project/buildroot/board/px2/bootloader/u-boot-px2.bin"
test "$(stat -c %s "$prefix")" -eq 16744448
cp -- "$prefix" "$root/open-boot-prefix.bin"
sha256sum -- "$root/open-boot-prefix.bin"
