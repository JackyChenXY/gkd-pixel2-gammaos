#!/system/bin/sh
set -eu
base=/sys/kernel/tracing
tag=pixel2_gfx_$
instance="$base/instances/$tag"
home=com.android.launcher3
pkg=com.android.settings
focus_is() {
    dumpsys -t 4 window | grep "mCurrentFocus=.* $1/" >/dev/null
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
focus_is "$home"
[ "$(id -u)" = 0 ]
[ -d "$base/instances" ]
mkdir "$instance"
cleanup() {
    echo 0 > "$instance/tracing_on" || true
    echo nop > "$instance/current_tracer" || true
    rmdir "$instance"
}
trap cleanup EXIT
trap 'exit 143' HUP INT TERM
echo 0 > "$instance/tracing_on"
grep -qw function "$instance/available_tracers"
if grep -qw mono "$instance/trace_clock"; then echo mono > "$instance/trace_clock"; fi
echo 512 > "$instance/buffer_size_kb"
: > "$instance/set_ftrace_filter"
for name in drm_mode_atomic_ioctl drm_atomic_helper_commit rockchip_drm_atomic_helper_commit_tail_rpm drm_atomic_helper_wait_for_vblanks drm_atomic_helper_cleanup_planes; do
    if grep -Eq "^$name( |$)" "$base/available_filter_functions"; then
        echo "$name" >> "$instance/set_ftrace_filter"
    else
        echo "UNAVAILABLE $name"
    fi
done
grep -qw drm_atomic_helper_wait_for_vblanks "$instance/set_ftrace_filter"
grep -qw drm_atomic_helper_cleanup_planes "$instance/set_ftrace_filter"
echo function > "$instance/current_tracer"
echo 1 > "$instance/tracing_on"
echo PIXEL2_SETTINGS_BEGIN > "$instance/trace_marker"
am start -W -a android.settings.SETTINGS
focus_is "$pkg"
for key in 20 20 20 20 20 20 19 19 19 19 19 19; do
    input keyevent "$key"
    sleep 0.15
done
focus_is "$pkg" && input keyevent KEYCODE_HOME
sleep 0.5
echo PIXEL2_SETTINGS_END > "$instance/trace_marker"
echo 0 > "$instance/tracing_on"
cat "$instance/trace"
