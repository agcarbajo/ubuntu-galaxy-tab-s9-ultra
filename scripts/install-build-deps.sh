#!/bin/bash
# Install the host tools the Ubuntu image pipeline needs, inside the WSL
# Ubuntu-24.04 build environment.  Touches only the build host.
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y --no-install-recommends \
	mmdebstrap \
	debootstrap \
	qemu-user-static \
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
