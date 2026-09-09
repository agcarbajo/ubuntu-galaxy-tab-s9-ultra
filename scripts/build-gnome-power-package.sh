#!/bin/bash
# Rebuild Ubuntu's exact GNOME daemon source with the ambient-write fix.
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
base=${UBUNTU_WORKDIR:-/root/ubuntu-gts9u}
buildroot=${BUILDROOT_DIR:-$base/buildroot}
out=${DEB_OUT_DIR:-$base/out/packages}
test -x "$buildroot/usr/bin/apt-get"
mkdir -p "$out"
cat > "$buildroot/etc/apt/sources.list.d/gts9u-gnome-source.list" <<'EOF'
deb-src http://ports.ubuntu.com/ubuntu-ports noble main restricted universe multiverse
deb-src http://ports.ubuntu.com/ubuntu-ports noble-updates main restricted universe multiverse
EOF
install -m0644 "$repo/packaging/gnome-settings-daemon/skip-unchanged-ambient-brightness.patch" "$buildroot/tmp/gts9u-ambient.patch"
mount --bind /dev "$buildroot/dev"
mount -t proc proc "$buildroot/proc"
trap 'umount -l "$buildroot/proc"; umount -l "$buildroot/dev"' EXIT
chroot "$buildroot" /bin/bash -euo pipefail <<'EOF'
export DEBIAN_FRONTEND=noninteractive
export DEBEMAIL=noreply@example.invalid DEBFULLNAME="Ubuntu gts9uwifi port contributors"
apt-get update -qq
apt-get build-dep -y --no-install-recommends gnome-settings-daemon
mkdir -p /build/gnome-power-gts9u
cd /build/gnome-power-gts9u
apt-get source --download-only gnome-settings-daemon=46.0-1ubuntu1.24.04.1
# dpkg-source refuses an existing destination rather than reuse stale sources.
work=$(mktemp -d /build/gnome-power-gts9u/source.XXXXXX)
dpkg-source -x gnome-settings-daemon_46.0-1ubuntu1.24.04.1.dsc "$work/tree"
cd "$work/tree"
patch -p1 < /tmp/gts9u-ambient.patch
{
    printf '%s\n' 'gnome-settings-daemon (46.0-1ubuntu1.24.04.1+gts9u1) noble; urgency=medium' ''
    printf '%s\n' '  * Avoid redundant ambient writes while preserving smoothing.' ''
    printf ' -- Ubuntu gts9uwifi port contributors <noreply@example.invalid>  %s\n\n' "$(date -R)"
    cat debian/changelog
} > debian/changelog.gts9u
mv debian/changelog.gts9u debian/changelog
DEB_BUILD_OPTIONS='nocheck parallel=8' dpkg-buildpackage -b -uc -us
cp ../gnome-settings-daemon_*.deb ../gnome-settings-daemon-common_*.deb /build/gnome-power-gts9u/
EOF
cp "$buildroot"/build/gnome-power-gts9u/gnome-settings-daemon{,-common}_*+gts9u1_*.deb "$out/"