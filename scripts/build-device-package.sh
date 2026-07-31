#!/bin/bash
# Build the ubuntu-gts9u-device Debian package from packaging/.
#
# The tree under packaging/ubuntu-gts9u-device is the package layout verbatim,
# so what ships is exactly what is versioned here.
set -euo pipefail

repo=$(cd "$(dirname "$0")/.." && pwd)
base=${UBUNTU_WORKDIR:-/root/ubuntu-gts9u}
src=$repo/packaging/ubuntu-gts9u-device
out=${DEB_OUT_DIR:-$base/out/packages}

test -f "$src/DEBIAN/control"

version=$(awk '/^Version:/ {print $2}' "$src/DEBIAN/control")
arch=$(awk '/^Architecture:/ {print $2}' "$src/DEBIAN/control")
staging=$base/build/deb/ubuntu-gts9u-device
deb=$out/ubuntu-gts9u-device_${version}_${arch}.deb

rm -rf -- "$staging"
mkdir -p "$staging" "$out"
cp -a "$src/." "$staging/"

# Normalise ownership and modes: a package must not inherit whatever the build
# host happened to have.
chown -R root:root "$staging"
find "$staging" -type d -exec chmod 0755 {} +
find "$staging" -type f -exec chmod 0644 {} +
find "$staging/usr/libexec" -type f -exec chmod 0755 {} + 2>/dev/null || true
find "$staging/DEBIAN" -type f -name 'p*inst' -exec chmod 0755 {} + 2>/dev/null || true
find "$staging/DEBIAN" -type f -name 'p*rm' -exec chmod 0755 {} + 2>/dev/null || true

# Deterministic output: without a fixed mtime the .deb changes hash on every
# build even when its contents do not.
find "$staging" -exec touch -h -d '@0' {} +

dpkg-deb --root-owner-group --build "$staging" "$deb"
dpkg-deb --contents "$deb"
sha256sum "$deb"
