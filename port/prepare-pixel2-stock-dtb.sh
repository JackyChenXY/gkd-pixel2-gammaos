#!/usr/bin/env bash
# Reproduce the display and joypad DTB from a local, unmodified Pixel 2 DTB.
set -euo pipefail

if (( $# != 2 )); then
    printf 'Usage: %s STOCK_DTB OUTPUT_DTB\n' "$0" >&2
    exit 2
fi

stock=$(realpath -e -- "$1")
output=$(realpath -m -- "$2")
test -f "$stock"
test ! -e "$output"
test ! -L "$output"
test "$(fdtget -t s "$stock" / model)" = 'GameKiddy GKD Pixel2'
test "$(fdtget -t s "$stock" /gamekiddy-joypad compatible)" = gamekiddy-joypad
test "$(fdtget -t s "$stock" /aliases mmc0)" = /dwmmc@ff370000

staged=$(mktemp -- "$(dirname -- "$output")/.pixel2-dtb.XXXXXX")
trap 'rm -f -- "$staged"' EXIT
cp -- "$stock" "$staged"
for table in /cpu0-opp-table /px30s-cpu0-opp-table; do
    fdtput -r "$staged" "$table/opp-1512000000"
    fdtget -l "$staged" "$table" | grep -x 'opp-1416000000' > /dev/null
done
fdtput -t s "$staged" /gamekiddy-joypad compatible gpio-keys
fdtput -t s "$staged" /gamekiddy-joypad label gkd_pixel2_joypad
test "$(fdtget -t s "$staged" /gamekiddy-joypad compatible)" = gpio-keys
test "$(fdtget -t s "$staged" /gamekiddy-joypad label)" = gkd_pixel2_joypad
ln -- "$staged" "$output"
sha256sum -- "$output"
