#!/bin/bash
# Build a staged GPU candidate without changing installed cameras or old builds.
# Run as root on the validated PC/arm64 build chroot; never installs the result.
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
buildroot=${BUILDROOT_DIR:-/root/ubuntu-gts9u/buildroot}
source_tree=$buildroot/build/libcamera-gts9u
commit=62d4bfc450798cbd57722fa349a245b93b11d1cd
[[ $EUID == 0 ]] || { echo 'Run on the build PC as root.' >&2; exit 1; }
test -d "$buildroot/usr/bin"
git -C "$source_tree" cat-file -e "$commit^{commit}"
# Do not copy dirty work, reset it, reconfigure its output, or install packages.
chroot "$buildroot" pkg-config --exists egl glesv2
candidate=$(mktemp -d "$buildroot/build/camera-gpu-experiment.XXXXXXXX")
inside=${candidate#"$buildroot"}
echo "Candidate retained at $candidate"
mkdir "$candidate/source"
git -C "$source_tree" archive "$commit" | tar -x -C "$candidate/source"
for patch in "$repo"/packaging/libcamera/patches/*.patch; do
    # Match the production builder (git apply also supports short-context
    # hand-authored hunks without GNU patch's end-of-file heuristic).
    (cd "$candidate/source" && git apply --check "$patch" && git apply "$patch")
done
chroot "$buildroot" meson setup "$inside/output" "$inside/source" \
    --prefix=/usr --libdir=lib/aarch64-linux-gnu --buildtype=release \
    -Dpipelines=simple -Dipas=simple -Dgstreamer=disabled \
    -Dcam=enabled -Dcam-output-kms=disabled -Dcam-output-sdl2=disabled \
    -Dqcam=disabled -Ddocumentation=disabled -Dtest=false \
    -Dlc-compliance=disabled -Dpycamera=disabled -Dv4l2=false \
    -Dtracing=disabled -Dsoftisp-gpu=enabled
chroot "$buildroot" meson compile -C "$inside/output" -j 4
chroot "$buildroot" env DESTDIR="$inside/stage" \
    meson install --no-rebuild -C "$inside/output"
for tuning in hi1337-gts9u.yaml hi847.yaml; do
    install -Dm644 "$repo/packaging/libcamera/tuning/$tuning" \
        "$candidate/stage/usr/share/libcamera/ipa/simple/$tuning"
done
echo "Staged only: $candidate/stage"
echo 'NOT approved for deployment: validate GPU/CPU frames, autofocus, colours,'
echo 'field of view, four-camera handover, latency and power on the tablet first.'
