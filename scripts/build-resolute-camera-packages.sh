#!/bin/bash
# Build the SM-X910 camera pair against the exact Resolute arm64 libraries.
set -euo pipefail
export SOURCE_DATE_EPOCH=0

repo=$(cd "$(dirname "$0")/.." && pwd)
base=${UBUNTU_WORKDIR:-/root/ubuntu-gts9u-2604}
buildroot=${BUILDROOT_DIR:-$base/resolute-probe}
out=${DEB_OUT_DIR:-$base/out/camera-resolute}
camver=0.7.2+53.g62d4bfc-gts9u10
spaver=1.6.2-1ubuntu1.2+gts9u1
cam_stage=$buildroot/build/stage-libcamera
spa_stage=$buildroot/build/stage-pipewire-camera

test "$buildroot" != / && test "$base" != /
grep -qx 'VERSION_ID="26.04"' "$buildroot/etc/os-release" || {
    echo 'Resolute arm64 buildroot required' >&2; exit 2;
}
test "$(chroot "$buildroot" dpkg --print-architecture)" = arm64
mkdir -p "$out" "$buildroot/build" "$base/cache"

if [ "${REUSE_LIBCAMERA_STAGE:-0}" != 1 ]; then
    chroot "$buildroot" /bin/bash -ec '
        export DEBIAN_FRONTEND=noninteractive
        apt-get install -y --no-install-recommends build-essential meson ninja-build \
            pkg-config git python3-jinja2 python3-yaml python3-ply \
            libgnutls28-dev libudev-dev libyaml-dev libdrm-dev libjpeg-dev \
            libtiff-dev libevent-dev libegl-dev libgles-dev libboost-dev libdw-dev
    '
    cam_src=$buildroot/build/libcamera-gts9u-resolute
    rm -rf -- "$cam_src" "$cam_stage"
    git clone --quiet --filter=blob:none \
        https://git.libcamera.org/libcamera/libcamera.git "$cam_src"
    git -C "$cam_src" checkout --quiet --detach \
        62d4bfc450798cbd57722fa349a245b93b11d1cd
    # Later patches depend on earlier ones; apply each to the updated tree.
    for patch in "$repo"/packaging/libcamera/patches/000[1-7]-*.patch; do
        git -C "$cam_src" apply "$patch"
    done
    chroot "$buildroot" meson setup /build/libcamera-gts9u-resolute/build \
        /build/libcamera-gts9u-resolute --buildtype=release --prefix=/usr \
        --libdir=lib/aarch64-linux-gnu -Dpipelines=simple -Dipas=simple \
        -Dgstreamer=disabled -Dcam=enabled -Dcam-output-kms=disabled \
        -Dcam-output-sdl2=disabled -Dqcam=disabled -Ddocumentation=disabled \
        -Dtest=false -Dlc-compliance=disabled -Dpycamera=disabled \
        -Dv4l2=disabled -Dtracing=disabled -Dsoftisp-gpu=enabled
    chroot "$buildroot" ninja -C /build/libcamera-gts9u-resolute/build -j "${BUILD_JOBS:-4}"
    chroot "$buildroot" env DESTDIR=/build/stage-libcamera meson install \
        --no-rebuild -C /build/libcamera-gts9u-resolute/build
    install -Dm644 "$repo/packaging/libcamera/tuning/hi1337-gts9u.yaml" \
        "$cam_stage/usr/share/libcamera/ipa/simple/hi1337-gts9u.yaml"
    install -Dm644 "$repo/packaging/libcamera/tuning/hi847.yaml" \
        "$cam_stage/usr/share/libcamera/ipa/simple/hi847.yaml"
fi
test -f "$cam_stage/usr/lib/aarch64-linux-gnu/libcamera.so.0.7.2"
test -f "$cam_stage/usr/lib/aarch64-linux-gnu/libcamera/ipa/ipa_soft_simple.so.sign"

# Only the disposable buildroot receives headers and libraries for SPA linking.
cp -a "$cam_stage/." "$buildroot/"
chroot "$buildroot" ldconfig

if [ "${REUSE_PIPEWIRE_BUILD:-0}" != 1 ]; then
    chroot "$buildroot" /bin/bash -ec '
        export DEBIAN_FRONTEND=noninteractive
        apt-get install -y --no-install-recommends libpipewire-0.3-dev \
            libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev
    '
    cache=$base/cache/pipewire-resolute
    mkdir -p "$cache"
    url=https://ports.ubuntu.com/ubuntu-ports/pool/main/p/pipewire
    fetch() {
        local name=$1 digest=$2
        if ! printf '%s  %s\n' "$digest" "$cache/$name" | sha256sum -c --status; then
            curl --fail --location --silent --show-error "$url/$name" -o "$cache/$name"
        fi
        printf '%s  %s\n' "$digest" "$cache/$name" | sha256sum -c
    }
    fetch pipewire_1.6.2.orig.tar.gz \
        13eaaf67558ddccf3d61ab7826f202d53538de422b015dd841ec92e1b7f5c0d8
    fetch pipewire_1.6.2-1ubuntu1.2.debian.tar.xz \
        686045295dbc667683300a970f7bf5caa75b31e2d18a1572fa71f5fe3f902b07
    fetch pipewire_1.6.2-1ubuntu1.2.dsc \
        f6b65fb2d4a332f53f8eab9803a4156c9c352452510aff54ed538093b69aa9e0
    spa_src=$buildroot/build/pipewire-camera-resolute
    rm -rf -- "$spa_src" "$spa_stage"
    dpkg-source -x "$cache/pipewire_1.6.2-1ubuntu1.2.dsc" "$spa_src"
    patch -d "$spa_src" -p1 --fuzz=0 < \
        "$repo/packaging/pipewire/patches/resolute-0001-libcamera-suppress-redundant-video-transform.patch"
    chroot "$buildroot" meson setup /build/pipewire-camera-resolute/build \
        /build/pipewire-camera-resolute --prefix=/usr \
        --libdir=lib/aarch64-linux-gnu -Dauto_features=disabled \
        -Dspa-plugins=enabled -Ddbus=disabled -Dudev=enabled \
        -Dlibcamera=enabled -Dsession-managers=
    chroot "$buildroot" ninja -C /build/pipewire-camera-resolute/build \
        -j "${BUILD_JOBS:-4}" spa/plugins/libcamera/libspa-libcamera.so
    install -Dm755 \
        "$spa_src/build/spa/plugins/libcamera/libspa-libcamera.so" \
        "$spa_stage/usr/lib/aarch64-linux-gnu/spa-0.2/libcamera/libspa-libcamera.so"
fi
test -f "$spa_stage/usr/lib/aarch64-linux-gnu/spa-0.2/libcamera/libspa-libcamera.so"

pack() {
    local stage=$1 name=$2 version=$3 control=$4
    local dest=$out/${name}_${version}_arm64.deb
    local temp
    temp=$(mktemp -d "$base/build/camera-package.XXXXXX")
    cp -a "$stage/." "$temp/"
    mkdir -p "$temp/DEBIAN"
    printf '%s\n' "$control" > "$temp/DEBIAN/control"
    find "$temp" -exec touch -h -d '@0' {} +
    dpkg-deb --root-owner-group --build "$temp" "$dest"
    rm -rf -- "$temp"
    dpkg-deb -f "$dest" Package Version Depends
    sha256sum "$dest"
}
mkdir -p "$base/build"
pack "$cam_stage" libcamera0.7 "$camver" "Package: libcamera0.7
Version: $camver
Architecture: arm64
Multi-Arch: same
Section: libs
Priority: optional
Maintainer: Ubuntu gts9uwifi port contributors <noreply@example.invalid>
Depends: libc6, libstdc++6, libgcc-s1, libgnutls30t64, libudev1, libyaml-0-2, libegl1, libgles2, libtiff6, libevent-2.1-7t64, libevent-pthreads-2.1-7t64, libdw1t64
Provides: libcamera-gts9u (= $camver), libcamera-ipa (= $camver), libcamera-tools (= $camver), gstreamer1.0-libcamera (= $camver)
Conflicts: libcamera-ipa, libcamera-tools, libcamera-dev, gstreamer1.0-libcamera
Replaces: libcamera-ipa, libcamera-tools, libcamera-dev, gstreamer1.0-libcamera
Description: SM-X910 libcamera 0.7.2 with simple software ISP and GPU backend"
pack "$spa_stage" libspa-0.2-libcamera-gts9u "$spaver" "Package: libspa-0.2-libcamera-gts9u
Version: $spaver
Architecture: arm64
Section: libs
Priority: optional
Maintainer: Ubuntu gts9uwifi port contributors <noreply@example.invalid>
Depends: libc6, libstdc++6, pipewire (>= 1.6.2), pipewire (<< 1.7), libspa-0.2-modules, wireplumber, libcamera0.7 (= $camver)
Description: SM-X910 PipeWire 1.6.2 libcamera SPA with native video orientation"
