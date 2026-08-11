#!/bin/bash
# Build desktop tools that Ubuntu 24.04 LTS does not ship, as .deb.
#
# This builds fastfetch and the small on-demand V4L2 camera relay. The latter
# deliberately omits Ubuntu's v4l2loopback-dkms dependency: this port ships a
# module built and signed against its exact custom kernel instead.
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
v4l2_relayd_commit=80e8f54563f624fe2f80a954af8cce27cc3a9636
v4l2_relayd_version=0.1.2-gts9u12
obs_v4l2_commit=a4578a6a307e857b7ceafa2723cc1eb345f05100
obs_v4l2_version=30.0.2+dfsg-3build1-gts9u1
only=${ONLY_EXTRA_PACKAGE:-all}

case "$only" in
	all|fastfetch|v4l2-relayd|obs-v4l2) ;;
	*) echo "unknown ONLY_EXTRA_PACKAGE: $only" >&2; exit 2 ;;
esac

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
autoconf automake autoconf-archive libtool libglib2.0-dev
libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev
libobs-dev libv4l-dev libavcodec-dev libavformat-dev libavutil-dev libudev-dev'

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
if [ "$only" = all ] || [ "$only" = fastfetch ]; then
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
fi

# ---------------------------------------------------------------------------
if [ "$only" = all ] || [ "$only" = v4l2-relayd ]; then
step "v4l2-relayd $v4l2_relayd_commit"
install -m 0644 \
	"$repo/packaging/v4l2-relayd/patches/0001-recreate-input-after-stream-error.patch" \
	"$buildroot/tmp/v4l2-relayd-recovery.patch"
install -m 0644 \
	"$repo/packaging/v4l2-relayd/patches/0002-preempt-active-camera-on-handover.patch" \
	"$buildroot/tmp/v4l2-relayd-handover.patch"
run "cd /build
rm -rf v4l2-relayd-gts9u stage-v4l2-relayd
git clone --quiet https://git.launchpad.net/ubuntu/+source/v4l2-relayd \
	v4l2-relayd-gts9u
cd v4l2-relayd-gts9u
git checkout --quiet $v4l2_relayd_commit
git apply /tmp/v4l2-relayd-recovery.patch
git apply /tmp/v4l2-relayd-handover.patch
# v4l2-relayd is a single C source file. Compiling it directly avoids running
# architecture-independent autotools generators through slow ARM emulation and
# keeps unused upstream systemd/modprobe defaults out of this device package.
install -d /build/stage-v4l2-relayd/usr/bin
cc -std=gnu11 -O2 -Wall -Werror \
	-DG_LOG_DOMAIN=\\\"v4l2_relayd\\\" \
	-DV4L2_RELAYD_VERSION=\\\"0.1.2\\\" \
	-o /build/stage-v4l2-relayd/usr/bin/v4l2-relayd \
	src/v4l2-relayd.c \
	\$(pkg-config --cflags --libs glib-2.0 gio-unix-2.0 \
		gstreamer-1.0 gstreamer-app-1.0 gstreamer-video-1.0)
strip --strip-unneeded /build/stage-v4l2-relayd/usr/bin/v4l2-relayd
test -x /build/stage-v4l2-relayd/usr/bin/v4l2-relayd
echo 'v4l2-relayd built'"

step 'package v4l2-relayd'
pkgdir=$base/build/deb/v4l2-relayd-gts9u
rm -rf -- "$pkgdir"
mkdir -p "$pkgdir/DEBIAN"
cp -a "$buildroot/build/stage-v4l2-relayd/." "$pkgdir/"
cat > "$pkgdir/DEBIAN/control" <<EOF
Package: v4l2-relayd-gts9u
Version: $v4l2_relayd_version
Section: video
Priority: optional
Architecture: arm64
Maintainer: Ubuntu gts9uwifi port contributors <noreply@example.invalid>
Depends: libc6, libglib2.0-0t64, libgstreamer1.0-0,
 libgstreamer-plugins-base1.0-0, gstreamer1.0-pipewire,
 gstreamer1.0-plugins-base, gstreamer1.0-plugins-good
Provides: v4l2-relayd
Conflicts: v4l2-relayd
Replaces: v4l2-relayd
Description: On-demand V4L2 camera relay for the Galaxy Tab S9 Ultra
 Publishes the four processed libcamera PipeWire sources through ordinary
 V4L2 devices for browsers, OBS and other Linux camera applications.
EOF
chown -R root:root "$pkgdir"
find "$pkgdir" -type d -exec chmod 0755 {} +
find "$pkgdir" -type f -exec chmod 0644 {} +
chmod 0755 "$pkgdir/usr/bin/v4l2-relayd"
find "$pkgdir" -exec touch -h -d '@0' {} +
dpkg-deb --root-owner-group --build "$pkgdir" \
	"$out/v4l2-relayd-gts9u_${v4l2_relayd_version}_arm64.deb" >/dev/null
echo "built v4l2-relayd-gts9u_${v4l2_relayd_version}_arm64.deb"
fi

# ---------------------------------------------------------------------------
if [ "$only" = all ] || [ "$only" = obs-v4l2 ]; then
step "OBS V4L2 plugin $obs_v4l2_commit"
install -m 0644 \
	"$repo/packaging/obs-v4l2/patches/0001-hide-internal-camss-nodes.patch" \
	"$buildroot/tmp/obs-v4l2-gts9u.patch"
run "cd /build
rm -rf obs-v4l2-gts9u stage-obs-v4l2
git clone --quiet https://git.launchpad.net/ubuntu/+source/obs-studio \
	obs-v4l2-gts9u
cd obs-v4l2-gts9u
git checkout --quiet $obs_v4l2_commit
git apply /tmp/obs-v4l2-gts9u.patch
install -d /build/stage-obs-v4l2/usr/lib/obs-v4l2-gts9u
obs_cflags=\$(pkg-config --cflags libobs libavcodec libavformat libavutil libudev | \
	sed 's/ \\\$[^ ]*//g')
obs_libs=\$(pkg-config --libs libobs libavcodec libavformat libavutil libudev)
cc -std=gnu17 -O2 -fPIC -DHAVE_UDEV -shared -Wl,--no-undefined \
	-o /build/stage-obs-v4l2/usr/lib/obs-v4l2-gts9u/linux-v4l2.so \
	plugins/linux-v4l2/linux-v4l2.c \
	plugins/linux-v4l2/v4l2-controls.c \
	plugins/linux-v4l2/v4l2-input.c \
	plugins/linux-v4l2/v4l2-helpers.c \
	plugins/linux-v4l2/v4l2-output.c \
	plugins/linux-v4l2/v4l2-decoder.c \
	plugins/linux-v4l2/v4l2-udev.c \
	\$obs_cflags \$obs_libs \
	-lv4l2
strip --strip-unneeded \
	/build/stage-obs-v4l2/usr/lib/obs-v4l2-gts9u/linux-v4l2.so
echo 'OBS V4L2 plugin built'"

step 'package OBS V4L2 plugin'
pkgdir=$base/build/deb/obs-v4l2-gts9u
rm -rf -- "$pkgdir"
mkdir -p "$pkgdir/DEBIAN"
cp -a "$buildroot/build/stage-obs-v4l2/." "$pkgdir/"
cat > "$pkgdir/DEBIAN/control" <<EOF
Package: obs-v4l2-gts9u
Version: $obs_v4l2_version
Section: video
Priority: optional
Architecture: arm64
Maintainer: Ubuntu gts9uwifi port contributors <noreply@example.invalid>
Depends: obs-studio (= 30.0.2+dfsg-3build1), dpkg
Description: Safe OBS V4L2 device list for the Galaxy Tab S9 Ultra
 Replaces OBS's V4L2 source plugin with a device-specific build that hides
 raw Qualcomm CAMSS endpoints and exposes the four processed GTS9U cameras.
EOF
cat > "$pkgdir/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
target=/usr/lib/aarch64-linux-gnu/obs-plugins/linux-v4l2.so
divert=$target.distrib
owner=$(dpkg-divert --listpackage "$target" 2>/dev/null || true)
if [ -z "$owner" ]; then
	dpkg-divert --package obs-v4l2-gts9u --add --rename \
		--divert "$divert" "$target"
elif [ "$owner" != obs-v4l2-gts9u ]; then
	echo "unexpected diversion owner for $target: $owner" >&2
	exit 1
fi
install -m 0755 /usr/lib/obs-v4l2-gts9u/linux-v4l2.so "$target"
EOF
cat > "$pkgdir/DEBIAN/prerm" <<'EOF'
#!/bin/sh
set -e
case "$1" in
	remove|deconfigure)
		target=/usr/lib/aarch64-linux-gnu/obs-plugins/linux-v4l2.so
		divert=$target.distrib
		rm -f "$target"
		dpkg-divert --package obs-v4l2-gts9u --remove --rename \
			--divert "$divert" "$target"
		;;
esac
EOF
chown -R root:root "$pkgdir"
find "$pkgdir" -type d -exec chmod 0755 {} +
find "$pkgdir" -type f -exec chmod 0644 {} +
chmod 0755 "$pkgdir/DEBIAN/postinst" "$pkgdir/DEBIAN/prerm" \
	"$pkgdir/usr/lib/obs-v4l2-gts9u/linux-v4l2.so"
find "$pkgdir" -exec touch -h -d '@0' {} +
dpkg-deb --root-owner-group --build "$pkgdir" \
	"$out/obs-v4l2-gts9u_${obs_v4l2_version}_arm64.deb" >/dev/null
echo "built obs-v4l2-gts9u_${obs_v4l2_version}_arm64.deb"
fi
