[CmdletBinding()]
param(
    [ValidateSet('Status', 'Enable', 'Disable')]
    [string]$Mode = 'Status',
    [string]$AdbPath = 'adb'
)

$ErrorActionPreference = 'Stop'
$adb = (Get-Command $AdbPath -CommandType Application -ErrorAction Stop).Source

function Read-Pixel2([string[]]$Command) {
    $lines = & $adb -d shell @Command
    if ($LASTEXITCODE -ne 0) { throw 'The USB command did not complete.' }
    return ($lines -join [Environment]::NewLine).Trim()
}

if ((& $adb -d get-state) -ne 'device' -or
    (Read-Pixel2 @('getprop', 'sys.boot_completed')) -ne '1' -or
    (Read-Pixel2 @('getprop', 'ro.pixel2.open_system_probe')) -ne 'true' -or
    (Read-Pixel2 @('uname', '-r')) -ne '5.10.226-pixel2-panfrost') {
    throw 'Connect the booted Pixel 2 Panfrost test system by USB.'
}

$report = @'
node=/sys/class/devfreq/ff400000.gpu
value=$(getprop persist.gpu.minfreq)
case "$value" in
    "") echo "Performance preference: off" ;;
    400000000) echo "Performance preference: 400 MHz" ;;
    *) echo "Performance preference: custom" ;;
esac
echo "GPU limits in Hz:"
cat "$node/min_freq" "$node/max_freq"
'@
if ($Mode -eq 'Status') {
    Read-Pixel2 @($report)
    return
}

$boot = Read-Pixel2 @('cat', '/proc/sys/kernel/random/boot_id')
$initialUid = Read-Pixel2 @('id', '-u')
if ($initialUid -notin @('0','2000')) { throw 'Unexpected Android USB user.' }
$restoreUsb = $initialUid -ne '0'
$mutex = [Threading.Mutex]::new($false, 'Local\GkdPixel2PanfrostPerformance')
$locked = $false
try {
    try {
        $locked = $mutex.WaitOne(0)
    } catch [Threading.AbandonedMutexException] {
        $locked = $true
    }
    if (-not $locked) { throw 'Another performance mode change is running.' }

    if ($restoreUsb) {
        & $adb -d root | Out-Host
        $ready = $false
        for ($attempt=0; $attempt -lt 16; $attempt++) {
            Start-Sleep -Milliseconds 500
            if (((& $adb -d shell id -u 2>$null) -join '').Trim() -eq '0') { $ready = $true; break }
        }
        if (-not $ready) { throw 'Rooted debugging is required for changing the mode.' }
    }
    if ((Read-Pixel2 @('cat', '/proc/sys/kernel/random/boot_id')) -ne $boot -or
        (Read-Pixel2 @('getprop', 'ro.pixel2.open_system_probe')) -ne 'true') {
        throw 'The Pixel 2 changed while USB debugging restarted.'
    }

    $choice = if ($Mode -eq 'Enable') { '400000000' } else { '' }
    $transaction = @'
set -eu
node=/sys/class/devfreq/ff400000.gpu
prop=persist.gpu.minfreq
value="__MODE_VALUE__"
old=$(getprop "$prop")
case "$old" in ""|400000000) ;; *) echo "Custom preference detected" >&2; exit 3 ;; esac
grep -qw 400000000 "$node/available_frequencies"
cap=$(cat "$node/max_freq")
if [ -n "$value" ] && [ "$cap" -lt 400000000 ]; then
    echo "The active GPU cap is below 400 MHz" >&2
    exit 4
fi
rollback() {
    setprop "$prop" "$old"
    if [ -n "$old" ]; then echo "$old" > "$node/min_freq"; else echo 0 > "$node/min_freq"; fi
}
trap rollback EXIT
trap 'exit 143' HUP INT TERM
setprop "$prop" "$value"
if [ -n "$value" ]; then
    echo "$value" > "$node/min_freq"
    goal=$value
else
    echo 0 > "$node/min_freq"
    goal=200000000
fi
for attempt in 1 2 3 4 5; do
    if [ "$(getprop "$prop")" = "$value" ] && [ "$(cat "$node/min_freq")" = "$goal" ]; then
        trap - EXIT HUP INT TERM
        exit 0
    fi
    sleep 0.25
done
echo "The selected GPU setting did not take effect" >&2
exit 5
'@
    $transaction = $transaction.Replace('__MODE_VALUE__', $choice)
    $null = Read-Pixel2 @($transaction)
    Read-Pixel2 @($report)
} finally {
    if ($locked -and $restoreUsb) {
        & $adb -d unroot | Out-Host
        $normal = $false
        for ($attempt=0; $attempt -lt 16; $attempt++) {
            Start-Sleep -Milliseconds 500
            if (((& $adb -d shell id -u 2>$null) -join '').Trim() -eq '2000') { $normal = $true; break }
        }
        if (-not $normal) { Write-Warning 'Normal USB debugging was not yet verified.' }
    }
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
