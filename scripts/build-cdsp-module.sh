#!/bin/bash
# Build and sign against the existing kernel; never rebuild or flash boot images.
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
base=${UBUNTU_WORKDIR:-/root/ubuntu-gts9u}
kernel_tree=${KERNEL_WORKTREE:-$base/build/linux-src-gts9uwifi}
build_dir=${KERNEL_BUILD_DIR:-$base/build/linux-gts9uwifi}
module_dir=$base/build/cdsp-module
out_dir=${CDSP_OUT_DIR:-$base/out/cdsp-module}
test -f "$build_dir/Module.symvers"
test -f "$build_dir/certs/signing_key.pem"
test -f "$build_dir/certs/signing_key.x509"
grep -qx 'CONFIG_DMABUF_HEAPS_SYSTEM=m' "$build_dir/.config" || {
    echo 'Expected CONFIG_DMABUF_HEAPS_SYSTEM=m in the matching kernel' >&2
    exit 1
}
if [ -x /usr/lib/llvm-22/bin/clang ]; then
    export PATH=/usr/lib/llvm-22/bin:$PATH
fi
mkdir -p "$module_dir" "$out_dir"
install -m0644 "$repo/kernel/drivers/gts9u_cdsp.c" "$module_dir/"
install -m0644 "$repo/kernel/drivers/gts9u_dsp_stats.c" "$module_dir/"
install -m0644 "$repo/kernel/modules/cdsp/Makefile" "$module_dir/"
install -m0644 "$kernel_tree/drivers/dma-buf/heaps/system_heap.c" "$module_dir/"
make -C "$kernel_tree" O="$build_dir" ARCH=arm64 LLVM=1 M="$module_dir" modules
for module in gts9u_cdsp gts9u_dsp_stats system_heap; do
    install -m0644 "$module_dir/$module.ko" "$out_dir/"
    "$build_dir/scripts/sign-file" sha256 "$build_dir/certs/signing_key.pem" \
        "$build_dir/certs/signing_key.x509" "$out_dir/$module.ko"
    modinfo -F vermagic "$out_dir/$module.ko"
    modinfo -F signer "$out_dir/$module.ko"
    modinfo -F sig_key "$out_dir/$module.ko"
    sha256sum "$out_dir/$module.ko"
done
