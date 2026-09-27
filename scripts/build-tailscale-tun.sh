#!/bin/bash
# Build the TUN module against the exact object tree and signing key of an
# already-installed kernel. The caller must verify the live config and key.
set -euo pipefail
if [ "$#" -ne 3 ]; then
	echo "usage: $0 KERNEL_SOURCE KERNEL_BUILD OUTPUT_DIR" >&2
	exit 2
fi
source_tree=$(realpath "$1")
object_tree=$(realpath "$2")
output_dir=$(realpath -m "$3")
grep -qx 'CONFIG_TUN=m' "$object_tree/.config"
test -s "$object_tree/Module.symvers"
test -s "$object_tree/certs/signing_key.pem"
test -s "$object_tree/certs/signing_key.x509"
test -f "$source_tree/drivers/net/tun.c"

if [ -x /usr/lib/llvm-22/bin/clang ]; then
	export PATH=/usr/lib/llvm-22/bin:$PATH
fi
stage=$(mktemp -d)
trap 'rm -rf -- "$stage"' EXIT
ln -s "$source_tree/drivers/net/tun.c" "$stage/tun.c"
ln -s "$source_tree/drivers/net/tun_vnet.h" "$stage/tun_vnet.h"
printf 'obj-m := tun.o\n' > "$stage/Makefile"
make -C "$source_tree" O="$object_tree" ARCH=arm64 LLVM=1 \
	M="$stage" modules
"$object_tree/scripts/sign-file" sha512 \
	"$object_tree/certs/signing_key.pem" \
	"$object_tree/certs/signing_key.x509" "$stage/tun.ko"
modinfo -F signer "$stage/tun.ko" | grep -q .
test "$(modinfo -F vermagic "$stage/tun.ko" | cut -d' ' -f1)" = \
	"$(make -s -C "$source_tree" O="$object_tree" ARCH=arm64 LLVM=1 kernelrelease)"
install -d "$output_dir"
install -m 0644 "$stage/tun.ko" "$output_dir/tun.ko"
sha256sum "$output_dir/tun.ko"
