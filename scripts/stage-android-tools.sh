#!/bin/bash
# Stage the Android boot-image tooling this port needs.
#
# mkbootimg, mkdtboimg and avbtool are AOSP tools (Apache-2.0) that Ubuntu does
# not package.  They are not vendored in Git; this script copies them into the
# build base, from the postmarketOS build chroot when it is available, and
# records their SHA-256 so a build can prove which tooling produced an image.
set -euo pipefail

base=${UBUNTU_WORKDIR:-/root/ubuntu-gts9u}
tools=$base/tools
pmos_chroot=${PMOS_ROOTFS_CHROOT:-/root/pmos-gts9u/pmbootstrap-work/chroot_rootfs_samsung-gts9uwifi}

mkdir -p "$tools"

take() {
	# take <source> <name>
	if [ -f "$1" ]; then
		install -m 0755 "$1" "$tools/$2"
		return 0
	fi
	return 1
}

ok=1
take "$pmos_chroot/usr/share/android-tools/mkbootimg/mkbootimg.py" mkbootimg.py || ok=0
take "$pmos_chroot/usr/bin/mkdtboimg" mkdtboimg.py || ok=0
take "$pmos_chroot/usr/bin/avbtool" avbtool.py || ok=0

if [ "$ok" != 1 ]; then
	cat >&2 <<'EOF'
Could not stage the Android tooling.

Provide the three tools manually in $UBUNTU_WORKDIR/tools:

  mkbootimg.py   https://android.googlesource.com/platform/system/tools/mkbootimg
  mkdtboimg.py   same repository, mkdtboimg.py
  avbtool.py     https://android.googlesource.com/platform/external/avb

or point PMOS_ROOTFS_CHROOT at a postmarketOS rootfs chroot that has them.
EOF
	exit 1
fi

( cd "$tools" && sha256sum mkbootimg.py mkdtboimg.py avbtool.py > SHA256SUMS )
cat "$tools/SHA256SUMS"
