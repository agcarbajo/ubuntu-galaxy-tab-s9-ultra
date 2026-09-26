#!/bin/bash
# Pair Ubuntu's UNCHANGED PAM module with our additive fprintd daemon.
# Only package Version, Maintainer and the exact fprintd dependency change.
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
base=${UBUNTU_WORKDIR:-/root/ubuntu-gts9u}
out=${DEB_OUT_DIR:-$base/out/packages}
cache=$base/cache/fprintd-matched
suite=${UBUNTU_SUITE:-noble}
case "$suite" in
    noble)
        version=$(cat "$repo/packaging/fprintd/version")
        original_version=1.94.3-1
        checksum=67ea92e4c4f4befd3df19696bae9fbf5126710216f049d38948dbba8564bb223 ;;
    resolute)
        version=$(cat "$repo/packaging/fprintd/version-resolute")
        original_version=1.94.5-4
        checksum=8595c667b26ba7d8b49e9cfecc9ed4a0e4b2ce7ad95dd67718ae49b37912a3a4 ;;
    *) echo "unsupported fprintd suite: $suite" >&2; exit 2 ;;
esac
daemon=${1:-$out/fprintd_${version}_arm64.deb}
test "$(dpkg-deb -f "$daemon" Package)" = fprintd
test "$(dpkg-deb -f "$daemon" Architecture)" = arm64
test "$(dpkg-deb -f "$daemon" Version)" = "$version"
mkdir -p "$cache" "$out" "$base/build"
original=$cache/libpam-fprintd_${original_version}_arm64.deb
if ! printf '%s  %s\n' "$checksum" "$original" | sha256sum --check --status; then
    curl --fail --location --silent --show-error \
        "https://ports.ubuntu.com/ubuntu-ports/pool/main/f/fprintd/libpam-fprintd_${original_version}_arm64.deb" \
        -o "$original"
fi
printf '%s  %s\n' "$checksum" "$original" | sha256sum --check
task=$(mktemp -d "$base/build/fprintd-pam.XXXXXX")
stage=$task/package
dpkg-deb --raw-extract "$original" "$stage"
# Never remove the dependency, use --force-depends or weaken authentication.
grep -Fq "fprintd (= $original_version)" "$stage/DEBIAN/control"
sed -i "s/^Version: .*/Version: $version/; s/fprintd (= $original_version)/fprintd (= $version)/" "$stage/DEBIAN/control"
sed -i 's/^Maintainer: .*/Maintainer: Ubuntu gts9uwifi port contributors <noreply@example.invalid>/' "$stage/DEBIAN/control"
find "$stage" -exec touch -h -d '@0' {} +
deb=$out/libpam-fprintd_${version}_arm64.deb
dpkg-deb --root-owner-group --build "$stage" "$deb"
bash "$repo/scripts/check-fprintd-package-pair.sh" "$daemon" "$deb"
python3 "$repo/scripts/test-fprintd-packages.py" "$daemon" "$deb" "$original"
sha256sum "$deb"
