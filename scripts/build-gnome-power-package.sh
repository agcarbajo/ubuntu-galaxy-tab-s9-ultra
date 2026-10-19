#!/bin/bash
# Rebuild Ubuntu's exact GNOME daemon source with the ambient-write fix.
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
base=${UBUNTU_WORKDIR:-/root/ubuntu-gts9u}
buildroot=${BUILDROOT_DIR:-$base/buildroot}
out=${DEB_OUT_DIR:-$base/out/packages}
suite=${UBUNTU_SUITE:-noble}
case "$suite" in
    noble)
        source_version=46.0-1ubuntu1.24.04.1
        patch_name=skip-unchanged-ambient-brightness.patch
        message='Avoid redundant ambient writes while preserving smoothing.' ;;
    resolute)
        source_version=50.0-1ubuntu1
        patch_name=ambient-target-hysteresis.patch
        message='Apply ambient target hysteresis while preserving smoothing and resets.' ;;
    *) echo "Unsupported GNOME suite: $suite" >&2; exit 1 ;;
esac
version=$source_version+gts9u1
test -x "$buildroot/usr/bin/apt-get"
mkdir -p "$out"
cat > "$buildroot/etc/apt/sources.list.d/gts9u-gnome-source.list" <<EOF
deb-src http://ports.ubuntu.com/ubuntu-ports $suite main restricted universe multiverse
deb-src http://ports.ubuntu.com/ubuntu-ports $suite-updates main restricted universe multiverse
EOF
owned_mounts=()
cleanup() { for point in "${owned_mounts[@]}"; do umount "$point"; done; }
trap cleanup EXIT
if ! mountpoint -q "$buildroot/dev"; then
    mount --bind /dev "$buildroot/dev"; owned_mounts+=("$buildroot/dev")
fi
if ! mountpoint -q "$buildroot/proc"; then
    mount -t proc proc "$buildroot/proc"; owned_mounts=("$buildroot/proc" "${owned_mounts[@]}")
fi
chroot "$buildroot" /bin/bash -euo pipefail -s -- "$source_version" "$suite" <<'EOF'
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
DEB_BUILD_PROFILES=nocheck apt-get build-dep -y --no-install-recommends "gnome-settings-daemon=$1"
mkdir -p "/build/gnome-power-$2"
cd "/build/gnome-power-$2"
apt-get source --download-only "gnome-settings-daemon=$1"
EOF
# Use native dpkg-source/tar: arm64 tar under WSL binfmt can fail openat
# with ENOSYS, as with the sensor package build.
stage=$buildroot/build/gnome-power-$suite
work=$(mktemp -d "$stage/source.XXXXXX")
dpkg-source --no-check -x "$stage/gnome-settings-daemon_$source_version.dsc" "$work/tree"
patch -d "$work/tree" -p1 < "$repo/packaging/gnome-settings-daemon/$patch_name"
if [ "$suite" = resolute ]; then
    python3 "$repo/scripts/test-ambient-target-hysteresis.py" "$work/tree/plugins/power/gsd-power-manager.c"
else
    python3 "$repo/scripts/test-ambient-brightness.py" "$work/tree/plugins/power/gsd-power-manager.c"
fi
chroot "$buildroot" /bin/bash -euo pipefail -s -- "${work#"$buildroot"}/tree" "$version" "$suite" "$message" <<'EOF'
export DEBEMAIL=noreply@example.invalid DEBFULLNAME="Ubuntu gts9uwifi port contributors"
cd "$1"
{
    printf 'gnome-settings-daemon (%s) %s; urgency=medium\n\n' "$2" "$3"
    printf '  * %s\n\n' "$4"
    printf ' -- Ubuntu gts9uwifi port contributors <noreply@example.invalid>  %s\n\n' "$(date -R)"
    cat debian/changelog
} > debian/changelog.gts9u
mv debian/changelog.gts9u debian/changelog
# Keep Debian's compilation, install, strip, dependency and control generation.
# Only the final archive operation runs natively below: emulated arm64 tar can
# also fail stat/openat with ENOSYS while dh_builddeb creates its data archive.
if grep -q '^override_dh_builddeb:' debian/rules; then
    echo 'Unexpected upstream dh_builddeb override; review the pinned recipe' >&2
    exit 1
fi
printf '\noverride_dh_builddeb:\n\t@true\n' >> debian/rules
DEB_BUILD_PROFILES=nocheck DEB_BUILD_OPTIONS='nocheck parallel=8' dpkg-buildpackage -Tbinary -uc -us
EOF
dpkg-deb --root-owner-group --build "$work/tree/debian/gnome-settings-daemon" \
    "$out/gnome-settings-daemon_${version}_arm64.deb"
dpkg-deb --root-owner-group --build "$work/tree/debian/gnome-settings-daemon-common" \
    "$out/gnome-settings-daemon-common_${version}_all.deb"
