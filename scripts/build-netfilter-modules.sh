#!/bin/bash
# Build and sign the configured IPv4/IPv6/Netfilter modules as one export set.
set -euo pipefail
test "$#" -eq 3 || { echo "Usage: $0 KERNEL_SOURCE KERNEL_BUILD MODULE_DESTINATION" >&2; exit 2; }
source_tree=$(realpath "$1")
object_tree=$(realpath "$2")
destination=$3
test -s "$object_tree/Module.symvers"
test -s "$object_tree/certs/signing_key.pem"
stage=$(mktemp -d "$object_tree/netfilter-build.XXXXXX")
trap 'rm -rf -- "$stage"' EXIT
# A single modpost resolves the mutual dependencies between conntrack, NAT,
# IPv4/IPv6 defragmentation and the xtables/nftables modules.
ln -s "$source_tree/net/netfilter" "$stage/nf"
ln -s "$source_tree/net/ipv4/netfilter" "$stage/v4"
ln -s "$source_tree/net/ipv6/netfilter" "$stage/v6"
printf 'obj-m += nf/ v4/ v6/\n' > "$stage/Makefile"
make -C "$source_tree" O="$object_tree" ARCH=arm64 LLVM=1 \
	M="$stage" -j"${JOBS:-$(nproc)}" modules
mkdir -p "$destination"
# modules.order is authoritative: never ship stale .ko files from an earlier
# configuration just because they are still present in the source directory.
while IFS= read -r module; do
	# Recent kbuild versions list .o paths rather than .ko in modules.order.
	case "$module" in *.o) module=${module%.o}.ko ;; esac
	case "$module" in /*) ;; *) module=$stage/$module ;; esac
	target=$destination/$(basename "$module")
	install -m 0644 "$module" "$target"
	llvm-strip --strip-debug "$target"
	"$object_tree/scripts/sign-file" sha512 \
		"$object_tree/certs/signing_key.pem" \
		"$object_tree/certs/signing_key.x509" "$target"
	# Old host kmod cannot decode every current arm64 module; sign-file's
	# successful exit plus the trailer works across build host versions.
	tail -c 28 "$target" | grep -qx '~Module signature appended~'
done < "$stage/modules.order"
