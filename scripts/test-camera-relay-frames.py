#!/usr/bin/env python3
"""Sequentially test live relays; optionally retain one private PNG per camera."""
import argparse
import hashlib
from pathlib import Path
import time
import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output-dir", type=Path)
parser.add_argument("--cycles", type=int, choices=range(1, 6), default=1)
args = parser.parse_args()
if args.output_dir:
    args.output_dir.mkdir(mode=0o700, parents=False, exist_ok=False)
Gst.init(None)
for cycle in range(args.cycles):
    for node in range(20, 24):
        pipeline = Gst.parse_launch(
            f"v4l2src device=/dev/video{node} io-mode=rw do-timestamp=true "
            "! video/x-raw,format=YUY2,width=640,height=480 "
            "! identity sleep-time=33333 ! videoconvert ! video/x-raw,format=RGB "
            "! appsink name=probe sync=false max-buffers=1 drop=true")
        sink = pipeline.get_by_name("probe")
        start = time.monotonic()
        hashes, frames, last = set(), 0, None
        try:
            pipeline.set_state(Gst.State.PLAYING)
            while time.monotonic() - start < 6:
                sample = sink.emit("try-pull-sample", Gst.SECOND)
                if sample is None:
                    continue
                buffer = sample.get_buffer()
                ok, mapped = buffer.map(Gst.MapFlags.READ)
                if ok:
                    last = bytes(mapped.data)
                    # Spatial variation excludes uniform splash frames. This
                    # is only a streaming check, not a focus/quality guarantee.
                    pixels = last[::48]
                    if max(pixels) - min(pixels) > 8:
                        hashes.add(hashlib.sha256(pixels).digest())
                    frames += 1
                    buffer.unmap(mapped)
        finally:
            pipeline.set_state(Gst.State.NULL)
            pipeline.get_state(3 * Gst.SECOND)
        if args.output_dir and last:
            from PIL import Image
            Image.frombytes("RGB", (640, 480), last).save(
                args.output_dir / f"cycle-{cycle}-video{node}.png")
        print(f"cycle={cycle} video{node} frames={frames} distinct_nonuniform={len(hashes)}", flush=True)
        if frames < 30 or len(hashes) < 3:
            raise SystemExit("Capture failed or scene unsuitable; inspect frames before accepting")
        time.sleep(1)
