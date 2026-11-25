#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-or-later
set -euo pipefail
if [[ $# != 5 || -z $(printenv ANDROID_HOME) ]]; then
    echo "Usage: ANDROID_HOME=/path/to/android-sdk $0 <ppsspp-git> <official-1.20.4.apk> <built-pixel2-android> <built-g31> <output-dir>" >&2
    exit 2
fi
src=$(cd "$(dirname "$0")" && pwd)
upstream=$(realpath "$1")
official=$(realpath "$2")
board=$(realpath "$3")
driver=$(realpath "$4")
mkdir -p "$5"
out=$(realpath "$5")
work=$(mktemp -d "$out/build.XXXXXXXX")
commit=fa50bb1976065c4f8b1b47af227d367fe9771555
git clone -q --no-checkout --local "$upstream" "$work/ppsspp"
git -C "$work/ppsspp" checkout -q --detach "$commit"
python3 "$src/prepare.py" "$work/ppsspp" "$official"
bash "$src/build-presenter.sh" "$board" "$driver" "$work/ppsspp/android/src/main/jniLibs/armeabi-v7a"
(cd "$work/ppsspp" && "${GRADLE_BIN:-./gradlew}" --console=plain --max-workers=4 -Dorg.gradle.jvmargs=-Xmx2g :android:assembleNormalDebug)
apks=("$work"/ppsspp/android/build/outputs/apk/normal/debug/*.apk)
[[ ${#apks[@]} -eq 1 && -f ${apks[0]} ]]
"$ANDROID_HOME/build-tools/36.0.0/apksigner" verify "${apks[0]}"
python3 - "$official" "${apks[0]}" <<'PY'
import sys
from zipfile import ZipFile

with ZipFile(sys.argv[1]) as original, ZipFile(sys.argv[2]) as built:
    files = [p for p in original.namelist() if p.startswith(("assets/", "lib/armeabi-v7a/")) and not p.endswith("/")]
    for name in files:
        if original.read(name) != built.read(name):
            raise SystemExit("Original contents changed: " + name)
    for name in ("libpixel2_ppsspp.so", "libpixel2_g31.so", "libpixel2_g31_android.so"):
        built.getinfo("lib/armeabi-v7a/" + name)
    print("Verified", len(files), "upstream entries and the three presenter libraries.")
PY
cp "${apks[0]}" "$work/ppsspp-pixel2-g31-test.apk"
sha256sum "$work/ppsspp-pixel2-g31-test.apk"
