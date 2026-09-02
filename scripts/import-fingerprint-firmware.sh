#!/bin/bash
# Package the signed EL721 TrustZone app extracted from this tablet owner's
# matching One UI firmware.  Proprietary bytes never enter the repository.
set -euo pipefail

repo=$(cd "$(dirname "$0")/.." && pwd)
base=${UBUNTU_WORKDIR:-/root/ubuntu-gts9u}
out=${DEB_OUT_DIR:-$base/out/packages}
source_dir=${1:-${GTS9U_FINGERPRINT_FIRMWARE_DIR:-}}
version=${GTS9U_FINGERPRINT_FIRMWARE_VERSION:-1.1}

[ -n "$source_dir" ] || {
	echo "usage: $0 DIRECTORY-CONTAINING-EL721-signed-TA-segments" >&2
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

expected_gatekeeper='7c77cc69e68aed5fb71ebf3af5c39caed9c16a2a2f449c2f1c355804b9b8904c skeymast.b00
5a73f4985171b6f24e4e3c22fe0a5bf6383295c66e1661490b4397a98a84c110 skeymast.b01
0c240673c9e33f1792d66d62275d52ea459fb8d04a2469e8608991698f7c4338 skeymast.b02
7d8d4a597f0101a80c615018837e1fb7da39fcc6f92519927a227f45e254cdc6 skeymast.b03
0fd5e6a3b728d5f6484ab63e3999d5c2eb6cf0d5d3664bf8438a5ec3b206a595 skeymast.b04
f98489f6b1a4075f244696b945c9adb6255f5a24de8f0c83d8dc7aa1b00f4b7c skeymast.b05
b34d6a209d270c877f717d0fe384ce3a1735e516de81f06922645107b5d2914c skeymast.b06
7d8d4a597f0101a80c615018837e1fb7da39fcc6f92519927a227f45e254cdc6 skeymast.b07
aa0f67b43f42e5d97c6ba37d8bbcc982f62dad4c582a2cf405d57be399e65b1d skeymast.b08'

expected_hwvault='0cc3c57bd496bf33c111c2cf138e97d34cfb6eb0022fe6d8a9b3ac26c46d3f84 hwvault.b00
6a0245e22a3870c4bc59c44edb5e802a5ea0ade8250d59e777c7efb9877be16b hwvault.b01
28c37bca2079f8c9f95fdf5edc1e65abaf7a1dae7f4979c61373a6c9533a4370 hwvault.b02
c8d747db1cfb8d808185ed66e8cbdd40ff4732e1727a826d64a61bf99497dfda hwvault.b03
7a088585f7873b108911753206723523c1dd7252380227eb9d2793b5e7772805 hwvault.b04
c5019f3c23d476340f5caa32b94624cd4456fa4aac6ca6ea5f2ce594912e4fae hwvault.b05
54b048e66ab6d3e354aa55b410a31ed0f37af20974b44a87abdf152ea5a3c6e4 hwvault.b06
c8d747db1cfb8d808185ed66e8cbdd40ff4732e1727a826d64a61bf99497dfda hwvault.b07
470a39fbead41f7faa7ed3ca179340620773bda5b707112e623364079aae7620 hwvault.b08'

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
		echo "$name does not match the validated One UI 8 firmware" >&2
		exit 1
	}
done <<EOF
$expected_gatekeeper
EOF

while read -r hash name; do
	file=$source_dir/$name
	test -f "$file" || { echo "missing $file" >&2; exit 1; }
	actual=$(sha256sum "$file" | awk '{print $1}')
	[ "$actual" = "$hash" ] || {
		echo "$name does not match the validated One UI 8 firmware" >&2
		exit 1
	}
done <<EOF
$expected_hwvault
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
	install -m0644 "$source_dir/$name" \
		"$staging/usr/lib/firmware/gts9u/fingerprint/$name"
done <<EOF
$expected_gatekeeper
EOF
while read -r _ name; do
	install -m0644 "$source_dir/$name" \
		"$staging/usr/lib/firmware/gts9u/fingerprint/$name"
done <<EOF
$expected_hwvault
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
Description: locally imported Samsung secure apps for the SM-X910 EL721
 User-supplied, hash-validated signed dualfp, skeymast and HwVault images
 required by the EL721 and its authenticated template-encryption path.
EOF
cat > "$staging/usr/share/doc/ubuntu-gts9u-fingerprint-firmware/copyright" <<'EOF'
The files dualfp.b00 through dualfp.b08, skeymast.b00 through skeymast.b08,
hwvault.b00 through hwvault.b08 and the device-specific EL721 calibration data
are proprietary Samsung/Qualcomm firmware and configuration.
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
