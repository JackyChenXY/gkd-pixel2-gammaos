#!/usr/bin/env bash
# Build the Pixel 2 Settings tile, its service.
set -euo pipefail
if (( $# != 3 )); then echo "Usage: $0 GAMMA_ANDROID_TREE GO_ROOT OUTPUT" >&2; exit 2; fi
here=$(cd "$(dirname "$0")" && pwd)
gamma=$(realpath "$1"); goroot=$(realpath "$2"); out=$(realpath -m "$3")
mkdir -p "$out"; build=$(mktemp -d "$out/tools.XXXXXXXX")
sdk="$gamma/prebuilts/sdk"; host="$sdk/tools/linux/bin"; jar="$sdk/32/public/android.jar"
jdk="$gamma/prebuilts/jdk/jdk11/linux-x86/bin"; key="$gamma/build/make/target/product/security/platform"
export PATH="$jdk:$PATH" LD_LIBRARY_PATH="$sdk/tools/linux/lib64"
mkdir -p "$build/gen" "$build/classes" "$build/dex"
"$host/aapt" package -f -m --min-sdk-version 31 --target-sdk-version 32 -M "$here/app/AndroidManifest.xml" -S "$here/app/res" -I "$jar" -J "$build/gen" -F "$build/base.apk"
find "$build/gen" "$here/app/src" -name '*.java' -print > "$build/sources"
"$jdk/javac" -encoding UTF-8 -source 8 -target 8 -bootclasspath "$jar:$sdk/tools/core-lambda-stubs.jar" -d "$build/classes" @"$build/sources"
"$jdk/jar" cf "$build/classes.jar" -C "$build/classes" .
"$jdk/java" -cp "$gamma/prebuilts/r8/r8.jar" com.android.tools.r8.D8 --min-api 31 --lib "$jar" --output "$build/dex" "$build/classes.jar"
(cd "$build/dex" && "$host/aapt" add "$build/base.apk" classes.dex)
"$host/zipalign" -f 4 "$build/base.apk" "$build/aligned.apk"
env -u LD_LIBRARY_PATH "$jdk/java" -Djava.library.path=/nonexistent -jar "$sdk/tools/linux/lib/apksigner.jar" sign --key "$key.pk8" --cert "$key.x509.pem" --out "$out/Pixel2GpuSelector.apk" "$build/aligned.apk"
env -u LD_LIBRARY_PATH "$jdk/java" -Djava.library.path=/nonexistent -jar "$sdk/tools/linux/lib/apksigner.jar" verify --verbose --print-certs "$out/Pixel2GpuSelector.apk"
export CGO_ENABLED=0 GOTOOLCHAIN=local GOPROXY=off
cd "$here/backend"
GOOS=linux GOARCH=arm64 "$goroot/bin/go" build -buildvcs=false -trimpath -ldflags="-s -w" -o "$out/pixel2-gpu" ./cmd/gpud
