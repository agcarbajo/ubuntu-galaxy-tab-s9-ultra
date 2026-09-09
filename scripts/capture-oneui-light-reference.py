#!/usr/bin/env python3
"""Capture the SM-X910's light-sensor reference over rooted ADB, locally only."""
import argparse
from pathlib import Path
import subprocess

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("serial")
p.add_argument("output", type=Path)
p.add_argument("--adb", default="adb")
a = p.parse_args()


def adb(*args, timeout=45):
    return subprocess.run([a.adb, "-s", a.serial, *args], check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=timeout).stdout


model = adb("shell", "getprop", "ro.product.model").decode().strip()
device = adb("shell", "getprop", "ro.product.device").decode().strip()
if model != "SM-X910" or device not in ("gts9u", "gts9uwifi"):
    raise SystemExit(f"Refusing device {model}/{device}")


def root(command):
    return adb("exec-out", "su", "-c", command)


if not root("id").startswith(b"uid=0"):
    raise SystemExit("Root access is unavailable")
a.output.mkdir(parents=True, exist_ok=False)
commands = {
    "build.txt": "uname -a; getprop ro.build.display.id; getprop ro.build.version.oneui; getprop ro.build.version.release",
    "sensorservice.txt": "dumpsys sensorservice",
    "display.txt": "dumpsys display",
    "sensor-processes.txt": "ps -A -o USER,PID,ARGS | grep -Ei 'sensor|ssc|adsp|factory'; command -v strace",
    "sensor-sysfs.txt": "ls -l /sys/class/sensors; for p in /sys/class/sensors/*light*; do echo PATH=$p; ls -l $p/; for n in name vendor lux raw_data brightness sensor_info; do if [ -f $p/$n ]; then echo ATTR=$n; cat $p/$n; fi; done; done",
    "registry-layout.txt": "find /vendor/etc/sensors /mnt/vendor/persist/sensors /persist/sensors -maxdepth 4 -type f 2>/dev/null",
    "firmware-sha256.txt": "sha256sum /vendor/firmware_mnt/image/adsp.mdt /vendor/firmware_mnt/image/adsp.b18 /vendor/bin/factory.ssc 2>/dev/null",
    "sensor-log.txt": "logcat -d -t 3000 | grep -Ei 'stk316|ambient_light|light_sensor|ssc_core|factory.ssc|sns_client|sns_ssc' | tail -300",
    "light-samples.txt": "for i in 1 2 3 4 5 6 7 8 9 10; do date +%s; for p in /sys/class/sensors/*light*; do for n in lux raw_data; do if [ -f $p/$n ]; then echo $p/$n; cat $p/$n; fi; done; done; sleep 1; done",
}
for name, command in commands.items():
    try:
        data = root(command + "; true")
    except subprocess.SubprocessError as e:
        data = str(e).encode()
    (a.output / name).write_bytes(data)
    print(name, len(data), flush=True)
