#!/bin/bash
# Build liblog_capture.so, the LD_PRELOAD shim for the SPU daemons, in the
# pinned arm64 buildroot.  No hardware access and no proprietary input: the
# shim is this port's own source, see packaging/fingerprint-shim/.
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
base=${UBUNTU_WORKDIR:-/root/ubuntu-gts9u}
buildroot=${BUILDROOT_DIR:-$base/buildroot}
out=${FINGERPRINT_SHIM_OUT_DIR:-$base/out/fingerprint-shim}
stage=$buildroot/build/fingerprint-shim
mkdir -p "$out" "$stage"
install -m0644 "$repo/packaging/fingerprint-shim/android-log-capture.c" "$stage/"
# -nostdlib: the daemons run under Bionic, so vsnprintf and write must stay
# unversioned, unresolved imports and the library must not NEED glibc.
# -fno-stack-protector/-fno-builtin: nothing else may be imported.
chroot "$buildroot" /bin/bash -euo pipefail -c '
  cd /build/fingerprint-shim
  cc -std=c11 -Wall -Wextra -Werror -O2 -fPIC -shared -nostdlib \
    -fno-stack-protector -fno-builtin -fno-asynchronous-unwind-tables \
    -Wl,-soname,liblog_capture.so -Wl,--hash-style=both -Wl,-z,relro,-z,now \
    android-log-capture.c -o liblog_capture.so
  strip --strip-unneeded liblog_capture.so'
shim=$stage/liblog_capture.so
# What the validated hand-built binary looked like: two exports, two imports,
# no NEEDED entry at all.
if readelf -d "$shim" | grep -q NEEDED; then
	echo 'liblog_capture.so must not depend on any shared library' >&2
	exit 1
fi
defined=$(readelf --dyn-syms -W "$shim" | awk '$7 != "UND" && $4 == "FUNC" {print $8}' | sort | tr '\n' ' ')
undefined=$(readelf --dyn-syms -W "$shim" | awk '$7 == "UND" && $8 != "" {print $8}' | sort | tr '\n' ' ')
test "$defined" = '__android_log_buf_print __android_log_print ' || {
	echo "unexpected exports: $defined" >&2; exit 1; }
test "$undefined" = 'vsnprintf write ' || {
	echo "unexpected imports: $undefined" >&2; exit 1; }
test "$(readelf -h "$shim" | awk '/Machine:/ {print $2}')" = AArch64
install -m0644 "$shim" "$out/liblog_capture.so"
sha256sum "$out/liblog_capture.so"
