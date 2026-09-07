#!/bin/bash
# Install a previously built session bundle on the matching Ubuntu tablet.
# The service remains demand-started; the sleep hook only recovers sessions that
# were active when the machine entered suspend.
set -euo pipefail
if [ "$(id -u)" != 0 ] || [ "$#" != 1 ]; then
    echo "Usage: sudo $0 /path/to/npu-session-bundle" >&2
    exit 2
fi
bundle=$(realpath "$1")
runtime=/opt/gts9u-npu-bionic
target=/opt/gts9u-npu-session
tr '\0' '\n' < /proc/device-tree/compatible | grep -qx samsung,gts9uwifi
if systemctl is-active --quiet gts9u-npu.service; then
    echo 'Stop gts9u-npu.service before replacing its files.' >&2
    exit 1
fi
for module in gts9u_cdsp system_heap gts9u_fastrpc_prepared gts9u_cdsp_intents_probe; do
    test "$(modinfo -F vermagic "$bundle/modules/$module.ko" | cut -d' ' -f1)" = "$(uname -r)"
done
for file in bin/linker64 bin/probe-npu-htp bin/test-htp lib/libcdsprpc.so; do
    test -f "$runtime/$file"
done
python3 -c 'import dbus' || { echo 'Install python3-dbus first.' >&2; exit 1; }
test -x /opt/gts9u-npu/bin/cdsprpcd
install -d -m0755 "$target/bin" "$target/modules"
install -m0755 "$bundle/bin/"* "$target/bin/"
install -m0644 "$bundle/modules/"*.ko "$target/modules/"
install -m0644 "$bundle/gts9u-npu.service" /etc/systemd/system/
install -m0644 "$bundle/70-gts9u-npu.rules" /etc/udev/rules.d/
install -d -m0755 /usr/lib/systemd/system-sleep
install -m0755 "$bundle/gts9u-npu-sleep" /usr/lib/systemd/system-sleep/gts9u-npu-sleep
udevadm control --reload-rules
udevadm trigger --action=change --subsystem-match=dma_heap --sysname-match=system
systemctl daemon-reload
echo 'Installed. The Bionic runtime must include the FastRPC shell-search fix.'
echo 'Start explicitly: systemctl start gts9u-npu.service'
echo 'Validate: /opt/gts9u-npu-bionic/bin/test-htp 100'
echo 'Stop: systemctl stop gts9u-npu.service'
