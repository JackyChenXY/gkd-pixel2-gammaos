#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

if (( $# != 2 )); then
    echo "Usage: $0 /path/to/mesa-22.3.7.tar.xz /path/to/work-directory" >&2
    exit 2
fi
port=$(cd "$(dirname "$0")" && pwd)
archive=$(realpath "$1")
expected=894ce2f4a1c2e76177cdd2284620192d0da3066b243eec2fbb1d7cf37f13042c
printf '%s  %s\n' "$expected" "$archive" | sha256sum --check --status
mkdir -p "$2"
scratch=$(mktemp -d "$(realpath "$2")/g31-compiler.XXXXXXXX")
tar -xf "$archive" -C "$scratch"
source_dir="$scratch/mesa-22.3.7"
pan="$source_dir/src/panfrost"
cp "$port/compile_shader.c" "$pan/pixel2_compile_shader.c"
cp "$port/shader_abi.h" "$pan/shader_abi.h"
cat "$port/compiler-target.meson" >>"$pan/meson.build"
meson setup "$scratch/build" "$source_dir" --wrap-mode=nodownload -Dbuildtype=release \
    -Dgallium-drivers=panfrost -Dvulkan-drivers= -Dplatforms= -Degl=disabled -Dglx=disabled \
    -Dgbm=disabled -Dgles1=disabled -Dgles2=disabled -Dllvm=disabled -Dvalgrind=disabled -Dgallium-xa=disabled
ninja -C "$scratch/build" -j "${JOBS:-4}" src/panfrost/pixel2-shader-compiler
"$scratch/build/src/panfrost/pixel2-shader-compiler" >"$scratch/g31_program.h"
cmp "$port/g31_program.h" "$scratch/g31_program.h"
echo "Verified shader header: $scratch/g31_program.h"
