#!/usr/bin/env python3
"""Capture/discard 90 frames; report ISP timing, not image quality or battery life."""
import argparse
import json
import os
from pathlib import Path
import re
import resource
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera", type=int, choices=range(1, 5), default=1)
    parser.add_argument("--width", type=int, choices=(640, 1280, 1920), default=1280)
    parser.add_argument("--height", type=int, choices=(480, 720, 1080), default=720)
    parser.add_argument("--stage", type=Path, help="Private candidate stage; never installs it")
    parser.add_argument("--mode", choices=("cpu", "gpu"), default="cpu")
    args = parser.parse_args()
    if args.mode == "gpu" and not args.stage:
        parser.error("GPU testing requires an explicitly staged GPU build")
    env = os.environ.copy()
    env["LIBCAMERA_SOFTISP_MODE"] = args.mode
    cam = Path("/usr/bin/cam")
    if args.stage:
        stage = args.stage.resolve(strict=True)
        cam = stage / "usr/bin/cam"
        for path in (cam, stage / "usr/lib/aarch64-linux-gnu/libcamera.so.0.7",
                     stage / "usr/lib/aarch64-linux-gnu/libcamera/ipa",
                     stage / "usr/libexec/libcamera", stage / "usr/share/libcamera/ipa"):
            if not path.exists():
                parser.error(f"Incomplete stage: missing {path}")
        env["LD_LIBRARY_PATH"] = str(stage / "usr/lib/aarch64-linux-gnu")
        env["LIBCAMERA_IPA_MODULE_PATH"] = str(stage / "usr/lib/aarch64-linux-gnu/libcamera/ipa")
        env["LIBCAMERA_IPA_PROXY_PATH"] = str(stage / "usr/libexec/libcamera")
        env["LIBCAMERA_IPA_CONFIG_PATH"] = str(stage / "usr/share/libcamera/ipa")
    command = [str(cam), "-c", str(args.camera), "-s",
               f"width={args.width},height={args.height},pixelformat=XRGB8888",
               "--strict-formats", "--capture=90"]
    # timeout limits the capture and its children, including IPA proxies.
    command = ["timeout", "--signal=TERM", "--kill-after=3", "25", *command]
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    start = time.monotonic()
    result = subprocess.run(command, env=env, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)
    elapsed = time.monotonic() - start
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    frames = re.findall(r"seq:\s*(\d+)", result.stdout)
    timings = re.findall(r"processed \d+ frames in \d+us, (\d+) us/frame", result.stdout, re.I)
    cpu_seconds = after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime
    print(json.dumps({"camera": args.camera, "requested_mode": args.mode,
                      "stage": str(args.stage) if args.stage else None,
                      "requested_size": [args.width, args.height],
                      "returncode": result.returncode, "completed_frames": len(frames),
                      "wall_seconds": elapsed, "child_cpu_seconds": cpu_seconds,
                      "isp_us_per_frame": [int(value) for value in timings],
                      "log": result.stdout,
                      "note": "Requested GPU is not proof of hardware execution; inspect fallback/EGL logs. No pixels saved."}, indent=2))
    raise SystemExit(0 if result.returncode == 0 and len(frames) == 90 else 1)


if __name__ == "__main__":
    main()
