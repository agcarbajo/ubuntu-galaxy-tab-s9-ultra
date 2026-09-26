#!/bin/sh
# Build inside the selected Ubuntu arm64 buildroot, never on the tablet.
set -eu
cd "$(dirname "$0")"
api=${MUTTER_API:-14}
case "$api" in 14|18) ;; *) echo "unsupported Mutter API: $api" >&2; exit 2 ;; esac
mutter_dir=/usr/lib/aarch64-linux-gnu/mutter-$api
clutter_pkg=mutter-clutter-$api

cc -std=c11 -fPIC -shared -Wall -Wextra -Werror \
  -Wl,-rpath,"$mutter_dir" \
  -o libgts9u-presented.so gts9u-presented-watcher.c \
  $(pkg-config --cflags --libs "$clutter_pkg")

GI_TYPELIB_PATH="$mutter_dir" \
LD_LIBRARY_PATH=".:$mutter_dir" \
g-ir-scanner --quiet --warn-all --namespace=Gts9uPresented --nsversion=1.0 \
  --identifier-prefix=Gts9u --symbol-prefix=gts9u \
  --library=gts9u-presented --library-path=. \
  --add-include-path="$mutter_dir" \
  --include="Clutter-$api" --pkg="$clutter_pkg" --pkg=gobject-2.0 \
  --output=Gts9uPresented-1.0.gir \
  gts9u-presented-watcher.h gts9u-presented-watcher.c

g-ir-compiler --includedir="$mutter_dir" \
  Gts9uPresented-1.0.gir -o Gts9uPresented-1.0.typelib
