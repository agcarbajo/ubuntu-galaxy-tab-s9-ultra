#!/bin/bash
# Build this port's two Bionic-side libraries for the SPU daemons in the
# pinned arm64 buildroot: liblog_capture.so (LD_PRELOAD log shim) and
# libvmmem.so (mem_buf-less sharing probe).  No hardware access and no
# proprietary input: both sources live in packaging/fingerprint-shim/.
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
base=${UBUNTU_WORKDIR:-/root/ubuntu-gts9u}
buildroot=${BUILDROOT_DIR:-$base/buildroot}
out=${FINGERPRINT_SHIM_OUT_DIR:-$base/out/fingerprint-shim}
stage=$buildroot/build/fingerprint-shim
mkdir -p "$out" "$stage"
install -m0644 "$repo/packaging/fingerprint-shim/android-log-capture.c" "$stage/"
install -m0644 "$repo/packaging/fingerprint-shim/vmmem-compat.c" "$stage/"
# -nostdlib: the daemons run under Bionic, so every import must stay an
# unversioned, unresolved symbol and the library must not NEED glibc.
# -fno-stack-protector/-fno-builtin: nothing else may be imported.
chroot "$buildroot" /bin/bash -euo pipefail -c '
  cd /build/fingerprint-shim
  for pair in android-log-capture.c:liblog_capture.so vmmem-compat.c:libvmmem.so; do
    cc -std=c11 -Wall -Wextra -Werror -O2 -fPIC -shared -nostdlib \
      -fno-stack-protector -fno-builtin -fno-asynchronous-unwind-tables \
      -Wl,-soname,"${pair#*:}" -Wl,--hash-style=both -Wl,-z,relro,-z,now \
      "${pair%%:*}" -o "${pair#*:}"
    strip --strip-unneeded "${pair#*:}"
  done'

check() {
	# $1 library, $2 expected exports, $3 expected imports (sorted, space-terminated)
	local lib=$stage/$1 defined undefined
	if readelf -d "$lib" | grep -q NEEDED; then
		echo "$1 must not depend on any shared library" >&2
		exit 1
	fi
	defined=$(readelf --dyn-syms -W "$lib" | awk '$7 != "UND" && $4 == "FUNC" {print $8}' | sort | tr '\n' ' ')
	undefined=$(readelf --dyn-syms -W "$lib" | awk '$7 == "UND" && $8 != "" {print $8}' | sort | tr '\n' ' ')
	test "$defined" = "$2" || { echo "$1: unexpected exports: $defined" >&2; exit 1; }
	test "$undefined" = "$3" || { echo "$1: unexpected imports: $undefined" >&2; exit 1; }
	test "$(readelf -h "$lib" | awk '/Machine:/ {print $2}')" = AArch64
	install -m0644 "$lib" "$out/$1"
	sha256sum "$out/$1"
}
# What the validated hand-built binaries looked like.
check liblog_capture.so '__android_log_buf_print __android_log_print ' 'vsnprintf write '
check libvmmem.so 'CreateVmMem FindVmByName FreeVmMem ShareDmabuf ' 'write '
