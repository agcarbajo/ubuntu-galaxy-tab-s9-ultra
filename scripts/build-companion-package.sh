#!/bin/bash
# Build Galaxy Companion from the pinned submodule, and the transitional
# ubuntu-gts9u-companion package that points at it.
#
# Tab Companion became Galaxy Companion and lives in its own repository
# (external/galaxy-companion); this port only pins the commit it ships.  The
# transitional package keeps the old name installable, so an updater that still
# requires ubuntu-gts9u-companion in a payload pulls galaxy-companion in.
set -euo pipefail

repo=$(cd "$(dirname "$0")/.." && pwd)
base=${UBUNTU_WORKDIR:-/root/ubuntu-gts9u}
out=${DEB_OUT_DIR:-$base/out/packages}
companion=$repo/external/galaxy-companion
test -f "$companion/scripts/build-companion-package.sh" || {
	echo 'Galaxy Companion submodule is not checked out: run git submodule update --init' >&2
	exit 1
}
mkdir -p "$out"

UBUNTU_WORKDIR=$base DEB_OUT_DIR=$out bash "$companion/scripts/build-companion-package.sh"

version=$(awk '/^Version:/ {print $2}' "$companion/packaging/galaxy-companion/DEBIAN/control")
transitional=$(awk '/^Version:/ {print $2}' "$repo/packaging/ubuntu-gts9u-companion/DEBIAN/control")
test "$version" = "$transitional" || {
	echo "ubuntu-gts9u-companion is $transitional but the pinned Galaxy Companion is $version" >&2
	exit 1
}
# Galaxy Companion's Debian version carries epoch 1 since its numbering
# restarted at 0.9.0; file names leave the epoch out, as dpkg does.
upstream=${version#*:}
staging=$base/build/deb/ubuntu-gts9u-companion
rm -rf -- "$staging"
mkdir -p "$staging"
cp -a "$repo/packaging/ubuntu-gts9u-companion/DEBIAN" "$staging/"
chown -R root:root "$staging"
find "$staging" -type d -exec chmod 0755 {} +
find "$staging" -type f -exec chmod 0644 {} +
find "$staging" -exec touch -h -d '@0' {} +
dpkg-deb --root-owner-group --build "$staging" "$out/ubuntu-gts9u-companion_${upstream}_all.deb"
sha256sum "$out/galaxy-companion_${upstream}_all.deb" "$out/ubuntu-gts9u-companion_${upstream}_all.deb"
