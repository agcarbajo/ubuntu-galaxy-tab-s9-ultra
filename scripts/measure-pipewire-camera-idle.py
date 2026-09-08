#!/usr/bin/env python3
"""Read PipeWire CPU/memory and deduplicated DRM engine counters; no workload changes."""
import argparse
import json
from pathlib import Path
import subprocess
import time


def service():
    result = subprocess.check_output([
        "systemctl", "--user", "show", "pipewire.service",
        "-p", "MainPID", "-p", "ControlGroup"], text=True)
    values = dict(line.split("=", 1) for line in result.splitlines())
    pid = int(values["MainPID"])
    if not pid or not values["ControlGroup"].startswith("/"):
        raise RuntimeError("PipeWire is not running")
    return pid, Path("/sys/fs/cgroup") / values["ControlGroup"].lstrip("/")


def snapshot(pid, group):
    cpu = dict(line.split() for line in (group / "cpu.stat").read_text().splitlines())
    clients = {}
    # Duplicated DRM descriptors can expose the same engine time. Count each
    # DRM client once, not once per file descriptor.
    for fd in (Path("/proc") / str(pid) / "fdinfo").iterdir():
        try:
            fields = dict(line.split(":", 1) for line in fd.read_text().splitlines() if ":" in line)
        except FileNotFoundError:
            continue
        if "drm-client-id" in fields and "drm-engine-gpu" in fields:
            value, unit = fields["drm-engine-gpu"].split()
            if unit != "ns":
                raise RuntimeError("Unexpected DRM counter unit")
            clients[fields["drm-client-id"].strip()] = int(value)
    return {"cpu_us": int(cpu["usage_usec"]), "gpu_ns": clients,
            "memory_bytes": int((group / "memory.current").read_text())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=20)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 60:
        parser.error("--seconds must be between 1 and 60")
    pid, group = service()
    before = snapshot(pid, group)
    start = time.monotonic()
    time.sleep(args.seconds)
    after = snapshot(pid, group)
    elapsed = time.monotonic() - start
    if service() != (pid, group) or after["cpu_us"] < before["cpu_us"]:
        raise RuntimeError("PipeWire restarted; discard this sample")
    print(json.dumps({"pid": pid, "seconds": elapsed, "before": before, "after": after,
                      "cpu_percent_one_core": (after["cpu_us"] - before["cpu_us"]) / elapsed / 10000,
                      "note": "Compare matching DRM clients only. Missing counters are unavailable, not zero. Not a battery measurement."}, indent=2))


if __name__ == "__main__":
    main()
