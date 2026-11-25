#!/system/bin/sh
set -eu
set -o pipefail
[ "$(id -u)" = 0 ]
[ "$(getprop ro.pixel2.open_system_probe)" = true ]
[ "$(sha256sum /vendor/lib/dri/libgallium_dri.so | cut -d ' ' -f 1)" = e42b8b3053042fe32aaecf06e90ed55378889e5d06d4dd289063345397f00074 ]
node=/sys/class/devfreq/ff400000.gpu
freq=/sys/devices/system/cpu/cpufreq/policy0
prop=persist.gpu.minfreq
old_prop=$(getprop "$prop")
[ -z "$old_prop" ]
[ "$(cat "$node/min_freq")" = 200000000 ]
[ "$(cat "$node/max_freq")" = 520000000 ]
[ "$(cat "$node/governor")" = simple_ondemand ]
grep -qw 400000000 "$node/available_frequencies"
restore() {
    if [ "$(cat "$node/governor")" != simple_ondemand ]; then
        echo simple_ondemand > "$node/governor"
    fi
    setprop "$prop" "$old_prop"
    echo 0 > "$node/min_freq"
    [ "$(getprop "$prop")" = "$old_prop" ]
    [ "$(cat "$node/min_freq")" = 200000000 ]
}
trap restore EXIT
trap 'exit 143' HUP INT TERM
focus_is() { dumpsys -t 4 window | grep "mCurrentFocus=.* $1/" >/dev/null; }
timed_log() {
    dmesg | awk 'match($0,/^\[[[:space:]]*[0-9]+\.[0-9]+\]/) { last=substr($0,2,RLENGTH-2)+0 } END { printf "%.6f\n",last }'
}
new_errors() {
    dmesg | awk -v cutoff="$1" '
      match($0,/^\[[[:space:]]*[0-9]+\.[0-9]+\]/) {
        stamp=substr($0,2,RLENGTH-2)+0
        if (!seen++) first=stamp
        if (stamp<=cutoff) next
        if ($0 ~ /bus-apll.*failed to set voltage/) bus++
        if ($0 ~ /vdd_logic.*Restricting voltage/) rail++
        if ($0 ~ /Failed to change cpu frequency:[[:space:]]*-16/) cpu++
        if ($0 ~ /panfrost.*_set_opp_voltage: failed/) opp++
      }
      END { printf "new_bus_apll=%d new_vdd_logic=%d new_cpu_e_16=%d new_gpu_opp=%d ring_gap=%d\n",bus,rail,cpu,opp,(first>cutoff) }'
}
observe() {
    printf 'gpu_min='; cat "$node/min_freq"
    printf 'gpu_now='; cat "$node/cur_freq"
    printf 'thermal_mC='; cat /sys/class/thermal/thermal_zone0/temp
    printf 'cpu_now='; cat "$freq/cpuinfo_cur_freq" 2>/dev/null || true
    printf 'gpu_runtime='; cat /sys/devices/platform/ff400000.gpu/power/runtime_status
}
if dumpsys -t 4 power | grep -Eq 'mWakefulness=(Asleep|Dozing)'; then
    input keyevent KEYCODE_WAKEUP
    sleep 0.7
fi
if dumpsys -t 4 window | grep -q 'mCurrentFocus=.*NotificationShade' &&
   dumpsys -t 4 window policy | grep -q 'showing=false'; then
    input keyevent KEYCODE_HOME
    sleep 0.4
fi
focus_is com.android.launcher3
am start -W -a android.settings.SETTINGS >/dev/null
if focus_is com.android.settings; then input keyevent KEYCODE_HOME; fi
sleep 0.75
for phase in A1 B1 B2 A2; do
    focus_is com.android.launcher3
    [ "$(cat /sys/class/thermal/thermal_zone0/temp)" -lt 55000 ]
    desired=200000000
    case "$phase" in
        B1|B2)
            desired=400000000
            setprop "$prop" "$desired"
            [ "$(getprop "$prop")" = "$desired" ]
            echo "$desired" > "$node/min_freq"
            ;;
        *) restore ;;
    esac
    sleep 0.25
    echo "==== CASE $phase START ===="
    [ "$(cat "$node/min_freq")" = "$desired" ]
    observe
    echo userspace > "$node/governor"
    if echo "$desired" > "$node/userspace/set_freq"; then
        printf 'cpu_test_gpu_target='; cat "$node/cur_freq"
    else
        echo 'cpu_test_gpu_target=rejected'
    fi
    start_log=$(timed_log)
    echo "==== CPU_FREQ_BEFORE $phase ===="
    cat "$freq/stats/time_in_state"
    start=$(cut -d ' ' -f 1 /proc/uptime)
    checksum=$(dd if=/dev/zero bs=65536 count=4096 2>/dev/null | taskset 1 sha256sum)
    finish=$(cut -d ' ' -f 1 /proc/uptime)
    printf 'cpu_hash=%s\n' "$checksum"
    awk -v a="$start" -v b="$finish" 'BEGIN {printf "cpu256m_s=%.2f\n",b-a}'
    echo "==== CPU_FREQ_AFTER $phase ===="
    cat "$freq/stats/time_in_state"
    new_errors "$start_log"
    observe
    echo simple_ondemand > "$node/governor"
    echo "==== BEFORE $phase ===="
    dumpsys -t 5 gfxinfo com.android.settings framestats
    echo "==== DRIVE $phase ===="
    start_log=$(timed_log)
    am start -W -a android.settings.SETTINGS
    focus_is com.android.settings
    # Android's launch boost can temporarily vote higher. The restored minimum
    # after the boost and before the key burst is the effective comparison.
    sleep 0.35
    observe
    for key in 20 20 20 20 20 20 19 19 19 19 19 19; do
        input keyevent "$key"
        sleep 0.15
    done
    sleep 0.4
    focus_is com.android.settings
    echo "==== AFTER $phase ===="
    dumpsys -t 5 gfxinfo com.android.settings framestats
    new_errors "$start_log"
    observe
    if focus_is com.android.settings; then input keyevent KEYCODE_HOME; fi
    sleep 0.6
    echo "==== CASE $phase END ===="
    observe
done
restore
echo '==== RESTORED ===='
getprop "$prop"
cat "$node/min_freq"
