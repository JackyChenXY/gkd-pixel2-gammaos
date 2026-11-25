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
original_size=$(wm size)
original_density=$(wm density)
[ "$original_size" = 'Physical size: 640x480' ]
[ "$original_density" = 'Physical density: 160' ]
[ "$(cat "$cpu/interactive/target_loads")" = 90 ]
check_mode() {
    size=$(wm size)
    density=$(wm density)
    if [ "$1" = 0 ]; then
        [ "$size" = "$original_size" ] && [ "$density" = "$original_density" ]
    else
        echo "$size" | grep -Fxq 'Override size: 480x360' &&
        echo "$density" | grep -Fxq 'Override density: 120'
    fi
}
set_mode() {
    if check_mode "$1"; then return; fi
    if [ "$1" = 0 ]; then
        wm size reset
        wm density reset
    else
        wm size 480x360
        wm density 120
    fi
    check_mode "$1"
}
[ "$(cat "$cpu/scaling_governor")" = interactive ]
input_node=
for item in /sys/class/input/event*; do
    if [ "$(cat "$item/device/name" 2>/dev/null)" = gkd_pixel2_joypad ] &&
       [ "$(cat "$item/device/id/bustype" 2>/dev/null)" = 0006 ] &&
       [ "$(cat "$item/device/id/product" 2>/dev/null)" = 2102 ]; then
        [ -z "$input_node" ]
        input_node="/dev/input/$(basename "$item")"
    fi
done
[ -n "$input_node" ]
keys=$(getevent -lp "$input_node")
echo "$keys" | grep -qw BTN_DPAD_UP
echo "$keys" | grep -qw BTN_DPAD_DOWN
[ -c "$input_node" ]
echo "Verified virtual joypad: $input_node"
pressed=0
restore() {
    if [ "$pressed" != 0 ]; then
        sendevent "$input_node" 1 "$pressed" 0 || true
        sendevent "$input_node" 0 0 0 || true
    fi
    set_mode 0
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
focus_is com.android.launcher3
raw_key() {
    pressed=$1
    sendevent "$input_node" 1 "$pressed" 1
    sendevent "$input_node" 0 0 0
    sleep 0.02
    sendevent "$input_node" 1 "$pressed" 0
    sendevent "$input_node" 0 0 0
    pressed=0
}
observe() {
    wm size
    wm density
    printf 'cpu_now_khz='; cat "$cpu/scaling_cur_freq"
    printf 'gpu_min_hz='; cat "$gpu/min_freq"
    printf 'temperature_mC='; cat /sys/class/thermal/thermal_zone0/temp
}
for phase in A1 B1 B2 A2; do
    if focus_is com.android.settings; then input keyevent KEYCODE_HOME; fi
    sleep 0.6
    focus_is com.android.launcher3
    [ "$(cat /sys/class/thermal/thermal_zone0/temp)" -lt 55000 ]
    [ "$(cat "$gpu/min_freq")" = 400000000 ]
    [ "$(cat "$cpu/scaling_governor")" = interactive ]
    case "$phase" in A1|A2) mode=0 ;; *) mode=1 ;; esac
    set_mode "$mode"
    sleep 1.1
    am force-stop com.android.settings
    am start -W -a android.settings.SETTINGS
    ready=false
    for poll in 1 2 3 4 5 6 7 8; do
        if focus_is com.android.settings; then ready=true; break; fi
        sleep 0.5
    done
    if [ "$ready" != true ]; then
        echo "Settings not focused after screen reconfiguration"
        dumpsys -t 4 window | grep -E 'mCurrentFocus=|mFocusedApp=' || true
        wm size
        wm density
        exit 1
    fi
    raw_key 545
    raw_key 544
    sleep 0.85
    check_mode "$mode" || { echo "Display override changed before $phase"; wm size; wm density; exit 1; }
    echo "==== CASE $phase START ===="
    observe
    echo "==== CPU_BEFORE $phase ===="
    cat "$cpu/stats/time_in_state"
    echo "==== BEFORE $phase ===="
    dumpsys -t 5 gfxinfo com.android.settings framestats
    for key in 545 545 545 545 545 545 544 544 544 544 544 544; do
        raw_key "$key"
        sleep 0.23
    done
    sleep 0.5
    focus_is com.android.settings
    check_mode "$mode"
    echo "==== AFTER $phase ===="
    dumpsys -t 5 gfxinfo com.android.settings framestats
    echo "==== CPU_AFTER $phase ===="
    cat "$cpu/stats/time_in_state"
    echo "==== CASE $phase END ===="
    observe
done
input keyevent KEYCODE_HOME
set_mode 0
echo '==== RESTORED ===='
observe
