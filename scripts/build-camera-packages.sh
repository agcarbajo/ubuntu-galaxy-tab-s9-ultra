#!/bin/bash
# Build the camera userspace that Noble does not provide at a usable version.
#
# The SM8550 CAMSS graph needs libcamera's current simple pipeline and CPU
# software ISP.  Noble's libcamera 0.2 predates that support.  PipeWire 1.0.5
# also needs seven small backports so its SPA plugin can consume libcamera 0.7
# controls, packed RGB buffers and the safe request-reuse lifecycle.
set -euo pipefail

repo=$(cd "$(dirname "$0")/.." && pwd)
base=${UBUNTU_WORKDIR:-/root/ubuntu-gts9u}
buildroot=${BUILDROOT_DIR:-$base/buildroot}
out=${DEB_OUT_DIR:-$base/out/packages}
suite=${UBUNTU_SUITE:-noble}
mirror=${UBUNTU_MIRROR:-http://ports.ubuntu.com/ubuntu-ports}

libcamera_commit=62d4bfc450798cbd57722fa349a245b93b11d1cd
libcamera_version=0.7.2+53.g62d4bfc-gts9u3
pipewire_commit=a2287be601710eea0d073261223ec34b92384c8a
pipewire_version=1.0.5-gts9u6
skip_build=${SKIP_CAMERA_BUILD:-0}
skip_libcamera_build=${SKIP_LIBCAMERA_BUILD:-$skip_build}
skip_pipewire_build=${SKIP_PIPEWIRE_BUILD:-$skip_build}

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

build_deps='build-essential meson ninja-build pkg-config git ca-certificates
python3 python3-jinja2 python3-yaml python3-ply
libgnutls28-dev libudev-dev libyaml-dev libdrm-dev libjpeg-dev libtiff-dev
libevent-dev libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev
libboost-dev libdw-dev libpipewire-0.3-dev'

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
if [ "$skip_build" != 1 ]; then
	run "export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends $(printf '%s' "$build_deps" | tr '\n' ' ') >/dev/null
echo 'camera build dependencies present'"
else
	echo 'reusing the existing camera build trees'
fi

package_tree() {
	local tree=$buildroot$1 name=$2 version=$3 depends=$4 desc=$5
	local extra_debian=${6:-}
	local pkgdir=$base/build/deb/$name
	rm -rf -- "$pkgdir"
	mkdir -p "$pkgdir/DEBIAN"
	cp -a "$tree/." "$pkgdir/"
	if [ -n "$extra_debian" ] && [ -d "$extra_debian" ]; then
		cp -a "$extra_debian/." "$pkgdir/DEBIAN/"
	fi
	cat > "$pkgdir/DEBIAN/control" <<EOF
Package: $name
Version: $version
Section: video
Priority: optional
Architecture: arm64
Maintainer: Ubuntu gts9uwifi port contributors <noreply@example.invalid>
Depends: $depends
Description: $desc
EOF
	case "$name" in
	libcamera-gts9u)
		cat >> "$pkgdir/DEBIAN/control" <<'EOF'
Provides: gstreamer1.0-libcamera, libcamera-tools
Conflicts: gstreamer1.0-libcamera, libcamera-tools
Replaces: gstreamer1.0-libcamera, libcamera-tools
EOF
		;;
	libspa-0.2-libcamera-gts9u)
		cat >> "$pkgdir/DEBIAN/control" <<'EOF'
Provides: libspa-0.2-libcamera
Conflicts: libspa-0.2-libcamera
Replaces: libspa-0.2-libcamera
EOF
		;;
	esac
	chown -R root:root "$pkgdir"
	find "$pkgdir" -type d -exec chmod 0755 {} +
	find "$pkgdir" -type f -exec chmod 0644 {} +
	find "$pkgdir/usr/bin" -type f -exec chmod 0755 {} + 2>/dev/null || true
	find "$pkgdir" -name '*.so*' -type f -exec chmod 0755 {} + 2>/dev/null || true
	for s in preinst postinst prerm postrm; do
		[ -f "$pkgdir/DEBIAN/$s" ] && chmod 0755 "$pkgdir/DEBIAN/$s"
	done
	find "$pkgdir" -exec touch -h -d '@0' {} +
	dpkg-deb --root-owner-group --build "$pkgdir" \
		"$out/${name}_${version}_arm64.deb" >/dev/null
	echo "built ${name}_${version}_arm64.deb"
}

rm -rf "$buildroot/build/camera-inputs"
mkdir -p \
	"$buildroot/build/camera-inputs/libcamera" \
	"$buildroot/build/camera-inputs/tuning" \
	"$buildroot/build/camera-inputs/pipewire"
cp "$repo/packaging/libcamera/patches/"*.patch \
	"$buildroot/build/camera-inputs/libcamera/"
cp "$repo/packaging/libcamera/tuning/"*.yaml \
	"$buildroot/build/camera-inputs/tuning/"
cp "$repo/packaging/pipewire/patches/"*.patch \
	"$buildroot/build/camera-inputs/pipewire/"

step "libcamera $libcamera_version"
if [ "$skip_libcamera_build" != 1 ]; then
	run "cd /build
rm -rf libcamera-gts9u stage-libcamera
git clone --quiet https://git.libcamera.org/libcamera/libcamera.git libcamera-gts9u
cd libcamera-gts9u
git checkout --quiet $libcamera_commit
git apply \
	/build/camera-inputs/libcamera/0001-libipa-add-hynix-hi1337-hi847-gain-helpers.patch \
	/build/camera-inputs/libcamera/0002-simple-software-autofocus.patch \
	/build/camera-inputs/libcamera/0003-software-isp-preserve-full-field-of-view.patch
meson setup build \
	--prefix=/usr \
	--libdir=lib/aarch64-linux-gnu \
	-Dpipelines=simple \
	-Dipas=simple \
	-Dgstreamer=enabled \
	-Dcam=enabled \
	-Dcam-output-kms=disabled \
	-Dcam-output-sdl2=disabled \
	-Dqcam=disabled \
	-Ddocumentation=disabled \
	-Dtest=false \
	-Dlc-compliance=disabled \
	-Dpycamera=disabled \
	-Dv4l2=false \
	-Dtracing=disabled \
	-Dsoftisp-gpu=disabled
meson compile -C build
DESTDIR=/build/stage-libcamera meson install --no-rebuild -C build
install -Dm644 /build/camera-inputs/tuning/hi1337-gts9u.yaml \
	/build/stage-libcamera/usr/share/libcamera/ipa/simple/hi1337-gts9u.yaml
install -Dm644 /build/camera-inputs/tuning/hi847.yaml \
	/build/stage-libcamera/usr/share/libcamera/ipa/simple/hi847.yaml
echo 'libcamera built'"
else
	test -f "$buildroot/build/stage-libcamera/usr/lib/aarch64-linux-gnu/libcamera.so"
fi

mkdir -p "$buildroot/build/stage-libcamera-DEBIAN"
cat > "$buildroot/build/stage-libcamera-DEBIAN/postinst" <<'POSTINST'
#!/bin/sh
set -e
ldconfig
exit 0
POSTINST
cat > "$buildroot/build/stage-libcamera-DEBIAN/postrm" <<'POSTRM'
#!/bin/sh
set -e
ldconfig
exit 0
POSTRM

package_tree /build/stage-libcamera libcamera-gts9u "$libcamera_version" \
	'libc6, libstdc++6, libgnutls30t64, libudev1, libyaml-0-2, libgstreamer1.0-0, libgstreamer-plugins-base1.0-0' \
	'libcamera simple pipeline and software ISP for the Galaxy Tab S9 Ultra' \
	"$buildroot/build/stage-libcamera-DEBIAN"

# The PipeWire plugin links against this exact libcamera ABI.  Installing into
# the disposable build chroot affects no shipped rootfs; the staged files above
# are what enter the package.
run 'cp -a /build/stage-libcamera/. / && ldconfig'

step "PipeWire libcamera SPA $pipewire_version"
if [ "$skip_pipewire_build" != 1 ]; then
	run "cd /build
rm -rf pipewire-camera stage-pipewire-camera
git clone --quiet https://gitlab.freedesktop.org/pipewire/pipewire.git pipewire-camera
cd pipewire-camera
git checkout --quiet $pipewire_commit
git apply \
	/build/camera-inputs/pipewire/0001-libcamera-0.7-string-view-model.patch \
	/build/camera-inputs/pipewire/0002-libcamera-0.7-skip-array-controls.patch \
	/build/camera-inputs/pipewire/0003-libcamera-correct-packed-rgb-mapping.patch \
	/build/camera-inputs/pipewire/0004-libcamera-reuse-request-buffers.patch \
	/build/camera-inputs/pipewire/0005-libcamera-do-not-close-borrowed-buffer-fds.patch \
	/build/camera-inputs/pipewire/0006-libcamera-process-completions-on-data-loop.patch \
	/build/camera-inputs/pipewire/0007-libcamera-suppress-redundant-video-transform.patch
meson setup build \
	--prefix=/usr \
	--libdir=lib/aarch64-linux-gnu \
	-Dauto_features=disabled \
	-Dspa-plugins=enabled \
	-Ddbus=disabled \
	-Dudev=enabled \
	-Dlibcamera=enabled \
	-Dsession-managers=[]
meson compile -C build spa-libcamera
install -Dm755 build/spa/plugins/libcamera/libspa-libcamera.so \
	/build/stage-pipewire-camera/usr/lib/aarch64-linux-gnu/spa-0.2/libcamera/libspa-libcamera.so
echo 'PipeWire camera SPA built'"
else
	install -Dm755 \
		"$buildroot/build/pipewire-camera/build/spa/plugins/libcamera/libspa-libcamera.so" \
		"$buildroot/build/stage-pipewire-camera/usr/lib/aarch64-linux-gnu/spa-0.2/libcamera/libspa-libcamera.so"
fi

package_tree /build/stage-pipewire-camera libspa-0.2-libcamera-gts9u \
	"$pipewire_version" \
	"libc6, libstdc++6, pipewire (>= 1.0.5), pipewire (<< 1.1), wireplumber, libcamera-gts9u (= $libcamera_version)" \
	'PipeWire 1.0 libcamera SPA adapted for libcamera 0.7'

step 'results'
ls -l \
	"$out/libcamera-gts9u_${libcamera_version}_arm64.deb" \
	"$out/libspa-0.2-libcamera-gts9u_${pipewire_version}_arm64.deb"
sha256sum \
	"$out/libcamera-gts9u_${libcamera_version}_arm64.deb" \
	"$out/libspa-0.2-libcamera-gts9u_${pipewire_version}_arm64.deb"
