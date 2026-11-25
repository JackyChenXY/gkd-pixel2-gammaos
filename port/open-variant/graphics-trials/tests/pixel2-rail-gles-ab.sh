#!/system/bin/sh
set -eu
test "$(id -u)" = 0
test "$(getprop ro.pixel2.open_system_probe)" = true
test "$(sha256sum /vendor/lib/dri/libgallium_dri.so | cut -d ' ' -f 1)" = e42b8b3053042fe32aaecf06e90ed55378889e5d06d4dd289063345397f00074
node=/sys/class/devfreq/ff400000.gpu
prop=persist.gpu.minfreq
original=$(getprop "$prop")
[ -z "$original" ]
[ "$(cat "$node/min_freq")" = 200000000 ]
[ "$(cat "$node/max_freq")" = 520000000 ]
[ "$(sha256sum "$1" | cut -d ' ' -f 1)" = 13630c808b6e7d50d7e72672ff14f3188802be5becdef3b4f25f7ee0eb5711aa ]
restore() {
    setprop "$prop" "$original"
    echo 0 > "$node/min_freq"
    [ -z "$(getprop "$prop")" ]
    [ "$(cat "$node/min_freq")" = 200000000 ]
}
trap restore EXIT
trap 'exit 143' HUP INT TERM
chmod 700 "$1"
for phase in A1 B1 B2 A2; do
    [ "$(cat /sys/class/thermal/thermal_zone0/temp)" -lt 55000 ]
    case "$phase" in
        B1|B2) n=400000000; setprop "$prop" "$n"; echo "$n" > "$node/min_freq" ;;
        *) n=200000000; restore ;;
    esac
    sleep 0.55
    [ "$(cat "$node/min_freq")" = "$n" ]
    echo "==== CASE $phase ===="
    printf 'gpu_min='; cat "$node/min_freq"
    printf 'temperature_mC='; cat /sys/class/thermal/thermal_zone0/temp
    cat "$node/trans_stat"
    timeout 20 "$1"
    [ "$(cat "$node/min_freq")" = "$n" ]
    cat "$node/trans_stat"
done
restore
echo '==== RESTORED ===='
