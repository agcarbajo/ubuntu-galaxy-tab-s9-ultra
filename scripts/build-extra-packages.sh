#!/bin/bash
# Build desktop tools that Ubuntu 24.04 LTS does not ship, as .deb.
#
# fastfetch entered the Debian and Ubuntu archives after noble froze, so
# "apt install fastfetch" fails on 24.04 with no candidate.  Rather than tell
# every new installation to fetch a binary from the internet, build it here and
# install it into the rootfs like any other package.
#
# The build happens in the same throwaway arm64 chroot the sensor packages use,
# never in the rootfs that ships.
set -euo pipefail

repo=$(cd "$(dirname "$0")/.." && pwd)
base=${UBUNTU_WORKDIR:-/root/ubuntu-gts9u}
buildroot=${BUILDROOT_DIR:-$base/buildroot}
out=${DEB_OUT_DIR:-$base/out/packages}
suite=${UBUNTU_SUITE:-noble}
mirror=${UBUNTU_MIRROR:-http://ports.ubuntu.com/ubuntu-ports}

fastfetch_ver=${FASTFETCH_VERSION:-2.66.0}
# This port carries a patch, so the package must not claim to be the stock
# upstream release: a plain "2.66.0" would compare equal to the archive's
# and let an upgrade quietly drop the patch.
fastfetch_pkgver=${fastfetch_ver}-gts9u1
obs_gstreamer_commit=a936d45f7968a6211b9563e92eeb63de2ac45d82
obs_gstreamer_version=0.4.0+git20260809.a936d45-gts9u1

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
step 'build chroot'
build_deps='build-essential cmake pkg-config git ca-certificates
libpci-dev libvulkan-dev libwayland-dev libxrandr-dev libdconf-dev
libdbus-1-dev libdrm-dev libpulse-dev libchafa-dev zlib1g-dev
libegl-dev libglx-dev libosmesa6-dev libxcb-randr0-dev libsqlite3-dev
meson ninja-build libobs-dev libgstreamer1.0-dev
libgstreamer-plugins-base1.0-dev'

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
rm -f "$buildroot/etc/resolv.conf"
cp /etc/resolv.conf "$buildroot/etc/resolv.conf"

run "export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends $(printf '%s' "$build_deps" | tr '\n' ' ') >/dev/null
echo 'build dependencies present'"

# ---------------------------------------------------------------------------
step "fastfetch $fastfetch_ver"

# On ARM, fastfetch takes the CPU name from the device tree compatible and then
# skips /proc/cpuinfo entirely, which on this tablet prints "sm8550".  The
# kernel states "Qualcomm Snapdragon 8 Gen 2" in the conventional place; the
# patch makes fastfetch look there first.  Copied into the chroot because the
# repository lives on a path the chroot cannot see.
install -m 0644 "$repo/packaging/patches/fastfetch-prefer-cpuinfo-model-name.patch" \
	"$buildroot/tmp/fastfetch-prefer-cpuinfo-model-name.patch"

run "cd /build 2>/dev/null || mkdir -p /build && cd /build
rm -rf fastfetch stage-fastfetch
git clone --quiet --depth 1 --branch $fastfetch_ver \
	https://github.com/fastfetch-cli/fastfetch.git fastfetch
cd fastfetch
patch -p1 < /tmp/fastfetch-prefer-cpuinfo-model-name.patch
cmake -S . -B output \
	-DCMAKE_BUILD_TYPE=Release \
	-DCMAKE_INSTALL_PREFIX=/usr \
	-DBUILD_TESTS=OFF
cmake --build output --parallel \"\$(nproc)\" >/dev/null
DESTDIR=/build/stage-fastfetch cmake --install output >/dev/null
echo 'fastfetch built'
ls /build/stage-fastfetch/usr/bin/"

# fastfetch dlopens every optional library it touches, so the only thing it
# links against is the C library.  Assert that rather than assume it: a future
# release that starts linking something new must not ship with a Depends line
# that quietly understates it.
step 'confirm the binary links against nothing but libc'
needed=$(readelf -d "$buildroot/build/stage-fastfetch/usr/bin/fastfetch" |
	sed -n 's/.*NEEDED.*\[\(.*\)\]/\1/p' | sort)
printf '%s\n' "$needed"
expected=$(printf 'ld-linux-aarch64.so.1\nlibc.so.6\nlibm.so.6\n')
if [ "$needed" != "$expected" ]; then
	echo 'fastfetch now links against something else; update Depends' >&2
	exit 1
fi
deps='libc6'

# ---------------------------------------------------------------------------
step 'package'
pkgdir=$base/build/deb/fastfetch
rm -rf -- "$pkgdir"
mkdir -p "$pkgdir/DEBIAN"
cp -a "$buildroot/build/stage-fastfetch/." "$pkgdir/"
cat > "$pkgdir/DEBIAN/control" <<EOF
Package: fastfetch
Version: $fastfetch_pkgver
Section: utils
Priority: optional
Architecture: arm64
Maintainer: Ubuntu gts9uwifi port contributors <noreply@example.invalid>
Depends: $deps
Description: Fast system information tool
 Neofetch-like tool written in C.  Ubuntu 24.04 LTS predates fastfetch's
 arrival in the archive, so this port builds it from the upstream release
 tag and installs it with the rest of the image.
EOF
chown -R root:root "$pkgdir"
find "$pkgdir" -type d -exec chmod 0755 {} +
find "$pkgdir" -type f -exec chmod 0644 {} +
[ -d "$pkgdir/usr/bin" ] && find "$pkgdir/usr/bin" -type f -exec chmod 0755 {} +
find "$pkgdir" -exec touch -h -d '@0' {} +
dpkg-deb --root-owner-group --build "$pkgdir" \
	"$out/fastfetch_${fastfetch_pkgver}_arm64.deb" >/dev/null
echo "built fastfetch_${fastfetch_pkgver}_arm64.deb"

# ---------------------------------------------------------------------------
step "obs-gstreamer $obs_gstreamer_commit"

# Noble's OBS PipeWire module captures displays, not camera nodes.  This small
# upstream plugin adds a GStreamer source, which lets OBS consume each of the
# four named libcamera PipeWire nodes without a V4L2 compatibility shim.
# Ubuntu's libobs.pc accidentally contains CMake generator expressions in its
# Cflags.  Strip those expressions in a private pkg-config directory; never
# alter the build chroot's packaged file.
run "cd /build
rm -rf obs-gstreamer stage-obs-gstreamer obs-gstreamer-pkgconfig
git clone --quiet https://github.com/fzwoch/obs-gstreamer.git obs-gstreamer
cd obs-gstreamer
git checkout --quiet $obs_gstreamer_commit
install -d /build/obs-gstreamer-pkgconfig
sed 's/ \\$<[^ ]*>//g' /usr/lib/aarch64-linux-gnu/pkgconfig/libobs.pc \
	>/build/obs-gstreamer-pkgconfig/libobs.pc
export PKG_CONFIG_PATH=/build/obs-gstreamer-pkgconfig:/usr/lib/aarch64-linux-gnu/pkgconfig:/usr/share/pkgconfig
meson setup build --buildtype=release --prefix=/usr \
	--libdir=lib/aarch64-linux-gnu/obs-plugins
meson compile -C build
DESTDIR=/build/stage-obs-gstreamer meson install --no-rebuild -C build
test -s /build/stage-obs-gstreamer/usr/lib/aarch64-linux-gnu/obs-plugins/obs-gstreamer.so
echo 'obs-gstreamer built'"

step 'package obs-gstreamer'
pkgdir=$base/build/deb/obs-gstreamer-gts9u
rm -rf -- "$pkgdir"
mkdir -p "$pkgdir/DEBIAN"
cp -a "$buildroot/build/stage-obs-gstreamer/." "$pkgdir/"
cat > "$pkgdir/DEBIAN/control" <<EOF
Package: obs-gstreamer-gts9u
Version: $obs_gstreamer_version
Section: video
Priority: optional
Architecture: arm64
Maintainer: Ubuntu gts9uwifi port contributors <noreply@example.invalid>
Depends: obs-studio, gstreamer1.0-pipewire, gstreamer1.0-plugins-base,
 libgstreamer1.0-0, libgstreamer-plugins-base1.0-0
Description: GStreamer camera sources for OBS on the Galaxy Tab S9 Ultra
 Adds the upstream obs-gstreamer source plugin so OBS can consume the four
 libcamera cameras exposed by PipeWire on the SM-X910.
EOF
chown -R root:root "$pkgdir"
find "$pkgdir" -type d -exec chmod 0755 {} +
find "$pkgdir" -type f -exec chmod 0644 {} +
chmod 0755 "$pkgdir/usr/lib/aarch64-linux-gnu/obs-plugins/obs-gstreamer.so"
find "$pkgdir" -exec touch -h -d '@0' {} +
dpkg-deb --root-owner-group --build "$pkgdir" \
	"$out/obs-gstreamer-gts9u_${obs_gstreamer_version}_arm64.deb" >/dev/null
echo "built obs-gstreamer-gts9u_${obs_gstreamer_version}_arm64.deb"
