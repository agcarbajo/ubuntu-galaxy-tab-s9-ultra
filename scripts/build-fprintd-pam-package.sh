#!/bin/bash
# Pair Ubuntu's PAM package with a module that skips gdm-password only.
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
base=${UBUNTU_WORKDIR:-/root/ubuntu-gts9u}
out=${DEB_OUT_DIR:-$base/out/packages}
cache=$base/cache/fprintd-matched
suite=${UBUNTU_SUITE:-noble}
case "$suite" in
    noble)
        version=$(cat "$repo/packaging/fprintd/version")
        original_version=1.94.3-1
        checksum=67ea92e4c4f4befd3df19696bae9fbf5126710216f049d38948dbba8564bb223 ;;
    resolute)
        version=$(cat "$repo/packaging/fprintd/version-resolute")
        original_version=1.94.5-4
        checksum=8595c667b26ba7d8b49e9cfecc9ed4a0e4b2ce7ad95dd67718ae49b37912a3a4 ;;
    *) echo "unsupported fprintd suite: $suite" >&2; exit 2 ;;
esac
daemon=${1:-$out/fprintd_${version}_arm64.deb}
module=${2:-}
test "$(dpkg-deb -f "$daemon" Package)" = fprintd
test "$(dpkg-deb -f "$daemon" Architecture)" = arm64
test "$(dpkg-deb -f "$daemon" Version)" = "$version"
mkdir -p "$cache" "$out" "$base/build"
original=$cache/libpam-fprintd_${original_version}_arm64.deb
if ! printf '%s  %s\n' "$checksum" "$original" | sha256sum --check --status; then
    curl --fail --location --silent --show-error \
        "https://ports.ubuntu.com/ubuntu-ports/pool/main/f/fprintd/libpam-fprintd_${original_version}_arm64.deb" \
        -o "$original"
fi
printf '%s  %s\n' "$checksum" "$original" | sha256sum --check
buildroot=${BUILDROOT_DIR:-$base/buildroot}
mkdir -p "$buildroot/build"
task=$(mktemp -d "$buildroot/build/fprintd-pam.XXXXXX")
stage=$task/package
dpkg-deb --raw-extract "$original" "$stage"
if test -z "$module"; then
    printf '%s  %s\n' \
        969777bacf353706747998e50e5d55050e6cec09117b2565a2e8681eba094a82 \
        "$cache/fprintd_1.94.3.orig.tar.bz2" | sha256sum --check
    chroot "$buildroot" /bin/bash -ec '
export DEBIAN_FRONTEND=noninteractive
apt-get install -y --no-install-recommends meson ninja-build pkg-config \
    libfprint-2-dev libpolkit-gobject-1-dev libdbus-1-dev gettext \
    libpam0g-dev libsystemd-dev
'
    tar -xf "$cache/fprintd_1.94.3.orig.tar.bz2" -C "$task"
    source=$task/fprintd-v1.94.3
    patch -d "$source" -p1 < "$repo/packaging/fprintd/0002-gdm-password-bypass-fingerprint.patch"
    inside=/build/$(basename "$task")
    chroot "$buildroot" /bin/bash -ec "
meson setup '$inside/fprintd-v1.94.3/build' '$inside/fprintd-v1.94.3' \
    --prefix=/usr --libexecdir=libexec --localstatedir=/var --sysconfdir=/etc \
    -Dpam=true -Dman=false -Dgtk_doc=false -Dsystemd=false
ninja -C '$inside/fprintd-v1.94.3/build' pam/pam_fprintd.so
strip --strip-unneeded '$inside/fprintd-v1.94.3/build/pam/pam_fprintd.so'
"
    module=$source/build/pam/pam_fprintd.so
fi
test -s "$module"
install -m0644 "$module" "$stage/usr/lib/aarch64-linux-gnu/security/pam_fprintd.so"
readelf -h "$stage/usr/lib/aarch64-linux-gnu/security/pam_fprintd.so" | grep -q 'Machine:.*AArch64'
readelf --dyn-syms "$stage/usr/lib/aarch64-linux-gnu/security/pam_fprintd.so" | grep -q 'pam_sm_authenticate'
install -Dm0644 "$repo/packaging/fprintd/0002-gdm-password-bypass-fingerprint.patch" \
    "$stage/usr/share/doc/libpam-fprintd/0002-gdm-password-bypass-fingerprint.patch"
# Never remove the dependency, use --force-depends or weaken authentication.
grep -Fq "fprintd (= $original_version)" "$stage/DEBIAN/control"
sed -i "s/^Version: .*/Version: $version/; s/fprintd (= $original_version)/fprintd (= $version)/" "$stage/DEBIAN/control"
sed -i 's/^Maintainer: .*/Maintainer: Ubuntu gts9uwifi port contributors <noreply@example.invalid>/' "$stage/DEBIAN/control"
(cd "$stage"; find . -type f ! -path './DEBIAN/*' -print0 | sort -z | xargs -0 md5sum > DEBIAN/md5sums)
find "$stage" -exec touch -h -d '@0' {} +
deb=$out/libpam-fprintd_${version}_arm64.deb
dpkg-deb --root-owner-group --build "$stage" "$deb"
bash "$repo/scripts/check-fprintd-package-pair.sh" "$daemon" "$deb"
python3 "$repo/scripts/test-fprintd-packages.py" "$daemon" "$deb" "$original"
sha256sum "$deb"
