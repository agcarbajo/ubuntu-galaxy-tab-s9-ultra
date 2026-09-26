#!/bin/bash
# Build the suite's pinned libfprint with the secure EL721 driver.
# Qualcomm's QTEE client and QCBOR are linked statically so the tablet needs no
# private runtime ABI.  Samsung's signed TA is deliberately a separate package.
set -euo pipefail

repo=$(cd "$(dirname "$0")/.." && pwd)
base=${UBUNTU_WORKDIR:-/root/ubuntu-gts9u}
buildroot=${BUILDROOT_DIR:-$base/buildroot}
out=${DEB_OUT_DIR:-$base/out/packages}
input=$repo/packaging/libfprint
suite=${UBUNTU_SUITE:-noble}
mirror=${UBUNTU_MIRROR:-http://ports.ubuntu.com/ubuntu-ports}

libfprint_commit=bebe8565cd7e2c89c0b0c5e6ee7353b80d6a51e1
quic_teec_commit=736419e25a2036aac3292a10a93e394a90750ca3
qcbor_commit=4ace4620d549f22c1163c5b00d3ae0c0dae1d207
case "$suite" in
  noble) default_version=1:1.94.7+tod1-0ubuntu5~24.04.8+gts9u51 ;;
  resolute) default_version=1:1.95.1+tod1-0ubuntu2+gts9u1 ;;
  *) echo "unsupported libfprint build suite: $suite" >&2; exit 2 ;;
esac
package_version=${LIBFPRINT_EL721_VERSION:-$default_version}

command -v mmdebstrap >/dev/null || {
	echo 'mmdebstrap is missing; run scripts/install-build-deps.sh' >&2
	exit 1
}
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

build_deps='build-essential cmake meson ninja-build pkg-config git ca-certificates
libglib2.0-dev libgusb-dev libgudev-1.0-dev libudev-dev libpixman-1-dev
libnss3-dev libssl-dev gettext'

step 'throwaway arm64 build chroot'
if [ ! -d "$buildroot/usr/bin" ]; then
	mmdebstrap \
		--architecture=arm64 \
		--variant=important \
		--components='main,restricted,universe,multiverse' \
		--include="$(printf '%s' "$build_deps" | tr -s ' \n' ',,' | sed 's/^,//;s/,$//')" \
		"$suite" "$buildroot" \
		"deb $mirror $suite main restricted universe multiverse" \
		"deb $mirror $suite-updates main restricted universe multiverse"
fi
rm -f "$buildroot/etc/resolv.conf"
cp /etc/resolv.conf "$buildroot/etc/resolv.conf"
if run "for package in $(printf '%s' "$build_deps" | tr '\n' ' '); do
  dpkg-query -W -f='\${db:Status-Status}' \"\$package\" 2>/dev/null | grep -qx installed || exit 1
done"; then
	echo 'build dependencies already present'
else
	run "export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends $(printf '%s' "$build_deps" | tr '\n' ' ') >/dev/null"
fi

step 'pinned sources'
src=$buildroot/build/el721-libfprint
rm -rf -- "$src"
mkdir -p "$src/input"
cp -a "$input/." "$src/input/"
cache=$base/cache/libfprint-el721
mkdir -p "$cache"
fetch_source() {
	local name=$1 url=$2 commit=$3 mirror_cache
	mirror_cache=$cache/$name.git
	if ! git -C "$mirror_cache" rev-parse --is-bare-repository \
		>/dev/null 2>&1; then
		rm -rf -- "$mirror_cache"
		git init --quiet --bare "$mirror_cache"
		git -C "$mirror_cache" remote add origin "$url"
	fi
	git -C "$mirror_cache" remote set-url origin "$url"
	if ! git -C "$mirror_cache" cat-file -e "$commit^{commit}" 2>/dev/null; then
		git -C "$mirror_cache" fetch --quiet --depth=1 origin "$commit"
	fi
	# Fetching an exact SHA only creates FETCH_HEAD, which clone does not copy.
	# Give the pinned commit a ref so an initially empty cache clones correctly.
	git -C "$mirror_cache" update-ref refs/heads/pinned "$commit"
	git clone --quiet --no-checkout "$mirror_cache" "$src/$name"
	git -C "$src/$name" checkout --quiet "$commit"
	test "$(git -C "$src/$name" rev-parse HEAD)" = "$commit"
}
if [ "$suite" = resolute ]; then
	# Resolute's TOD-bearing source is the ABI base for its fprintd package.
	# Pin all three files, including the .dsc, to the inspected Ubuntu archive.
	archive=$cache/resolute-source
	mkdir -p "$archive"
	fetch_archive() {
		local filename=$1 checksum=$2 target=$archive/$1
		if ! printf '%s  %s\n' "$checksum" "$target" | sha256sum -c --status; then
			curl --fail --location --silent --show-error \
				"https://ports.ubuntu.com/ubuntu-ports/pool/main/libf/libfprint/$filename" \
				-o "$target.part"
			mv "$target.part" "$target"
		fi
		printf '%s  %s\n' "$checksum" "$target" | sha256sum -c
	}
	fetch_archive libfprint_1.95.1+tod1.orig.tar.bz2 \
		b04c55ce1b1f0bcf97ca6e9e3dfbcad931ac2e8f87c29548c93d1aa69d9f6c60
	fetch_archive libfprint_1.95.1+tod1-0ubuntu2.debian.tar.xz \
		3abf87b13fe2ca2d24d8a34f8087efa0e0da877890bdc62986e78f1566565688
	fetch_archive libfprint_1.95.1+tod1-0ubuntu2.dsc \
		d2f0e9f33753d529bf27275a63afd0f3f34b733a344ae59ca07f8c79df6b25c1
	dpkg-source -x "$archive/libfprint_1.95.1+tod1-0ubuntu2.dsc" "$src/libfprint"
else
	fetch_source libfprint \
		https://gitlab.freedesktop.org/libfprint/libfprint.git "$libfprint_commit"
fi
fetch_source quic-teec \
	https://github.com/qualcomm/quic-teec.git "$quic_teec_commit"
fetch_source qcbor \
	https://github.com/laurencelundblade/QCBOR.git "$qcbor_commit"

if [ "$suite" = resolute ]; then
	patch --batch --fuzz=0 -d "$src/libfprint" -p1 \
		< "$input/patches/0001-el721-platform-driver-resolute.patch"
else
	git -C "$src/libfprint" apply "$input/patches/0001-el721-platform-driver.patch"
fi
git -C "$src/quic-teec" apply --recount \
	"$input/patches/0002-qcomtee-expose-memory-fd.patch" \
	"$input/patches/0003-qcomtee-register-dmabuf.patch"
install -m0644 "$input/el721.c" "$input/el721.h" \
	"$input/el721-qtee.c" "$input/el721-qtee.h" "$input/el721-enroll-wire.h" \
	"$input/el721-hwvault-wire.h" "$input/el721-qtee-lookup.h" "$input/el721-spl-wire.h" \
	"$input/el721-print-wire.h" "$input/el721-identify-wire.h" "$input/el721-gallery.h" \
	"$input/el721-match-retry.h" "$input/el721-touch-light.h" "$input/el721-ui-lease.h" \
	"$src/libfprint/libfprint/drivers/"

step 'offline touch-to-light lifecycle tests'
run 'cd /build/el721-libfprint/input
cc -std=c11 -Wall -Wextra -Werror $(pkg-config --cflags glib-2.0) \
  el721-ui-lease-test.c -o /tmp/el721-ui-lease-test \
  $(pkg-config --libs glib-2.0)
/tmp/el721-ui-lease-test'
run 'cd /build/el721-libfprint/input
cc -std=c11 -Wall -Wextra -Werror $(pkg-config --cflags glib-2.0) \
  el721-touch-light-test.c -o /tmp/el721-touch-light-test \
  $(pkg-config --libs glib-2.0)
/tmp/el721-touch-light-test'

step 'offline persisted identity tests'
run 'cd /build/el721-libfprint/input
cc -std=c11 -Wall -Wextra -Werror $(pkg-config --cflags glib-2.0) \
  el721-gallery-test.c -o /tmp/el721-gallery-test \
  $(pkg-config --libs glib-2.0)
/tmp/el721-gallery-test'
run 'cd /build/el721-libfprint/input
cc -std=c11 -Wall -Wextra -Werror $(pkg-config --cflags glib-2.0) \
  el721-print-wire-test.c -o /tmp/el721-print-wire-test \
  $(pkg-config --libs glib-2.0)
/tmp/el721-print-wire-test'

step 'offline match retry lifecycle tests'
run 'cd /build/el721-libfprint/input
cc -std=c11 -Wall -Wextra -Werror $(pkg-config --cflags glib-2.0) \
  el721-match-retry-test.c -o /tmp/el721-match-retry-test \
  $(pkg-config --libs glib-2.0)
/tmp/el721-match-retry-test'

step 'offline IdentifyDo protocol and contact-gating tests'
run 'cd /build/el721-libfprint/input
cc -std=c11 -Wall -Wextra -Werror $(pkg-config --cflags glib-2.0) \
  el721-identify-wire-test.c -o /tmp/el721-identify-wire-test \
  $(pkg-config --libs glib-2.0)
/tmp/el721-identify-wire-test'

step 'offline EnrollDo protocol tests'
run 'cd /build/el721-libfprint/input
cc -std=c11 -Wall -Wextra -Werror $(pkg-config --cflags glib-2.0) \
  el721-enroll-wire-test.c -o /tmp/el721-enroll-wire-test \
  $(pkg-config --libs glib-2.0)
/tmp/el721-enroll-wire-test'

step 'offline HwVault restore tests'
run 'cd /build/el721-libfprint/input
cc -std=c11 -Wall -Wextra -Werror $(pkg-config --cflags glib-2.0) \
  el721-hwvault-wire-test.c -o /tmp/el721-hwvault-wire-test \
  $(pkg-config --libs glib-2.0)
/tmp/el721-hwvault-wire-test'

step 'static QTEE dependencies'
run 'cd /build/el721-libfprint
cmake -S qcbor -B build-qcbor -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=OFF -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
  -DCMAKE_INSTALL_PREFIX=/build/el721-libfprint/qtee-prefix >/dev/null
cmake --build build-qcbor -j2 >/dev/null
cmake --install build-qcbor >/dev/null
cmake -S quic-teec -B build-qcomtee -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=OFF -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
  -DCMAKE_INSTALL_PREFIX=/build/el721-libfprint/qtee-prefix \
  -DQCBOR_DIR_HINT=/build/el721-libfprint/qtee-prefix >/dev/null
cmake --build build-qcomtee -j2 >/dev/null
cmake --install build-qcomtee >/dev/null'

step 'offline QTEE lookup ABI tests'
run 'cd /build/el721-libfprint/input
cc -std=c11 -Wall -Wextra -Werror $(pkg-config --cflags glib-2.0) \
  -I/build/el721-libfprint/qtee-prefix/include \
  el721-qtee-lookup-test.c -o /tmp/el721-qtee-lookup-test \
  $(pkg-config --libs glib-2.0)
/tmp/el721-qtee-lookup-test'

step 'offline SPL callback protocol tests'
run 'cd /build/el721-libfprint/input
cc -std=c11 -Wall -Wextra -Werror $(pkg-config --cflags glib-2.0) \
  -I/build/el721-libfprint/qtee-prefix/include \
  el721-spl-wire-test.c -o /tmp/el721-spl-wire-test \
  $(pkg-config --libs glib-2.0)
/tmp/el721-spl-wire-test'

step 'libfprint EL721 build'
run 'cd /build/el721-libfprint
mkdir -p libfprint/el721-qtee-deps/include libfprint/el721-qtee-deps/lib
cp -a qtee-prefix/include/. libfprint/el721-qtee-deps/include/
cp qtee-prefix/lib/libqcomtee.a qtee-prefix/lib/libqcbor.a \
  libfprint/el721-qtee-deps/lib/
meson setup libfprint/build libfprint --prefix=/usr --libdir=lib/aarch64-linux-gnu \
  -Ddrivers=default -Ddoc=false -Dintrospection=false \
  -Dinstalled-tests=false -Dudev_rules=enabled \
  -Dudev_rules_dir=/usr/lib/udev/rules.d \
  -Dudev_hwdb_dir=/usr/lib/udev/hwdb.d
meson compile -C libfprint/build
DESTDIR=/build/el721-libfprint/stage meson install --no-rebuild -C libfprint/build'

# Debian's runtime package is stripped; do the same before copying out of the
# arm64 chroot so the host never needs a cross-binutils installation.
run 'strip --strip-unneeded \
  /build/el721-libfprint/stage/usr/lib/aarch64-linux-gnu/libfprint-2.so.2.0.0'
if [ "$suite" = resolute ]; then
	run 'strip --strip-unneeded \
  /build/el721-libfprint/stage/usr/lib/aarch64-linux-gnu/libfprint-2-tod.so.1'
fi

step 'runtime Debian package'
staging=$base/build/deb/libfprint-2-2
rm -rf -- "$staging"
mkdir -p "$staging/DEBIAN" "$staging/usr/lib/aarch64-linux-gnu" \
	"$staging/usr/lib/udev/hwdb.d" "$staging/usr/lib/udev/rules.d" \
	"$staging/usr/share/doc/libfprint-2-2"
install -m0755 "$src/stage/usr/lib/aarch64-linux-gnu/libfprint-2.so.2.0.0" \
	"$staging/usr/lib/aarch64-linux-gnu/"
ln -s libfprint-2.so.2.0.0 "$staging/usr/lib/aarch64-linux-gnu/libfprint-2.so.2"
install -m0644 "$src/libfprint/data/autosuspend.hwdb" \
	"$staging/usr/lib/udev/hwdb.d/"
mv "$staging/usr/lib/udev/hwdb.d/autosuspend.hwdb" \
	"$staging/usr/lib/udev/hwdb.d/60-autosuspend-libfprint-2.hwdb"
install -m0644 "$src/stage/usr/lib/udev/rules.d/70-libfprint-2.rules" \
	"$staging/usr/lib/udev/rules.d/"
install -m0644 "$input/copyright" "$staging/usr/share/doc/libfprint-2-2/"

if [ "$suite" = resolute ]; then
	package_depends="libc6 (>= 2.38), libfprint-2-tod1 (= $package_version), libglib2.0-0t64 (>= 2.80), libgudev-1.0-0 (>= 146), libgusb2a (>= 0.3.3), libssl3t64 (>= 3.0.0)"
else
	package_depends='libc6 (>= 2.38), libglib2.0-0t64 (>= 2.68), libgudev-1.0-0 (>= 146), libgusb2 (>= 0.3.3), libnss3 (>= 2:3.13.4-2~), libpixman-1-0 (>= 0.30)'
fi

cat > "$staging/DEBIAN/control" <<EOF
Package: libfprint-2-2
Version: $package_version
Section: libs
Priority: optional
Architecture: arm64
Maintainer: Ubuntu gts9uwifi port contributors <noreply@example.invalid>
Depends: $package_depends
Breaks: ubuntu-gts9u-device (<< 2.62)
Description: libfprint with secure EgisTec EL721 support for the SM-X910
 Full upstream libfprint runtime plus the Galaxy Tab S9 Ultra platform driver.
 Fingerprint images and templates stay inside Samsung's signed TrustZone app.
EOF
cat > "$staging/DEBIAN/shlibs" <<EOF
libfprint-2 2 libfprint-2-2 (>= $package_version)
EOF
printf 'activate-noawait ldconfig\n' > "$staging/DEBIAN/triggers"

chown -R root:root "$staging"
find "$staging" -type d -exec chmod 0755 {} +
find "$staging" -type f -exec chmod 0644 {} +
chmod 0755 "$staging/usr/lib/aarch64-linux-gnu/libfprint-2.so.2.0.0"
find "$staging" -exec touch -h -d '@0' {} +
file_version=${package_version#*:}
deb=$out/libfprint-2-2_${file_version}_arm64.deb
dpkg-deb --root-owner-group --build "$staging" "$deb" >/dev/null

step 'verification'
dpkg-deb --info "$deb"
readelf -d "$staging/usr/lib/aarch64-linux-gnu/libfprint-2.so.2.0.0" | \
	grep NEEDED
sha256sum "$deb"

if [ "$suite" = resolute ]; then
	# The TOD library shares private libfprint structures with the EL721 core.
	# Ship both from the same patched source and require their exact pairing.
	tod_staging=$base/build/deb/libfprint-2-tod1
	rm -rf -- "$tod_staging"
	mkdir -p "$tod_staging/DEBIAN" "$tod_staging/usr/lib/aarch64-linux-gnu" \
		"$tod_staging/usr/share/doc/libfprint-2-tod1"
	install -m0755 "$src/stage/usr/lib/aarch64-linux-gnu/libfprint-2-tod.so.1" \
		"$tod_staging/usr/lib/aarch64-linux-gnu/"
	install -m0644 "$input/copyright" "$tod_staging/usr/share/doc/libfprint-2-tod1/"
	cat > "$tod_staging/DEBIAN/control" <<EOF
Package: libfprint-2-tod1
Version: $package_version
Section: libs
Priority: optional
Architecture: arm64
Maintainer: Ubuntu gts9uwifi port contributors <noreply@example.invalid>
Depends: libc6 (>= 2.29), libglib2.0-0t64 (>= 2.80.0), libgusb2a (>= 0.2.4), libpixman-1-0 (>= 0.30.0), libssl3t64 (>= 3.0.0)
Description: Matched TOD library for the SM-X910 EL721 libfprint build
 Built from the same patched Ubuntu source as the EL721-enabled core library.
EOF
	printf 'libfprint-2-tod 1 libfprint-2-tod1 (>= %s)\n' \
		"$package_version" > "$tod_staging/DEBIAN/shlibs"
	printf 'activate-noawait ldconfig\n' > "$tod_staging/DEBIAN/triggers"
	chown -R root:root "$tod_staging"
	find "$tod_staging" -type d -exec chmod 0755 {} +
	find "$tod_staging" -type f -exec chmod 0644 {} +
	chmod 0755 "$tod_staging/usr/lib/aarch64-linux-gnu/libfprint-2-tod.so.1"
	find "$tod_staging" -exec touch -h -d '@0' {} +
	tod_deb=$out/libfprint-2-tod1_${file_version}_arm64.deb
	dpkg-deb --root-owner-group --build "$tod_staging" "$tod_deb" >/dev/null
	test "$(dpkg-deb -f "$tod_deb" Version)" = "$(dpkg-deb -f "$deb" Version)"
	sha256sum "$tod_deb"
fi
