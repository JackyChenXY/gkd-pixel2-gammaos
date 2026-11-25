#!/system/bin/sh
set -eu
[ "$(id -u)" = 0 ]
[ "$(getprop ro.pixel2.open_system_probe)" = true ]
[ "$(sha256sum /vendor/lib/hw/hwcomposer.drm_minigbm.so | cut -d ' ' -f 1)" = a52165cb7faf95efd82d8ac1e88d1dc97c0d2ffe8fcdf599dccbd4a1fe9e0a94 ]
prop=vendor.hwc.drm.nonblock_client_present
original=$(getprop "$prop")
case "$original" in ""|0) ;; *) exit 1 ;; esac
restore() { setprop "$prop" "$original"; }
trap restore EXIT
trap 'exit 143' HUP INT TERM
config=$1
out=$2
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
for stage in A1 B1 A2; do
    focus_is com.android.launcher3
    temp=$(cat /sys/class/thermal/thermal_zone0/temp)
    [ "$temp" -lt 55000 ]
    case "$stage" in B1) mode=1 ;; *) mode=0 ;; esac
    setprop "$prop" "$mode"
    [ "$(getprop "$prop")" = "$mode" ]
    echo "CASE $stage mode=$mode temp=$temp"
    dumpsys -t 7 SurfaceFlinger | grep -E 'nonblocking_frames|Failed to commit' || true
    file="$out-$stage.perfetto-trace"
    perfetto --txt -c "$config" -o "$file" &
    pid=$!
    sleep 0.65
    am start -W -a android.settings.SETTINGS >/dev/null
    focus_is com.android.settings
    for key in 20 20 20 20 20 20 19 19 19 19 19 19; do
        input keyevent "$key"
        sleep 0.15
    done
    focus_is com.android.settings && input keyevent KEYCODE_HOME
    wait "$pid"
    stat -c %s "$file"
    dumpsys -t 7 SurfaceFlinger | grep -E 'nonblocking_frames|Failed to commit' || true
done
restore
echo TEST_DONE
