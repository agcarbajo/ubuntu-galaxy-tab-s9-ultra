#!/bin/bash
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
base=${UBUNTU_WORKDIR:-/root/ubuntu-gts9u}
buildroot=${BUILDROOT_DIR:-$base/buildroot}
out=${DEB_OUT_DIR:-$base/out/packages}
version=46.2-1ubuntu0.24.04.16+gts9u1
test -x "$buildroot/usr/bin/apt-get"
mkdir -p "$out"
cat > "$buildroot/etc/apt/sources.list.d/gts9u-mutter-source.list" <<'EOF'
deb-src http://ports.ubuntu.com/ubuntu-ports noble main restricted universe multiverse
deb-src http://ports.ubuntu.com/ubuntu-ports noble-updates main restricted universe multiverse
EOF
install -m0644 "$repo/packaging/mutter/preserve-crtc-plane-assignments.patch" \
    "$buildroot/tmp/gts9u-mutter-plane.patch"
mount --bind /dev "$buildroot/dev"
mount -t proc proc "$buildroot/proc"
trap 'umount -l "$buildroot/proc"; umount -l "$buildroot/dev"' EXIT
chroot "$buildroot" /bin/bash -euo pipefail <<'EOF'
export DEBIAN_FRONTEND=noninteractive
export DEBEMAIL=noreply@example.invalid DEBFULLNAME="Ubuntu gts9uwifi port contributors"
apt-get update -qq
apt-get build-dep -y --no-install-recommends mutter
mkdir -p /build/mutter-gts9u
cd /build/mutter-gts9u
apt-get source --download-only mutter=46.2-1ubuntu0.24.04.16
work=$(mktemp -d /build/mutter-gts9u/source.XXXXXX)
dpkg-source -x mutter_46.2-1ubuntu0.24.04.16.dsc "$work/tree"
cd "$work/tree"
patch --batch --fuzz=0 -p1 < /tmp/gts9u-mutter-plane.patch
{
    printf '%s\n' 'mutter (46.2-1ubuntu0.24.04.16+gts9u1) noble; urgency=medium' ''
    printf '%s\n' '  * Preserve compatible primary and cursor plane assignments across monitor reconfiguration.' ''
    printf ' -- Ubuntu gts9uwifi port contributors <noreply@example.invalid>  %s\n\n' "$(date -R)"
    cat debian/changelog
} > debian/changelog.gts9u
mv debian/changelog.gts9u debian/changelog
DEB_BUILD_OPTIONS='nocheck parallel=8' dpkg-buildpackage -b -uc -us
for package in gir1.2-mutter-14 libmutter-14-0 mutter mutter-common mutter-common-bin; do
    cp ../${package}_*+gts9u1_*.deb /build/mutter-gts9u/
done
EOF
for package in gir1.2-mutter-14 libmutter-14-0 mutter mutter-common mutter-common-bin; do
    cp "$buildroot"/build/mutter-gts9u/${package}_${version}_*.deb "$out/"
done
