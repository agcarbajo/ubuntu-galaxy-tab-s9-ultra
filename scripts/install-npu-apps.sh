#!/bin/bash
set -euo pipefail
if [ "$(id -u)" != 0 ] || [ "$#" != 1 ]; then
    echo "Usage: sudo $0 /path/to/apps-bundle" >&2
    exit 2
fi
bundle=$(realpath "$1")
tr '\0' '\n' < /proc/device-tree/compatible | grep -qx samsung,gts9uwifi
test -x /usr/local/bin/gts9u-ai
python3 -c 'import gi; gi.require_version("Gtk", "4.0"); from gi.repository import Gtk'
exec 9<>/run/lock/gts9u-npu-users.lock
flock -n -x 9 || { echo 'Finish active AI applications first.' >&2; exit 1; }
! systemctl is-active --quiet gts9u-npu.service
(cd "$bundle" && sha256sum -c SHA256SUMS)
for component in llama whisper; do
    install -d -m0755 "/opt/gts9u-npu-$component"
    cp -a "$bundle/$component/." "/opt/gts9u-npu-$component/"
done
install -m0755 "$bundle/integration/gts9u-npu-app.py" /usr/local/bin/gts9u-npu-app
install -m0755 "$bundle/integration/gts9u-ai-studio.py" /usr/local/bin/gts9u-ai-studio
install -d -m0755 /usr/share/gts9u-ai
install -m0644 "$bundle/integration/model-catalog.json" /usr/share/gts9u-ai/model-catalog.json
install -m0644 "$bundle/integration/verified-models.json" /usr/share/gts9u-ai/verified-models.json
install -m0644 "$bundle/integration/io.github.agcarbajo.LocalAI.desktop" /usr/share/applications/
echo 'Installed: IA local in the application menu.'
