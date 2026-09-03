#!/bin/bash
# Pair Ubuntu's UNCHANGED PAM module with our additive fprintd daemon.
# Only package Version, Maintainer and the exact fprintd dependency change.
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
base=${UBUNTU_WORKDIR:-/root/ubuntu-gts9u}
out=${DEB_OUT_DIR:-$base/out/packages}
cache=$base/cache/fprintd-matched
version=$(cat "$repo/packaging/fprintd/version")
daemon=${1:-$out/fprintd_${version}_arm64.deb}
test "$(dpkg-deb -f "$daemon" Package)" = fprintd
test "$(dpkg-deb -f "$daemon" Architecture)" = arm64
test "$(dpkg-deb -f "$daemon" Version)" = "$version"
mkdir -p "$cache" "$out" "$base/build"
original=$cache/libpam-fprintd_1.94.3-1_arm64.deb
checksum=67ea92e4c4f4befd3df19696bae9fbf5126710216f049d38948dbba8564bb223
if ! printf '%s  %s\n' "$checksum" "$original" | sha256sum --check --status; then
    curl --fail --location --silent --show-error \
        https://ports.ubuntu.com/ubuntu-ports/pool/main/f/fprintd/libpam-fprintd_1.94.3-1_arm64.deb \
        -o "$original"
fi
printf '%s  %s\n' "$checksum" "$original" | sha256sum --check
task=$(mktemp -d "$base/build/fprintd-pam.XXXXXX")
stage=$task/package
dpkg-deb --raw-extract "$original" "$stage"
# Never remove the dependency, use --force-depends or weaken authentication.
grep -Fq 'fprintd (= 1.94.3-1)' "$stage/DEBIAN/control"
sed -i "s/^Version: .*/Version: $version/; s/fprintd (= 1.94.3-1)/fprintd (= $version)/" "$stage/DEBIAN/control"
sed -i 's/^Maintainer: .*/Maintainer: Ubuntu gts9uwifi port contributors <noreply@example.invalid>/' "$stage/DEBIAN/control"
find "$stage" -exec touch -h -d '@0' {} +
deb=$out/libpam-fprintd_${version}_arm64.deb
dpkg-deb --root-owner-group --build "$stage" "$deb"
bash "$repo/scripts/check-fprintd-package-pair.sh" "$daemon" "$deb"
python3 "$repo/scripts/test-fprintd-packages.py" "$daemon" "$deb" "$original"
sha256sum "$deb"
