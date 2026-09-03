#!/bin/bash
# Noble daemon plus one additive, claim-private matched-finger signal.
# Reuse Ubuntu's runtime packaging; do not build or install a PAM module.
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
base=${UBUNTU_WORKDIR:-/root/ubuntu-gts9u}
buildroot=${BUILDROOT_DIR:-$base/buildroot}
out=${DEB_OUT_DIR:-$base/out/packages}
version=1.94.3-1+gts9u1
cache=$base/cache/fprintd-matched
mkdir -p "$cache" "$out" "$buildroot/build"

fetch() {
    local name=$1 url=$2 checksum=$3
    if ! printf '%s  %s\n' "$checksum" "$cache/$name" | sha256sum --check --status; then
        curl --fail --location --silent --show-error "$url/$name" -o "$cache/$name"
    fi
    printf '%s  %s\n' "$checksum" "$cache/$name" | sha256sum --check
}
fetch fprintd_1.94.3.orig.tar.bz2 \
    https://archive.ubuntu.com/ubuntu/pool/main/f/fprintd \
    969777bacf353706747998e50e5d55050e6cec09117b2565a2e8681eba094a82
fetch fprintd_1.94.3-1_arm64.deb \
    https://ports.ubuntu.com/ubuntu-ports/pool/main/f/fprintd \
    4d44dfed1910f2eb2abb9de62170b76c920bc801c8bc1fa12013a2b910fce5a1

# The existing Noble arm64 buildroot is also used for the device/libfprint
# packages. These are build dependencies ONLY, never installed on the tablet.
chroot "$buildroot" /bin/bash -ec '
export DEBIAN_FRONTEND=noninteractive
apt-get install -y --no-install-recommends build-essential meson ninja-build \
    pkg-config libfprint-2-dev libpolkit-gobject-1-dev libdbus-1-dev gettext
'
task=$(mktemp -d "$buildroot/build/fprintd-matched.XXXXXX")
inside=/build/$(basename "$task")
tar -xf "$cache/fprintd_1.94.3.orig.tar.bz2" -C "$task"
source=$task/fprintd-v1.94.3
patch -d "$source" -p1 < "$repo/packaging/fprintd/0001-matched-finger-signal.patch"
chroot "$buildroot" /bin/bash -ec "
meson setup '$inside/fprintd-v1.94.3/build' '$inside/fprintd-v1.94.3' \
    --prefix=/usr --libexecdir=libexec --localstatedir=/var --sysconfdir=/etc \
    -Dpam=false -Dman=false -Dgtk_doc=false -Dsystemd=false
ninja -C '$inside/fprintd-v1.94.3/build' src/fprintd
strip --strip-unneeded '$inside/fprintd-v1.94.3/build/src/fprintd'
"

stage=$task/package
dpkg-deb --raw-extract "$cache/fprintd_1.94.3-1_arm64.deb" "$stage"
install -m0755 "$source/build/src/fprintd" "$stage/usr/libexec/fprintd"
install -m0644 "$source/src/net.reactivated.Fprint.Device.xml" \
    "$stage/usr/share/dbus-1/interfaces/net.reactivated.Fprint.Device.xml"
install -m0644 "$repo/packaging/fprintd/0001-matched-finger-signal.patch" \
    "$repo/packaging/fprintd/README.md" "$stage/usr/share/doc/fprintd/"
sed -i "s/^Version: .*/Version: $version/" "$stage/DEBIAN/control"
sed -i 's/^Maintainer: .*/Maintainer: Ubuntu gts9uwifi port contributors <noreply@example.invalid>/' "$stage/DEBIAN/control"
sed -i "s/^Installed-Size: .*/Installed-Size: $(du -sk "$stage" | cut -f1)/" "$stage/DEBIAN/control"
(cd "$stage"; find . -type f ! -path './DEBIAN/*' -print0 | sort -z | xargs -0 md5sum > DEBIAN/md5sums)
find "$stage" -exec touch -h -d '@0' {} +
deb=$out/fprintd_${version}_arm64.deb
dpkg-deb --root-owner-group --build "$stage" "$deb"
readelf -h "$stage/usr/libexec/fprintd" | grep Machine
dpkg-deb --info "$deb"
sha256sum "$deb"
printf 'Build retained for inspection: %s\n' "$task"
