#!/bin/bash
# Publish processed-camera identities without restarting camera/audio services.
set -euo pipefail
[[ $EUID == 0 ]] || { echo 'Run with pkexec.' >&2; exit 1; }
repo=$(cd -- "$(dirname -- "$0")/.." && pwd)
rule=70-gts9u-camera.rules
candidate="$repo/packaging/ubuntu-gts9u-device/usr/lib/udev/rules.d/$rule"
names=(GTS9U-Front-Ultra-Wide GTS9U-Front-Main GTS9U-Rear-Main GTS9U-Rear-Ultra-Wide)
for i in 0 1 2 3; do
    node="/sys/class/video4linux/video$((20+i))"
    [[ $(<"$node/name") == "${names[$i]}" ]] || { echo "Unexpected camera: $node" >&2; exit 1; }
done
udevadm verify "$candidate"
backup=$(mktemp -d /var/lib/gts9u-camera-backups/stable-ids.XXXXXXXX)
cp -a "/usr/lib/udev/rules.d/$rule" "$backup/$rule"
install -m 0644 "$candidate" "/usr/lib/udev/rules.d/$rule"
udevadm control --reload-rules
for n in 20 21 22 23; do
    udevadm trigger --action=change "/sys/class/video4linux/video$n"
done
udevadm settle --timeout=10
echo "Previous rule saved in $backup"
ls -l /dev/v4l/by-id/platform-gts9u-*
