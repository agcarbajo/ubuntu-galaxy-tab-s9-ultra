#!/bin/bash
# Offline synthetic restore checks; never opens a secure device or service.
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
test_dir=$(mktemp -d -t el721-hwvault-wire.XXXXXX)
trap 'rm -f -- "$test_dir/test"; rmdir -- "$test_dir"' EXIT
# pkg-config intentionally supplies compiler/linker words.
# shellcheck disable=SC2046
${CC:-cc} -std=c11 -Wall -Wextra -Werror ${CFLAGS:-} \
  $(pkg-config --cflags glib-2.0) \
  "$repo/packaging/libfprint/el721-hwvault-wire-test.c" \
  -o "$test_dir/test" $(pkg-config --libs glib-2.0)
"$test_dir/test"
