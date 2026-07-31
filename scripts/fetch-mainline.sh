#!/bin/bash
# Obtain the pinned upstream Linux checkout this port builds against.
#
# If the postmarketOS build base already has the same pinned tree, clone from
# it locally so the 2 GiB history is shared instead of downloaded again; the
# commit is verified either way.
set -euo pipefail

base=${UBUNTU_WORKDIR:-/root/ubuntu-gts9u}
tag=${LINUX_TAG:-v7.2-rc3}
commit=${LINUX_COMMIT:-a13c140cc289c0b7b3770bce5b3ad42ab35074aa}
reference=${PMOS_LINUX_SRC:-/root/pmos-gts9u/linux-mainline}
target=$base/linux-mainline
upstream=https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git

mkdir -p "$base"

if [ ! -d "$target/.git" ]; then
	if [ -d "$reference/.git" ]; then
		echo "cloning from the local reference checkout: $reference"
		git clone --shared --no-checkout "$reference" "$target"
		git -C "$target" checkout --detach "$commit"
	else
		echo "cloning $tag from upstream"
		git clone --depth 1 --branch "$tag" "$upstream" "$target"
	fi
else
	echo "already present: $target"
fi

head=$(git -C "$target" rev-parse HEAD)
if [ "$head" != "$commit" ]; then
	echo "checkout is at $head, expected the pinned $commit" >&2
	exit 1
fi

echo "pinned commit verified: $head"
git -C "$target" describe --always --dirty
