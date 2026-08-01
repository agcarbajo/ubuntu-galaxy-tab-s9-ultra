#!/bin/bash
# Build the three sensor userspace pieces Ubuntu does not ship, as .deb.
#
# The X910's motion sensors are not IIO devices on the AP: they live inside the
# ADSP and are reached over FastRPC and the Qualcomm Sensor Core protocol.
# Ubuntu's iio-sensor-proxy therefore has nothing to read, and GNOME never
# rotates.  Three pieces close that gap:
#
#   libssc             client for the Sensor Core (SSC) QMI protocol
#   hexagonrpcd        FastRPC daemon exposing the DSP sensor protection domain
#   iio-sensor-proxy   3.9 built with -Dssc-support=enabled; Ubuntu ships 3.5,
#                      which has no SSC support at all
#
# The build happens in a throwaway arm64 chroot, never in the rootfs that
# ships: an earlier version compiled in place and would have put the whole
# toolchain on the tablet.
set -euo pipefail

repo=$(cd "$(dirname "$0")/.." && pwd)
base=${UBUNTU_WORKDIR:-/root/ubuntu-gts9u}
buildroot=${BUILDROOT_DIR:-$base/buildroot}
out=${DEB_OUT_DIR:-$base/out/packages}
patches=$repo/packaging/sensors
suite=${UBUNTU_SUITE:-noble}
mirror=${UBUNTU_MIRROR:-http://ports.ubuntu.com/ubuntu-ports}

libssc_ver=${LIBSSC_VERSION:-0.4.4}
hexagonrpc_ver=${HEXAGONRPC_VERSION:-0.4.0}
isp_ver=${IIO_SENSOR_PROXY_VERSION:-3.9}

mkdir -p "$out"

mounted=0
mount_pseudo() {
	[ "$mounted" = 1 ] && return
	mount --bind /dev "$buildroot/dev"
	mkdir -p "$buildroot/dev/pts"
	mount -t devpts devpts "$buildroot/dev/pts" 2>/dev/null || true
	mount -t proc proc "$buildroot/proc"
	mount -t sysfs sys "$buildroot/sys"
	mounted=1
}
umount_pseudo() {
	[ "$mounted" = 0 ] && return
	umount -l "$buildroot/sys" 2>/dev/null || true
	umount -l "$buildroot/proc" 2>/dev/null || true
	umount -l "$buildroot/dev/pts" 2>/dev/null || true
	umount -l "$buildroot/dev" 2>/dev/null || true
	mounted=0
}
trap umount_pseudo EXIT

run() { mount_pseudo; chroot "$buildroot" /bin/bash -euo pipefail -c "$1"; }
step() { printf '\n########## %s\n' "$1"; }

# ---------------------------------------------------------------------------
step 'throwaway arm64 build chroot'
build_deps='build-essential ninja-build pkg-config git ca-certificates curl
python3-pip python3-setuptools python3-dev python3-gi python3-protobuf
libglib2.0-dev libgudev-1.0-dev libudev-dev
libqmi-glib-dev libmbim-glib-dev libqrtr-glib-dev
libprotobuf-c-dev protobuf-c-compiler libpolkit-gobject-1-dev'

if [ ! -d "$buildroot/usr/bin" ]; then
	mmdebstrap \
		--architecture=arm64 \
		--variant=important \
		--components='main,restricted,universe,multiverse' \
		--include="$(printf '%s' "$build_deps" | tr -s ' \n' ',,' | sed 's/^,//;s/,$//')" \
		"$suite" "$buildroot" \
		"deb $mirror $suite main restricted universe multiverse" \
		"deb $mirror $suite-updates main restricted universe multiverse"
else
	echo 'reusing the existing build chroot'
fi
# The chroot's /etc/resolv.conf is a symlink to systemd-resolved's stub, which
# does not exist here, so it dangles and cp refuses to write through it.
rm -f "$buildroot/etc/resolv.conf"
cp /etc/resolv.conf "$buildroot/etc/resolv.conf"

# Install the build dependencies every run, not only when the chroot is
# created: adding one later must not require rebuilding the whole chroot.
run "export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends $(printf '%s' "$build_deps" | tr '\n' ' ') >/dev/null
echo 'build dependencies present'"

# libssc 0.4.4 asks for meson >= 1.4.0 and noble ships 1.3.2.  Install a newer
# one with pip, inside this throwaway chroot only.
run 'if ! command -v meson >/dev/null || \
	dpkg --compare-versions "$(meson --version)" lt 1.4.0; then
	pip3 install --break-system-packages --quiet "meson>=1.4,<2" >/dev/null
fi
echo "meson $(meson --version)"'

# ---------------------------------------------------------------------------
package_tree() {
	# package_tree <staged-root-inside-chroot> <name> <version> <deps> <desc>
	local tree=$buildroot$1 name=$2 version=$3 depends=$4 desc=$5
	local pkgdir=$base/build/deb/$name
	rm -rf -- "$pkgdir"
	mkdir -p "$pkgdir/DEBIAN"
	cp -a "$tree/." "$pkgdir/"
	cat > "$pkgdir/DEBIAN/control" <<EOF
Package: $name
Version: $version
Section: misc
Priority: optional
Architecture: arm64
Maintainer: Ubuntu gts9uwifi port contributors <noreply@example.invalid>
Depends: $depends
Description: $desc
EOF
	chown -R root:root "$pkgdir"
	find "$pkgdir" -type d -exec chmod 0755 {} +
	find "$pkgdir" -type f -exec chmod 0644 {} +
	for d in usr/bin usr/sbin usr/libexec; do
		[ -d "$pkgdir/$d" ] && find "$pkgdir/$d" -type f -exec chmod 0755 {} +
	done
	find "$pkgdir" -name '*.so*' -type f -exec chmod 0755 {} + 2>/dev/null || true
	find "$pkgdir" -exec touch -h -d '@0' {} +
	dpkg-deb --root-owner-group --build "$pkgdir" \
		"$out/${name}_${version}_arm64.deb" >/dev/null
	echo "built ${name}_${version}_arm64.deb"
}

# ---------------------------------------------------------------------------
step "libssc $libssc_ver"
run "cd /build 2>/dev/null || mkdir -p /build && cd /build
rm -rf libssc stage-libssc
git clone --quiet --depth 1 --branch v$libssc_ver \
	https://codeberg.org/DylanVanAssche/libssc.git libssc
cd libssc
meson setup output --prefix=/usr --libdir=lib/aarch64-linux-gnu
meson compile -C output
DESTDIR=/build/stage-libssc meson install --no-rebuild -C output
echo 'libssc built'"

# The next two builds link against it, so it must be visible in the chroot.
run 'cp -a /build/stage-libssc/. / && ldconfig && echo "libssc available to the chroot"'

package_tree /build/stage-libssc libssc "$libssc_ver" \
	'libc6, libglib2.0-0t64, libqrtr-glib0, libprotobuf-c1' \
	'Client library for the Qualcomm Sensor Core (SSC)'

# ---------------------------------------------------------------------------
step "hexagonrpcd $hexagonrpc_ver"
mkdir -p "$buildroot/build"
cp "$patches/support-samsung-sensor-registry-writes.patch" "$buildroot/build/"
cp "$patches/10-fastrpc.rules" "$buildroot/build/"
run "cd /build
rm -rf hexagonrpc stage-hexagonrpcd
git clone --quiet --depth 1 --branch v$hexagonrpc_ver \
	https://github.com/linux-msm/hexagonrpc.git hexagonrpc
cd hexagonrpc
# Samsung's sensor firmware wants a writable registry cache; without this the
# sensor protection domain never publishes sns_registry.
patch -p1 < /build/support-samsung-sensor-registry-writes.patch
meson setup output --prefix=/usr
meson compile -C output
DESTDIR=/build/stage-hexagonrpcd meson install --no-rebuild -C output
install -Dm644 /build/10-fastrpc.rules \
	/build/stage-hexagonrpcd/usr/lib/udev/rules.d/10-fastrpc.rules
echo 'hexagonrpcd built'"

package_tree /build/stage-hexagonrpcd hexagonrpcd "$hexagonrpc_ver" \
	'libc6, adduser' \
	'Qualcomm FastRPC daemon exposing the DSP sensor protection domain'

# ---------------------------------------------------------------------------
step "iio-sensor-proxy $isp_ver with SSC support"
run "cd /build
rm -rf iio-sensor-proxy stage-isp isp.tar.gz
curl -fsSL -o isp.tar.gz \
	'https://gitlab.freedesktop.org/hadess/iio-sensor-proxy/-/archive/$isp_ver/iio-sensor-proxy-$isp_ver.tar.gz'
tar xf isp.tar.gz
mv iio-sensor-proxy-$isp_ver iio-sensor-proxy
cd iio-sensor-proxy
meson setup output --prefix=/usr \
	-Dssc-support=enabled \
	-Dsystemdsystemunitdir=/usr/lib/systemd/system
meson compile -C output
DESTDIR=/build/stage-isp meson install --no-rebuild -C output
echo 'iio-sensor-proxy built'"

package_tree /build/stage-isp iio-sensor-proxy "$isp_ver" \
	'libc6, dbus, libglib2.0-0t64, libgudev-1.0-0, libssc' \
	'IIO sensors to D-Bus proxy, built with Qualcomm SSC support'

step 'results'
ls -l "$out"/*.deb
sha256sum "$out"/*.deb
