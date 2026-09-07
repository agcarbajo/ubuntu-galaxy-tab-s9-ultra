#!/bin/bash
# Experimental SM-X910 session helpers. Does not install or flash anything.
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
base=${UBUNTU_WORKDIR:-/root/ubuntu-gts9u}
kernel_tree=${KERNEL_WORKTREE:-$base/build/linux-src-gts9uwifi}
build_dir=${KERNEL_BUILD_DIR:-$base/build/linux-gts9uwifi}
module_dir=$base/build/npu-session-module
out=${NPU_SESSION_OUT:-$base/out/npu-session}
: "${ANDROID_NDK:?Set ANDROID_NDK to the unpacked r26d directory}"
: "${QNN_HEADERS:?Set QNN_HEADERS to the compatible QAIRT 2.45 API headers}"
mkdir -p "$module_dir" "$out/bin" "$out/modules" "$module_dir/uapi/misc"
test -f "$kernel_tree/drivers/misc/fastrpc.c" || {
    echo "KERNEL_WORKTREE does not contain drivers/misc/fastrpc.c" >&2
    exit 1
}
test -f "$build_dir/Module.symvers" || {
    echo "KERNEL_BUILD_DIR is not a prepared build for KERNEL_WORKTREE" >&2
    exit 1
}
# Check compatibility before doing any compilation.  This patch intentionally
# targets the exact upstream FastRPC source used by the running kernel.
cp "$kernel_tree/drivers/misc/fastrpc.c" "$module_dir/gts9u_fastrpc_prepared.c"
patch --batch --fuzz=0 --dry-run -d "$module_dir" -p1 \
    < "$repo/kernel/patches/fastrpc-prepared-cdsp-module.patch" >/dev/null || {
    echo "KERNEL_WORKTREE does not match the FastRPC patch; use the exact source tree for this kernel" >&2
    exit 1
}
CDSP_OUT_DIR="$out/modules" bash "$repo/scripts/build-cdsp-module.sh"
cp "$kernel_tree/drivers/misc/fastrpc.c" "$module_dir/gts9u_fastrpc_prepared.c"
patch --batch --fuzz=0 -d "$module_dir" -p1 < "$repo/kernel/patches/fastrpc-prepared-cdsp-module.patch"
cp "$repo/kernel/drivers/gts9u_cdsp_intents_probe.c" "$module_dir/"
printf 'obj-m += gts9u_fastrpc_prepared.o gts9u_cdsp_intents_probe.o\n' > "$module_dir/Makefile"
export PATH=/usr/lib/llvm-22/bin:$PATH
make -C "$kernel_tree" O="$build_dir" ARCH=arm64 LLVM=1 M="$module_dir" modules
for name in gts9u_fastrpc_prepared gts9u_cdsp_intents_probe; do
    cp "$module_dir/$name.ko" "$out/modules/"
    "$build_dir/scripts/sign-file" sha256 "$build_dir/certs/signing_key.pem" \
        "$build_dir/certs/signing_key.x509" "$out/modules/$name.ko"
done
cc=$ANDROID_NDK/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android30-clang
"$cc" -O2 -Wall -Wextra -Werror -I "$QNN_HEADERS" \
    "$repo/scripts/npu-power-keeper.c" -ldl -o "$out/bin/npu-power-keeper"
cp "$kernel_tree/include/uapi/misc/fastrpc.h" "$module_dir/uapi/misc/"
aarch64-linux-gnu-gcc -O2 -Wall -Wextra -Werror -static -pthread \
    -I "$module_dir/uapi" "$repo/scripts/npu-bootstrap-traffic.c" \
    -o "$out/bin/npu-bootstrap-traffic"
install -m0755 "$repo/scripts/run-npu-session.py" "$out/bin/"
install -m0644 "$repo/configs/npu/gts9u-npu.service" "$out/"
install -m0755 "$repo/configs/npu/gts9u-npu-sleep" "$out/"
install -m0644 "$repo/configs/npu/70-gts9u-npu.rules" "$out/"
echo "Built experimental NPU session in $out"
