#!/usr/bin/env python3
"""Read-only cgroup CPU sample; no claims about battery discharge or wakeups."""
import argparse
import datetime
import json
import platform
from pathlib import Path
import time

SERVICES = (
    "ubuntu-gts9u-camera-relays", "iio-sensor-proxy",
    "hexagonrpcd-adsp-sensorspd", "ubuntu-gts9u-fingerprint-ui",
)


def snapshot():
    result = {}
    for service in SERVICES:
        group = Path("/sys/fs/cgroup/system.slice") / (service + ".service")
        try:
            counters = dict(line.split() for line in (group / "cpu.stat").read_text().splitlines())
            result[service] = (group.stat().st_ino, int(counters["usage_usec"]))
        except (FileNotFoundError, PermissionError):
            result[service] = None
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=20)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 60:
        parser.error("--seconds must be between 1 and 60")
    before = snapshot()
    start = time.monotonic()
    time.sleep(args.seconds)
    after = snapshot()
    elapsed = time.monotonic() - start
    cpu = {}
    for service in SERVICES:
        old, new = before[service], after[service]
        # Missing/recreated/reset cgroups are unavailable, not zero CPU usage.
        cpu[service] = ((new[1] - old[1]) / elapsed / 10000
                        if old and new and old[0] == new[0] and new[1] >= old[1]
                        else None)
    print(json.dumps({
        "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "kernel": platform.release(), "seconds": elapsed,
        "cpu_percent_one_core": cpu,
        "note": "No workloads stopped. Confirm no camera readers for idle comparisons; not a battery measurement.",
    }, indent=2))


if __name__ == "__main__":
    main()
