#!/bin/bash
# Package the signed EL721 TrustZone app extracted from this tablet owner's
# matching One UI firmware.  Proprietary bytes never enter the repository.
set -euo pipefail

repo=$(cd "$(dirname "$0")/.." && pwd)
base=${UBUNTU_WORKDIR:-/root/ubuntu-gts9u}
out=${DEB_OUT_DIR:-$base/out/packages}
source_dir=${1:-${GTS9U_FINGERPRINT_FIRMWARE_DIR:-}}
version=${GTS9U_FINGERPRINT_FIRMWARE_VERSION:-1.0}

[ -n "$source_dir" ] || {
	echo "usage: $0 DIRECTORY-CONTAINING-dualfp.b00...b08" >&2
	exit 2
}
if [ -d "$source_dir/ta" ]; then
	source_dir=$source_dir/ta
fi
test -d "$source_dir"

expected='6a6cbf508f93e705581457f6d6ba2048d96d3c11b9e3e06223611d4ff04e397b dualfp.b00
dde4dcc44d91830bad1a045a31762ac26ce575736b78d65dd2aae1bbd26c6128 dualfp.b01
7d69b0f9e9e492d7c8eaec9657a76611e24515b5135a07f6861d7267a4b0b671 dualfp.b02
6694555ab48fea7b2644d120ae50854dda22aced96a74c169747f66473aef404 dualfp.b03
2b33a15937dce56e7b6f825894d6cba963a85c5744c0c00a79442c25150530b1 dualfp.b04
509f7f5868b132657cec8ad53a02ed85fe03269bd4a4c9d8e0950e9cd66685b2 dualfp.b05
034cd485b7a16fabfbc87f00b4dfd63ceb5920bf7b5052d9644aacb652101192 dualfp.b06
6694555ab48fea7b2644d120ae50854dda22aced96a74c169747f66473aef404 dualfp.b07
67a2d8095b70e1c02918ecac0161efeb8a6b2531d90e708d7127561c6056637d dualfp.b08'

expected_runtime='471221d8a6743f580d94e45510d44143e9b0e2069d3783dff486306718fb449b calib.dat
c5beb1351a5d603b578fe79a80aa2a7c1f68aa0322445048690077e39b1292a4 egoptbds.dat'

while read -r hash name; do
	file=$source_dir/$name
	test -f "$file" || { echo "missing $file" >&2; exit 1; }
	actual=$(sha256sum "$file" | awk '{print $1}')
	[ "$actual" = "$hash" ] || {
		echo "$name does not match the validated One UI 8 firmware" >&2
		exit 1
	}
done <<EOF
$expected
EOF

while read -r hash name; do
	file=$source_dir/$name
	test -f "$file" || { echo "missing $file" >&2; exit 1; }
	actual=$(sha256sum "$file" | awk '{print $1}')
	[ "$actual" = "$hash" ] || {
		echo "$name does not match the validated SM-X910 calibration data" >&2
		exit 1
	}
done <<EOF
$expected_runtime
EOF

staging=$base/build/deb/ubuntu-gts9u-fingerprint-firmware
rm -rf -- "$staging"
mkdir -p "$staging/DEBIAN" \
	"$staging/usr/lib/firmware/gts9u/fingerprint" \
	"$staging/usr/share/doc/ubuntu-gts9u-fingerprint-firmware"
while read -r _ name; do
	install -m0644 "$source_dir/$name" \
		"$staging/usr/lib/firmware/gts9u/fingerprint/$name"
done <<EOF
$expected
EOF
while read -r _ name; do
	install -m0600 "$source_dir/$name" \
		"$staging/usr/lib/firmware/gts9u/fingerprint/$name"
done <<EOF
$expected_runtime
EOF
if [ -f "$source_dir/cell_id" ]; then
	cell_id=$(tr -d '\r\n' < "$source_dir/cell_id")
	case "$cell_id" in
		??????????????????????) ;;
		*) echo 'cell_id must contain exactly 22 hexadecimal characters' >&2; exit 1 ;;
	esac
	case "$cell_id" in
		*[!0123456789abcdefABCDEF]*)
			echo 'cell_id must contain exactly 22 hexadecimal characters' >&2
			exit 1
			;;
	esac
	printf '%s\n' "$(printf '%s' "$cell_id" | tr '[:upper:]' '[:lower:]')" > \
		"$staging/usr/lib/firmware/gts9u/fingerprint/cell_id"
fi
cat > "$staging/DEBIAN/control" <<EOF
Package: ubuntu-gts9u-fingerprint-firmware
Version: $version
Section: non-free-firmware
Priority: optional
Architecture: all
Maintainer: Local builder <noreply@example.invalid>
Description: locally imported Samsung EL721 secure app for the SM-X910
 User-supplied, hash-validated signed dualfp image required by the EL721.
EOF
cat > "$staging/usr/share/doc/ubuntu-gts9u-fingerprint-firmware/copyright" <<'EOF'
The files dualfp.b00 through dualfp.b08 and the device-specific EL721
calibration data are proprietary Samsung/Qualcomm firmware and configuration.
This package was built locally from files supplied by the device owner.
Redistribution is not granted by this project.
EOF
chown -R root:root "$staging"
find "$staging" -type d -exec chmod 0755 {} +
find "$staging" -type f -exec chmod 0644 {} +
find "$staging" -exec touch -h -d '@0' {} +
mkdir -p "$out"
deb=$out/ubuntu-gts9u-fingerprint-firmware_${version}_all.deb
dpkg-deb --root-owner-group --build "$staging" "$deb" >/dev/null
echo "built $deb"
sha256sum "$deb"
