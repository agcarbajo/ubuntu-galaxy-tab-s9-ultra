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
# Test imports may leave ignored bytecode beside extensionless Python helpers.
# Generated caches are not package source or reproducible runtime artifacts.
find "$staging" -type f -name '*.pyc' -delete
find "$staging" -type d -name '__pycache__' -empty -delete

# Boot-lifetime native secure owner and the matching signed IRQ module are
# built separately. No proprietary runtime/firmware bytes enter this package.
owner=$base/out/fingerprint-secure/ubuntu-gts9u-fingerprint-secure-owner
irq=$base/out/spss-irq-module/qcom_spss_irq.ko
test -x "$owner" || { echo 'Run scripts/build-fingerprint-secure-owner.sh first' >&2; exit 1; }
test -f "$irq" || { echo 'Run scripts/build-spss-irq-module.sh first' >&2; exit 1; }
release=$(modinfo -F vermagic "$irq" | cut -d' ' -f1)
test -n "$(modinfo -F signer "$irq")"
[[ "$release" =~ ^[a-zA-Z0-9.+_-]+$ ]]
install -m0755 "$owner" "$staging/usr/libexec/"
install -d "$staging/usr/lib/modules/$release/updates"
install -m0644 "$irq" "$staging/usr/lib/modules/$release/updates/"

# --- flashlight tile translations -----------------------------------------
# The one place where what ships is not byte-for-byte what is versioned: the
# catalogues are kept as .po next to the extension, because a .po is reviewable
# and a .mo is not, and they are compiled here.  The .po sources are then
# dropped from the staging tree so the package carries only the compiled form.
#
# The tile's source string is English, so a language with no catalogue falls
# back to "Flashlight" rather than showing everyone Spanish.
extension=$staging/usr/share/gnome-shell/extensions/flashlight@ubuntu-gts9u
if [ -d "$extension/po" ]; then
	command -v msgfmt >/dev/null || {
		echo 'msgfmt is missing; run scripts/install-build-deps.sh' >&2
		exit 1
	}
	compiled=0
	for po in "$extension"/po/*.po; do
		lang=$(basename "$po" .po)
		install -d "$extension/locale/$lang/LC_MESSAGES"
		msgfmt -o "$extension/locale/$lang/LC_MESSAGES/gts9u-flashlight.mo" "$po"
		compiled=$((compiled + 1))
	done
	rm -rf -- "$extension/po"
	echo "flashlight translations compiled: $compiled"
	[ "$compiled" -gt 0 ] || { echo 'no catalogues compiled' >&2; exit 1; }
fi

# Normalise ownership and modes: a package must not inherit whatever the build
# host happened to have.
chown -R root:root "$staging"
find "$staging" -type d -exec chmod 0755 {} +
find "$staging" -type f -exec chmod 0644 {} +
find "$staging/usr/libexec" -type f -exec chmod 0755 {} + 2>/dev/null || true
find "$staging/usr/bin" -type f -name 'gts9u-*' -exec chmod 0755 {} + 2>/dev/null || true
find "$staging/usr/lib/systemd/system-sleep" -type f -exec chmod 0755 {} + \
	2>/dev/null || true
# initramfs-tools refuses to run a hook that is not executable, and silently
# skips it rather than failing the build.
find "$staging/usr/share/initramfs-tools" -type f -exec chmod 0755 {} + \
	2>/dev/null || true
find "$staging/DEBIAN" -type f -name 'p*inst' -exec chmod 0755 {} + 2>/dev/null || true
find "$staging/DEBIAN" -type f -name 'p*rm' -exec chmod 0755 {} + 2>/dev/null || true

# Deterministic output: without a fixed mtime the .deb changes hash on every
# build even when its contents do not.
find "$staging" -exec touch -h -d '@0' {} +

dpkg-deb --root-owner-group --build "$staging" "$deb"
dpkg-deb --contents "$deb"
sha256sum "$deb"
