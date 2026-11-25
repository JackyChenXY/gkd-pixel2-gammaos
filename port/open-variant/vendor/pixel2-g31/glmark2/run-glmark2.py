# SPDX-License-Identifier: Apache-2.0
"""Run one on-screen glmark2 pass and keep its scores and device conditions."""
import argparse
import json
import math
import re
import shlex
import subprocess
import time
from pathlib import Path


def run(adb, *args):
    return subprocess.check_output([adb, "-d", *args], timeout=45).decode("utf-8", "replace").strip()


def shell(adb, *args):
    return run(adb, "shell", shlex.join(args))


def conditions(adb):
    return run(adb, "shell", """getprop ro.product.model
getprop ro.build.version.release
getprop ro.product.cpu.abilist
wm size
dumpsys battery | grep -e 'USB powered:' -e 'level:' -e 'temperature:'
for d in /sys/class/devfreq/*gpu*; do
  for f in governor min_freq max_freq cur_freq; do printf '%s=' "$f"; cat "$d/$f"; done
done
for d in /sys/class/thermal/thermal_zone*; do printf '%s=' "$(cat "$d/type")"; cat "$d/temp"; done""")


class ScreenTimes:
    """Track the active benchmark SurfaceView and deduplicate its rolling frame history."""
    def __init__(self, adb, package):
        self.adb, self.package = adb, package
        self.layer = None
        self.period = 0
        self.frames = set()
        self.previous = 0
        self.gaps = 0

    def poll(self):
        if not self.layer:
            names = shell(self.adb, "dumpsys", "SurfaceFlinger", "--list").splitlines()
            self.layer = next((n for n in names if self.package in n and "SurfaceView[" in n and "(BLAST)" in n), None)
        if not self.layer:
            return
        lines = shell(self.adb, "dumpsys", "SurfaceFlinger", "--latency", self.layer).splitlines()
        if not lines or not lines[0].strip().isdigit():
            return
        period = int(lines[0])
        if self.period and period != self.period:
            raise RuntimeError("Display refresh rate changed during benchmark")
        self.period = period
        ring = []
        for line in lines[1:]:
            fields = line.split()
            if len(fields) == 3 and fields[1].isdigit() and 0 < int(fields[1]) < 2**63-1:
                ring.append(int(fields[1]))
        if ring:
            if self.previous and min(ring) > self.previous:
                self.gaps += 1
            self.frames.update(ring)
            self.previous = max(ring)

    def result(self):
        times = sorted(self.frames)
        # Exclude the first and last second, including startup/exit transitions.
        if not times or self.gaps:
            raise RuntimeError(f"Invalid screen timing history ({len(times)} samples, {self.gaps} gaps)")
        kept = [t for t in times if times[0]+10**9 <= t <= times[-1]-10**9]
        if len(kept) < 3:
            raise RuntimeError("Too few steady-state presentation timestamps")
        intervals = sorted(b-a for a,b in zip(kept, kept[1:]))
        elapsed = (kept[-1] - kept[0]) / 1e9
        return {"layer":self.layer,"refresh_ns":self.period,"seconds":elapsed,"intervals":len(intervals),
                "fps":len(intervals)/elapsed,"p95_ms":intervals[math.ceil(0.95*len(intervals))-1]/1e6,
                "actual_present_ns":kept}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("adb")
    parser.add_argument("directory", type=Path)
    parser.add_argument("--activity", default="org.linaro.glmark2/org.linaro.glmark2.Glmark2Activity")
    profiles = parser.add_mutually_exclusive_group()
    profiles.add_argument("--options")
    profiles.add_argument("--quick", action="store_true")
    parser.add_argument("--expected", type=int)
    parser.add_argument("--expect-g31", action="store_true")
    parser.add_argument("--screen-times", action="store_true")
    parser.add_argument("--timeout", type=int, default=650)
    args = parser.parse_args()
    if args.quick:
        args.options = Path(__file__).with_name("quick.args").read_text().strip()
    if args.expected is None:
        args.expected = 5 if args.quick else 33
    out = args.directory
    out.mkdir(parents=True, exist_ok=False)
    adb = args.adb
    (out/"conditions-before.txt").write_text(conditions(adb))
    start = ["am", "start", "-W", "-a", "android.intent.action.MAIN", "-n", args.activity]
    if args.options is not None:
        start.extend(["--es", "args", args.options])
    if args.expect_g31:
        start.extend(["--ez", "pixel2G31", "true"])
    screen = ScreenTimes(adb, args.activity.split("/")[0]) if args.screen_times else None
    log_path = out/"android.log"
    with log_path.open("wb") as stream:
        monitor = subprocess.Popen([adb,"-d","logcat","-v","threadtime","-T","1","-s",
                                    "glmark2:V","GLMark2:V","Pixel2G31:I","AndroidRuntime:E"],
                                   stdout=stream, stderr=subprocess.STDOUT)
        try:
            result = shell(adb, *start)
            (out/"launch.txt").write_text(result)
            if "Status: ok" not in result:
                raise RuntimeError(result)
            # logcat -T 1 may contain an old line before the intended process.
            package = args.activity.split("/")[0]
            pid = ""
            for _ in range(15):
                for process in (package + ":glmark2", package):
                    p = subprocess.run([adb,"-d","shell","pidof",process], capture_output=True)
                    if p.stdout.strip():
                        pid = p.stdout.decode().split()[0]
                        break
                if pid:
                    break
                time.sleep(0.3)
            if not pid:
                raise RuntimeError("Cannot identify benchmark process")
            started = time.monotonic()
            next_liveness = started + 20
            score_re = re.compile(r"glmark2(?:-es2)?(?:[-\w ]*?)\s+Score\s*:\s*(\d+)", re.I)
            while True:
                lines = [line for line in log_path.read_text(errors="replace").splitlines()
                         if len(line.split()) >= 6 and line.split()[2] == pid]
                selected = "\n".join(lines)
                score = score_re.search(selected)
                if score:
                    break
                if time.monotonic() - started >= args.timeout:
                    raise RuntimeError("Timed out before a score; see " + str(log_path))
                if time.monotonic() > next_liveness:
                    next_liveness = time.monotonic() + 12
                    alive = subprocess.run([adb,"-d","shell","pidof",package+":glmark2"],capture_output=True)
                    if alive.returncode != 0 and not subprocess.run(
                            [adb,"-d","shell","pidof",package],capture_output=True).stdout.strip():
                        raise RuntimeError("Benchmark exited before a score; see " + str(log_path))
                if screen:
                    screen.poll()
                time.sleep(0.65 if screen else 3)
        finally:
            monitor.terminate()
            try:
                monitor.wait(timeout=4)
            except subprocess.TimeoutExpired:
                monitor.kill()
                monitor.wait()
    # Android's logger may divide a scene name and its resulting FPS across messages.
    only_log = []
    for line in lines:
        m = re.search(r"\b[VDIWEF]\s+glmark2\s*:\s?(.*)$",line,re.I)
        if m:
            only_log.append(m.group(1))
    bench = "\n".join(only_log)
    (out/"glmark2.log").write_text(bench + "\n")
    pattern = r"\[([a-zA-Z0-9_-]+)\]\s*([^\n]*?)\s*(?:\n\s*)?FPS:\s*([\d.]+)\s+FrameTime:\s*([\d.]+)\s*ms"
    scenes = [{"scene":m[1], "options":m[2].strip().strip(":").strip(),
               "fps":float(m[3]), "frame_ms":float(m[4])}
              for m in re.finditer(pattern, bench)]
    if len(scenes) != args.expected:
        raise RuntimeError(f"Score {score[1]} seen, parsed {len(scenes)} of {args.expected} cases; inspect {out/'glmark2.log'}")
    if args.expect_g31 and ("errors=0" not in selected or "Using original EGL window" in selected
                            or "Using Android presentation" in selected or "Game frame could not be presented" in selected):
        raise RuntimeError("G31 delivery was not verified")
    if args.activity.startswith("org.linaro.glmark2.pixel2compare/"):
        if "Active render surface 640x480" not in selected or "r=8 g=8 b=8 a=8" not in selected:
            raise RuntimeError("The expected resolution or RGBA format was not confirmed")
        if not args.expect_g31 and "Using Android presentation" not in selected:
            raise RuntimeError("Android presentation was not confirmed")
    report = {"score":int(score[1]), "activity":args.activity, "arguments":args.options,
              "process":pid, "scenes":scenes}
    (out/"result.json").write_text(json.dumps(report,ensure_ascii=False,indent=2))
    if screen:
        (out/"screen-times.json").write_text(json.dumps(screen.result(),indent=2))
    (out/"conditions-after.txt").write_text(conditions(adb))
    print(f"{out.name}: score {score[1]}, {len(scenes)} cases", flush=True)


if __name__ == "__main__":
    main()
