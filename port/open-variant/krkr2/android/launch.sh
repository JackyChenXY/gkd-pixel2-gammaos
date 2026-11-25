#!/system/bin/sh
# Only ship this wrapper on the matching engineering firmware.
stock() { exec "$@"; }
[ "$(id -u)" = 10117 ] && [ "$#" -ge 10 ] || stock "$@"
[ "$1" = /system/bin/app_process32 ] && [ "$2" = -Xcompiler-option ] &&
    [ "$3" = --generate-mini-debug-info ] && [ "$4" = /system/bin ] &&
    [ "$5" = --application ] && [ "$6" = --nice-name=org.github.krkr2 ] &&
    [ "$7" = com.android.internal.os.WrapperInit ] &&
    [ "${10}" = android.app.ActivityThread ] || stock "$@"
case "$8" in ''|*[!0-9]*) stock "$@";; esac
case "$9" in ''|*[!0-9]*) stock "$@";; esac
[ "$0" = /system/etc/pixel2-krkr/launch.sh ] || stock "$@"
J=/system/etc/pixel2-krkr/official-software-decor.jar
[ -r "$J" ] && [ -r /system/lib/libpixel2_krkr_bootstrap.so ] &&
    [ -r /odm/lib/libpixel2_krkr_v7.so ] || stock "$@"
a=$1; b=$2; c=$3; d=$4; e=$5; f=$6; h=$8; k=$9
shift 10
export CLASSPATH="$J"
exec "$a" "$b" "$c" "$d" "$e" "$f" pixel2.platformtest.EarlyMain "$h" "$k" -cp "$J" pixel2.platformtest.OfficialSoftwareDecor "$@"
