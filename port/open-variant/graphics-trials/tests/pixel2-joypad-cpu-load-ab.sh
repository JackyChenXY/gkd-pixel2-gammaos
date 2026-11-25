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
node="$cpu/interactive/target_loads"
target_before=$(cat "$node")
[ "$target_before" = 90 ]
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
trace=
pressed=0
restore() {
    if [ "$pressed" != 0 ]; then
        sendevent "$input_node" 1 "$pressed" 0 || true
        sendevent "$input_node" 0 0 0 || true
    fi
    echo "$target_before" > "$node"
    [ "$(cat "$node")" = "$target_before" ]
    if [ -n "$trace" ] && [ -d "$trace" ]; then
        echo 0 > "$trace/tracing_on" || true
        rmdir "$trace"
    fi
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
if [ -r /sys/kernel/debug/clk/clk_summary ]; then
    echo 'DDR clock summary (read-only)'
    grep -E 'dpll(_ddr)?|gpll_ddr|sclk_ddrc|clk_ddrphy[14]x' /sys/kernel/debug/clk/clk_summary || true
fi
am start -W -a android.settings.SETTINGS
focus_is com.android.settings
sleep 1
if [ -d /sys/kernel/tracing/instances ]; then
    base="/sys/kernel/tracing/instances/pixel2_joypad_boost_$$"
    mkdir "$base"
    trace="$base"
    echo 0 > "$trace/tracing_on"
    echo 128 > "$trace/buffer_size_kb"
    if [ -f "$trace/events/cpufreq_interactive/cpufreq_interactive_boost/enable" ]; then
        echo 1 > "$trace/events/cpufreq_interactive/cpufreq_interactive_boost/enable"
        echo 1 > "$trace/tracing_on"
    else
        echo 'cpufreq boost trace event unavailable'
    fi
fi
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
    printf 'target_loads='; cat "$node"
    printf 'cpu_now_khz='; cat "$cpu/scaling_cur_freq"
    printf 'gpu_min_hz='; cat "$gpu/min_freq"
    printf 'temperature_mC='; cat /sys/class/thermal/thermal_zone0/temp
}
for phase in A1 B1 B2 A2; do
    focus_is com.android.settings
    [ "$(cat /sys/class/thermal/thermal_zone0/temp)" -lt 55000 ]
    [ "$(cat "$gpu/min_freq")" = 400000000 ]
    [ "$(cat "$cpu/scaling_governor")" = interactive ]
    case "$phase" in A1|A2) load=90 ;; *) load=65 ;; esac
    echo "$load" > "$node"
    sleep 0.55
    [ "$(cat "$node")" = "$load" ]
    echo "==== CASE $phase START ===="
    observe
    echo "==== CPU_BEFORE $phase ===="
    cat "$cpu/stats/time_in_state"
    echo "==== BEFORE $phase ===="
    dumpsys -t 5 gfxinfo com.android.settings framestats
    if [ -n "$trace" ]; then echo "PIXEL2_PAD_$phase" > "$trace/trace_marker"; fi
    for key in 545 545 545 545 545 545 544 544 544 544 544 544; do
        raw_key "$key"
        sleep 0.23
    done
    sleep 0.5
    focus_is com.android.settings
    [ "$(cat "$node")" = "$load" ]
    echo "==== AFTER $phase ===="
    dumpsys -t 5 gfxinfo com.android.settings framestats
    echo "==== CPU_AFTER $phase ===="
    cat "$cpu/stats/time_in_state"
    echo "==== CASE $phase END ===="
    observe
done
if [ -n "$trace" ]; then
    echo 0 > "$trace/tracing_on"
    echo 'Verified joypad boost trace'
    grep -E 'PIXEL2_PAD_|cpufreq_interactive_boost:.*touch' "$trace/trace" || true
fi
echo "$target_before" > "$node"
input keyevent KEYCODE_HOME
echo '==== RESTORED ===='
observe
