# SPDX-License-Identifier: Apache-2.0
"""Sample actual presentation times for this test application's SurfaceView."""
import argparse
import json
import math
import shlex
import statistics
import subprocess
import time
from pathlib import Path

PACKAGE = "org.ppsspp.ppsspp.pixel2test"
PENDING = 2**63 - 1


def shell(adb, *args):
    return subprocess.check_output([adb, "-d", "shell", shlex.join(args)], timeout=15).decode().splitlines()


def active_layer(adb):
    layers = [name for name in shell(adb, "dumpsys", "SurfaceFlinger", "--list")
              if PACKAGE in name and "SurfaceView" in name]
    for name in sorted(layers, key=lambda n: "BLAST" not in n):
        _, times = timings(adb, name)
        if times:
            return name
    raise RuntimeError("No presenting SurfaceView for the test application: " + repr(layers))


def timings(adb, layer):
    lines = shell(adb, "dumpsys", "SurfaceFlinger", "--latency", layer)
    if not lines or not lines[0].strip().isdigit():
        return 0, []
    actual = []
    for line in lines[1:]:
        fields = line.split()
        if len(fields) == 3 and fields[1].isdigit():
            stamp = int(fields[1])
            if 0 < stamp < PENDING:
                actual.append(stamp)
    return int(lines[0]), actual


def measure(adb, seconds):
    layer = active_layer(adb)
    period, initial = timings(adb, layer)
    anchor = max(initial)
    previous = anchor
    observed = {anchor}
    started = time.monotonic()
    until = started + seconds
    while time.monotonic() < until:
        time.sleep(min(0.7, max(0, until - time.monotonic())))
        current_period, ring = timings(adb, layer)
        if current_period != period or (ring and min(ring) > previous):
            raise RuntimeError("Layer or refresh changed, or frames were lost between polls")
        observed.update(t for t in ring if t > anchor)
        if ring:
            previous = max(ring)
    elapsed = time.monotonic() - started
    samples = sorted(observed)
    if len(samples) < 3 or (samples[-1] - anchor) / 1e9 < 0.88 * elapsed:
        raise RuntimeError("Too few actual presents or the surface stopped during the sample")
    intervals = [(b - a) / 1e6 for a, b in zip(samples, samples[1:])]
    ordered = sorted(intervals)
    return dict(layer=layer, refresh_ns=period, frames=len(intervals), seconds=(samples[-1]-anchor)/1e9,
                fps=1e3/statistics.mean(intervals), p50_ms=statistics.median(intervals),
                p95_ms=ordered[math.ceil(len(ordered)*0.95)-1],
                over_2_5_refresh=sum(t*1e6 > 2.5*period for t in intervals),
                actual_present_ns=samples)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("adb")
    parser.add_argument("output", type=Path)
    parser.add_argument("--seconds", type=float, default=25)
    args = parser.parse_args()
    result = measure(args.adb, args.seconds)
    args.output.write_text(json.dumps(result, indent=2))
    print(json.dumps({k:v for k,v in result.items() if k != "actual_present_ns"}))
