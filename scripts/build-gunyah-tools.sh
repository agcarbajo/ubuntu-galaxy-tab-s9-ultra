#!/bin/bash
# Build the small, self-contained Gunyah ABI probes for the tablet.
set -euo pipefail

repo=$(cd "$(dirname "$0")/.." && pwd)
out=${GUNYAH_TOOLS_OUT:-$repo/out/gunyah-tools}
cc=${CC:-aarch64-linux-gnu-gcc}

mkdir -p "$out"
"$cc" -std=c11 -O2 -g -Wall -Wextra -Werror \
	-static -o "$out/gunyah-smoke" "$repo/scripts/gunyah-smoke.c"

file "$out/gunyah-smoke"
sha256sum "$out/gunyah-smoke"

"$cc" -std=c11 -O2 -g -Wall -Wextra -Werror -pthread \
	-static -o "$out/gunyah-cma-smoke" "$repo/scripts/gunyah-cma-smoke.c"
file "$out/gunyah-cma-smoke"
sha256sum "$out/gunyah-cma-smoke"
