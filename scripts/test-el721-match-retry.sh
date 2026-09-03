#!/bin/bash
# Offline notification lifecycle test; never opens the reader.
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
test_dir=$(mktemp -d -t el721-match-retry.XXXXXX)
trap 'rm -f -- "$test_dir/test"; rmdir -- "$test_dir"' EXIT
# shellcheck disable=SC2046
${CC:-cc} -std=c11 -Wall -Wextra -Werror ${CFLAGS:-} \
  $(pkg-config --cflags glib-2.0) \
  "$repo/packaging/libfprint/el721-match-retry-test.c" \
  -o "$test_dir/test" $(pkg-config --libs glib-2.0)
"$test_dir/test"
