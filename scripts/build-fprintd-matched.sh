#!/bin/bash
# Suite-matched daemon plus one additive, claim-private matched-finger signal.
# Reuse Ubuntu's runtime packaging and pair its unchanged PAM module.
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
base=${UBUNTU_WORKDIR:-/root/ubuntu-gts9u}
buildroot=${BUILDROOT_DIR:-$base/buildroot}
out=${DEB_OUT_DIR:-$base/out/packages}
suite=${UBUNTU_SUITE:-noble}
case "$suite" in
    noble) version=$(cat "$repo/packaging/fprintd/version") ;;
    resolute) version=$(cat "$repo/packaging/fprintd/version-resolute") ;;
    *) echo "unsupported fprintd suite: $suite" >&2; exit 2 ;;
esac
cache=$base/cache/fprintd-matched
mkdir -p "$cache" "$out" "$buildroot/build"

fetch() {
    local name=$1 url=$2 checksum=$3
    if ! printf '%s  %s\n' "$checksum" "$cache/$name" | sha256sum --check --status; then
        curl --fail --location --silent --show-error "$url/$name" -o "$cache/$name"
    fi
    printf '%s  %s\n' "$checksum" "$cache/$name" | sha256sum --check
}
if [ "$suite" = resolute ]; then
    source_url=https://ports.ubuntu.com/ubuntu-ports/pool/main/f/fprintd
    fetch fprintd_1.94.5.orig.tar.bz2 "$source_url" \
        597466f61fdd5bd1d8af4fe96d982eb07528d28e915200ad789279ed7d8dfb6d
    fetch fprintd_1.94.5-4.debian.tar.xz "$source_url" \
        587669733ded75b811ed04d5afc82ea3741e060b47938da9d969477b2e83dc88
    fetch fprintd_1.94.5-4.dsc "$source_url" \
        75bc3d56d70bacff47289e1e30783fb2f8f7fdd10da771aecfdbe84575767a7b
    fetch fprintd_1.94.5-4_arm64.deb "$source_url" \
        aeff991b9e8cdc0ab2e6c344798315b6bf1b2a9cc692372e8e82d783b704a2ab
    original=$cache/fprintd_1.94.5-4_arm64.deb
else
    fetch fprintd_1.94.3.orig.tar.bz2 \
        https://archive.ubuntu.com/ubuntu/pool/main/f/fprintd \
        969777bacf353706747998e50e6cec09117b2565a2e8681eba094a82
    fetch fprintd_1.94.3-1_arm64.deb \
        https://ports.ubuntu.com/ubuntu-ports/pool/main/f/fprintd \
        4d44dfed1910f2eb2abb9de62170b76c920bc801c8bc1fa12013a2b910fce5a1
    original=$cache/fprintd_1.94.3-1_arm64.deb
fi

# The existing Noble arm64 buildroot is also used for the device/libfprint
# packages. These are build dependencies ONLY, never installed on the tablet.
chroot "$buildroot" /bin/bash -ec '
export DEBIAN_FRONTEND=noninteractive
apt-get install -y --no-install-recommends build-essential meson ninja-build \
    pkg-config libfprint-2-dev libpolkit-gobject-1-dev libdbus-1-dev gettext
'
task=$(mktemp -d "$buildroot/build/fprintd-matched.XXXXXX")
inside=/build/$(basename "$task")
if [ "$suite" = resolute ]; then
    source=$task/source
    dpkg-source -x "$cache/fprintd_1.94.5-4.dsc" "$source"
else
    tar -xf "$cache/fprintd_1.94.3.orig.tar.bz2" -C "$task"
    source=$task/fprintd-v1.94.3
fi
patch -d "$source" -p1 < "$repo/packaging/fprintd/0001-matched-finger-signal.patch"
inside_source=$inside/${source##*/}
chroot "$buildroot" /bin/bash -ec "
meson setup '$inside_source/build' '$inside_source' \
    --prefix=/usr --libexecdir=libexec --localstatedir=/var --sysconfdir=/etc \
    -Dpam=false -Dman=false -Dgtk_doc=false -Dsystemd=false
ninja -C '$inside_source/build' src/fprintd
strip --strip-unneeded '$inside_source/build/src/fprintd'
"

stage=$task/package
dpkg-deb --raw-extract "$original" "$stage"
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
bash "$repo/scripts/build-fprintd-pam-package.sh" "$deb"
printf 'Build retained for inspection: %s\n' "$task"
