#!/bin/bash
# Build the EROFS module against the exact object tree and signing key of an
# already-installed kernel.  Android's system and vendor images inside `super`
# are EROFS; the fingerprint provisioning helper mounts them read-only.
# CONFIG_EROFS_FS=m is not useful unless the signed module is in the image,
# exactly as for TUN.  The caller must verify the live config and key.
set -euo pipefail
if [ "$#" -ne 3 ]; then
	echo "usage: $0 KERNEL_SOURCE KERNEL_BUILD OUTPUT_DIR" >&2
	exit 2
fi
source_tree=$(realpath "$1")
object_tree=$(realpath "$2")
output_dir=$(realpath -m "$3")
grep -qx 'CONFIG_EROFS_FS=m' "$object_tree/.config"
# Every decompressor EROFS can select is built in on this kernel, so the
# module has no dependencies of its own.
grep -qx 'CONFIG_LZ4_DECOMPRESS=y' "$object_tree/.config"
test -s "$object_tree/Module.symvers"
test -s "$object_tree/certs/signing_key.pem"
test -f "$source_tree/fs/erofs/super.c"
# The build tree keeps the certificate inside signing_key.pem; sign-file also
# accepts a separate DER copy, which older trees carry as signing_key.x509.
cert=$object_tree/certs/signing_key.x509
cert_tmp=
if [ ! -s "$cert" ]; then
	cert_tmp=$(mktemp)
	cert=$cert_tmp
	openssl x509 -in "$object_tree/certs/signing_key.pem" -outform DER -out "$cert"
fi

if [ -x /usr/lib/llvm-22/bin/clang ]; then
	export PATH=/usr/lib/llvm-22/bin:$PATH
fi
# Build out of tree from a staging copy: an in-tree M=fs/erofs build leaves
# its objects inside the pristine source tree.  The in-tree Makefile already
# selects the objects from the tree's CONFIG_EROFS_FS_* symbols.
stage=$(mktemp -d)
trap 'rm -rf -- "$stage" ${cert_tmp:-}' EXIT
ln -s "$source_tree"/fs/erofs/* "$stage/"
make -C "$source_tree" O="$object_tree" ARCH=arm64 LLVM=1 M="$stage" modules
module=$stage/erofs.ko
test -f "$module"
"$object_tree/scripts/sign-file" sha512 \
	"$object_tree/certs/signing_key.pem" "$cert" "$module"
modinfo -F signer "$module" | grep -q .
test "$(modinfo -F vermagic "$module" | cut -d' ' -f1)" = \
	"$(make -s -C "$source_tree" O="$object_tree" ARCH=arm64 LLVM=1 kernelrelease)"
test -z "$(modinfo -F depends "$module")"
install -d "$output_dir"
install -m 0644 "$module" "$output_dir/erofs.ko"
sha256sum "$output_dir/erofs.ko"
