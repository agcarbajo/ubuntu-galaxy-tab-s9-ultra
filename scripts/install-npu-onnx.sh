#!/bin/bash
# Install the staged inference tools on the SM-X910; no boot-image changes.
set -euo pipefail
if [ "$(id -u)" != 0 ] || [ "$#" != 1 ]; then
    echo "Usage: sudo $0 /path/to/onnx-bundle" >&2
    exit 2
fi
bundle=$(realpath "$1")
tr '\0' '\n' < /proc/device-tree/compatible | grep -qx samsung,gts9uwifi
test -x /opt/gts9u-npu-session/bin/run-npu-session.py
test -x /opt/gts9u-npu-bionic/bin/linker64
python3 -c 'import numpy, PIL, dbus' || {
    echo 'Install python3-numpy python3-pil python3-dbus first.' >&2
    exit 1
}
if systemctl is-active --quiet gts9u-npu.service; then
    echo 'Finish active NPU sessions before replacing the runtime.' >&2
    exit 1
fi
python3 - "$bundle" <<'PY'
import hashlib, json, pathlib, sys
root = pathlib.Path(sys.argv[1])
manifest = json.loads((root / 'manifest.json').read_text())
for name, expected in manifest['files'].items():
    file = (root / name).resolve()
    if not file.is_relative_to(root) or hashlib.sha256(file.read_bytes()).hexdigest() != expected:
        raise SystemExit('Bundle validation failed: ' + name)
PY
target=/opt/gts9u-npu-onnx
install -d -m0755 "$target"
for directory in bin lib dsp models licenses; do
    install -d -m0755 "$target/$directory"
    cp -a "$bundle/$directory/." "$target/$directory/"
done
install -m0644 "$bundle/manifest.json" "$target/"
install -m0755 "$bundle/bin/gts9u-ai" /usr/local/bin/gts9u-ai
install -m0644 "$bundle/integration/49-gts9u-npu.rules" /etc/polkit-1/rules.d/
install -m0644 "$bundle/integration/gts9u-npu-tmpfiles.conf" /etc/tmpfiles.d/gts9u-npu.conf
systemd-tmpfiles --create /etc/tmpfiles.d/gts9u-npu.conf
echo 'Installed. Run as a member of render: gts9u-ai classify /path/to/image.jpg'
