#!/system/bin/sh
set -eu
node=/sys/class/devfreq/ff400000.gpu
pkg=com.android.settings
home=com.android.launcher3
original_governor=$(cat "$node/governor")
original_polling=$(cat "$node/polling_interval")
[ "$(id -u)" = 0 ]
[ "$original_governor" = simple_ondemand ]
[ "$original_polling" -ge 30 ]
[ "$(cat "$node/max_freq")" = 520000000 ]
grep -qw performance "$node/available_governors"
[ "$(getprop ro.pixel2.open_system_probe)" = true ]

restore() {
    if [ "$(cat "$node/governor")" != "$original_governor" ]; then
        echo "$original_governor" > "$node/governor"
    fi
    if [ "$(cat "$node/polling_interval")" != "$original_polling" ]; then
        echo "$original_polling" > "$node/polling_interval"
    fi
}
trap restore EXIT
trap 'exit 143' HUP INT TERM
observe() {
    printf 'policy='; cat "$node/governor"
    printf 'polling_ms='; cat "$node/polling_interval"
    printf 'temperature_mC='; cat /sys/class/thermal/thermal_zone0/temp
    cat "$node/trans_stat"
    cat /proc/pressure/cpu
    cat /proc/pressure/memory
    cat /proc/pressure/io
    dmesg | grep -E 'bus-apll: failed to set voltage|vdd_logic: Restricting voltage|Failed to change cpu frequency: -16|_set_opp_voltage: failed' | tail -3 || true
}
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

for phase in A1 B1 Peak B2 A2; do
    focus_is "$home"
    present_temp=$(cat /sys/class/thermal/thermal_zone0/temp)
    if [ "$present_temp" -lt 10000 ] || [ "$present_temp" -ge 55000 ]; then
        echo "Temperature out of test range: $present_temp"
        exit 1
    fi
    case "$phase" in
        B1|B2)
            restore
            echo 16 > "$node/polling_interval"
            [ "$(cat "$node/polling_interval")" = 16 ]
            ;;
        Peak)
            restore
            echo performance > "$node/governor"
            [ "$(cat "$node/governor")" = performance ]
            ;;
        *)
            restore
            ;;
    esac
    echo "==== CASE $phase START ===="
    observe
    echo "==== BEFORE $phase ===="
    dumpsys -t 5 gfxinfo "$pkg" framestats
    echo "==== DRIVE $phase ===="
    am start -W -a android.settings.SETTINGS
    focus_is "$pkg"
    printf 'active_policy='; cat "$node/governor" "$node/polling_interval" "$node/cur_freq" | tr "\n" " "; echo
    for key in 20 20 20 20 20 20 19 19 19 19 19 19; do
        input keyevent "$key"
        sleep 0.15
    done
    sleep 0.4
    focus_is "$pkg"
    echo "==== AFTER $phase ===="
    dumpsys -t 5 gfxinfo "$pkg" framestats
    if focus_is "$pkg"; then input keyevent KEYCODE_HOME; fi
    sleep 0.5
    echo "==== CASE $phase END ===="
    observe
done
restore
echo '==== RESTORED ===='
cat "$node/governor" "$node/polling_interval" "$node/min_freq" "$node/max_freq"
