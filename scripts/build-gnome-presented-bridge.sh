#!/bin/bash
# Build the small GObject bridge against Ubuntu Noble's Mutter 14 headers.
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
base=${UBUNTU_WORKDIR:-/root/ubuntu-gts9u}
buildroot=${BUILDROOT_DIR:-$base/buildroot}
source=$repo/packaging/gnome-presented-bridge
stage=$buildroot/tmp/gts9u-presented-bridge
out=${PRESENTED_BRIDGE_OUT_DIR:-$base/out/gnome-presented-bridge}

if ! chroot "$buildroot" dpkg-query -W -f='${Status}\n' \
        libmutter-14-dev gobject-introspection 2>/dev/null | \
        awk '$0 == "install ok installed" { n++ } END { exit (n == 2 ? 0 : 1) }'; then
    # The rootfs builder may start with a minimal arm64 buildroot. Provision
    # only build-time headers and scanner there; never on the live tablet.
    mount --bind /dev "$buildroot/dev"
    mount -t proc proc "$buildroot/proc"
    trap 'umount "$buildroot/proc"; umount "$buildroot/dev"' EXIT
    chroot "$buildroot" apt-get update -qq
    chroot "$buildroot" env DEBIAN_FRONTEND=noninteractive \
        apt-get install -y --no-install-recommends \
        libmutter-14-dev gobject-introspection
fi
mkdir -p "$stage" "$out"
install -m0644 "$source/gts9u-presented-watcher.c" "$stage/"
install -m0644 "$source/gts9u-presented-watcher.h" "$stage/"
install -m0644 "$source/build.sh" "$stage/"
chroot "$buildroot" sh /tmp/gts9u-presented-bridge/build.sh
install -m0644 "$stage/libgts9u-presented.so" "$out/"
install -m0644 "$stage/Gts9uPresented-1.0.typelib" "$out/"
readelf -d "$out/libgts9u-presented.so" | grep -Fq \
    '/usr/lib/aarch64-linux-gnu/mutter-14'
sha256sum "$out/libgts9u-presented.so" "$out/Gts9uPresented-1.0.typelib"
