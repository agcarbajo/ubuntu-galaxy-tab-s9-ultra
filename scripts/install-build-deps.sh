#!/bin/bash
# Install the host tools the Ubuntu image pipeline needs, inside the WSL
# Ubuntu-24.04 build environment.  Touches only the build host.
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

apt-get update
qemu_user_package=$(bash "$(dirname "$0")/select-qemu-user-package.sh")
apt-get install -y --no-install-recommends \
	mmdebstrap \
	debootstrap \
	"$qemu_user_package" \
	binfmt-support \
	arch-test \
	apt-utils \
	dpkg-dev \
	gettext \
	libglib2.0-bin \
	libglib2.0-dev-bin \
	desktop-file-utils \
	appstream \
	gdisk \
	parted \
	kpartx \
	e2fsprogs \
	dosfstools \
	lz4 \
	zstd \
	xz-utils \
	cpio \
	device-tree-compiler \
	python3 \
	python3-pycryptodome \
	zip \
	unzip \
	ca-certificates

bash "$(dirname "$0")/check-build-deps.sh"
