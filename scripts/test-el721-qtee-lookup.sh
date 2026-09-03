#!/bin/bash
# Offline mocked invocation; no secure services or credentials are accessed.
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
: "${QTEE_INCLUDE_DIR:?set QTEE_INCLUDE_DIR to the pinned quic-teec headers}"
test_dir=$(mktemp -d -t el721-qtee-lookup.XXXXXX)
trap 'rm -f -- "$test_dir/test"; rmdir -- "$test_dir"' EXIT
# shellcheck disable=SC2046
${CC:-cc} -std=c11 -Wall -Wextra -Werror ${CFLAGS:-} \
  $(pkg-config --cflags glib-2.0) -I"$QTEE_INCLUDE_DIR" \
  "$repo/packaging/libfprint/el721-qtee-lookup-test.c" \
  -o "$test_dir/test" $(pkg-config --libs glib-2.0)
"$test_dir/test"
