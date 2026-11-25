#!/system/bin/sh
set -eu
[ "$(id -u)" = 0 ]
[ "$(getprop ro.pixel2.open_system_probe)" = true ]
[ "$(sha256sum /vendor/lib/dri/libgallium_dri.so | cut -d ' ' -f 1)" = 366fb3eced6632cfe1fec25e32d1ce63ab2985e09333a7f1d505e6b291a064c8 ]
[ "$(getprop persist.gpu.minfreq)" = 400000000 ]
[ "$(getprop debug.panfrost.native_fence)" != 1 ]
[ "$(getprop vendor.hwc.drm.nonblock_client_present)" != 1 ]
gpu=/sys/class/devfreq/ff400000.gpu
cpu=/sys/devices/system/cpu/cpufreq/policy0
pkg=com.android.settings
home=com.android.launcher3
original=$(cat "$cpu/scaling_governor")
[ "$original" = interactive ]
for candidate in performance schedutil; do grep -qw "$candidate" "$cpu/scaling_available_governors"; done
tunes='above_hispeed_delay boost boostpulse_duration go_hispeed_load hispeed_freq io_is_busy min_sample_time target_loads timer_rate timer_slack'
backup=$(mktemp -d /data/local/tmp/pixel2-cpu-tunables.XXXXXXXX)
for knob in $tunes; do cat "$cpu/interactive/$knob" > "$backup/$knob"; done
verify_interactive() {
    if [ "$(cat "$cpu/scaling_governor")" != "$original" ]; then
        echo "$original" > "$cpu/scaling_governor"
    fi
    for knob in $tunes; do
        expected=$(cat "$backup/$knob")
        node="$cpu/interactive/$knob"
        if [ "$(cat "$node")" != "$expected" ]; then echo "$expected" > "$node"; fi
        [ "$(cat "$node")" = "$expected" ]
    done
}
restore() {
    verify_interactive
    for knob in $tunes; do rm -f "$backup/$knob"; done
    rmdir "$backup"
}
trap restore EXIT
trap 'exit 143' HUP INT TERM
focus_is() { dumpsys -t 4 window | grep "mCurrentFocus=.* $1/" >/dev/null; }
if dumpsys -t 4 power | grep -Eq 'mWakefulness=(Asleep|Dozing)'; then
    input keyevent KEYCODE_WAKEUP
    sleep 0.7
fi
if dumpsys -t 4 window | grep -q 'mCurrentFocus=.*NotificationShade' &&
   dumpsys -t 4 window policy | grep -q 'showing=false'; then
    input keyevent KEYCODE_HOME
    sleep 0.4
fi
focus_is "$home"
echo 'Baseline interactive tunables'
for knob in $tunes; do printf '%s=' "$knob"; cat "$backup/$knob"; done
am start -W -a android.settings.SETTINGS
focus_is "$pkg"
input keyevent KEYCODE_DPAD_DOWN
input keyevent KEYCODE_DPAD_UP
sleep 1.0
observe() {
    printf 'cpu_governor='; cat "$cpu/scaling_governor"
    printf 'cpu_now_khz='; cat "$cpu/scaling_cur_freq"
    printf 'cpu_min_khz='; cat "$cpu/scaling_min_freq"
    printf 'cpu_max_khz='; cat "$cpu/scaling_max_freq"
    printf 'gpu_min_hz='; cat "$gpu/min_freq"
    printf 'gpu_now_hz='; cat "$gpu/cur_freq"
    printf 'temperature_mC='; cat /sys/class/thermal/thermal_zone0/temp
    cat /proc/pressure/cpu
}
for phase in A1 S1 P1 S2 A2; do
    focus_is "$pkg"
    present_temp=$(cat /sys/class/thermal/thermal_zone0/temp)
    if [ "$present_temp" -lt 10000 ] || [ "$present_temp" -ge 55000 ]; then
        echo "Temperature outside test range: $present_temp"
        exit 1
    fi
    case "$phase" in
        A1|A2) verify_interactive; expected=interactive ;;
        S1|S2) expected=schedutil; echo "$expected" > "$cpu/scaling_governor" ;;
        P1) expected=performance; echo "$expected" > "$cpu/scaling_governor" ;;
    esac
    sleep 0.35
    [ "$(cat "$cpu/scaling_governor")" = "$expected" ]
    [ "$(cat "$gpu/min_freq")" = 400000000 ]
    echo "==== CASE $phase START ===="
    observe
    echo "==== CPU_BEFORE $phase ===="
    cat "$cpu/stats/time_in_state"
    echo "==== BEFORE $phase ===="
    dumpsys -t 5 gfxinfo "$pkg" framestats
    for key in 20 20 20 20 20 20 19 19 19 19 19 19; do
        input keyevent "$key"
        sleep 0.16
    done
    sleep 0.45
    focus_is "$pkg"
    [ "$(cat "$cpu/scaling_governor")" = "$expected" ]
    [ "$(cat "$gpu/min_freq")" = 400000000 ]
    echo "==== AFTER $phase ===="
    dumpsys -t 5 gfxinfo "$pkg" framestats
    echo "==== CPU_AFTER $phase ===="
    cat "$cpu/stats/time_in_state"
    echo "==== CASE $phase END ===="
    observe
done
verify_interactive
input keyevent KEYCODE_HOME
echo '==== RESTORED ===='
observe
