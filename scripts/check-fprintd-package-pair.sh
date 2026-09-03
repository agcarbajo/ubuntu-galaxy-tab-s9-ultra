#!/bin/bash
# Read-only guard for build/deployment. dpkg --audit does not check Depends.
set -euo pipefail
if [ "$#" != 2 ]; then
    echo "usage: $0 fprintd.deb libpam-fprintd.deb" >&2
    exit 2
fi
test "$(dpkg-deb -f "$1" Package)" = fprintd
test "$(dpkg-deb -f "$2" Package)" = libpam-fprintd
test "$(dpkg-deb -f "$1" Architecture)" = arm64
test "$(dpkg-deb -f "$2" Architecture)" = arm64
version=$(dpkg-deb -f "$1" Version)
test "$(dpkg-deb -f "$2" Version)" = "$version"
depends=$(dpkg-deb -f "$2" Depends)
case ", $depends, " in
    *", fprintd (= $version), "*) ;;
    *) echo 'libpam-fprintd must depend on the exact paired daemon version' >&2; exit 1 ;;
esac
echo "Compatible fprintd/PAM package pair: $version"
