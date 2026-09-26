#!/bin/sh
# Build inside the pinned Ubuntu Noble arm64 buildroot, never on the tablet.
set -eu
cd "$(dirname "$0")"

cc -std=c11 -fPIC -shared -Wall -Wextra -Werror \
  -Wl,-rpath,/usr/lib/aarch64-linux-gnu/mutter-14 \
  -o libgts9u-presented.so gts9u-presented-watcher.c \
  $(pkg-config --cflags --libs mutter-clutter-14)

GI_TYPELIB_PATH=/usr/lib/aarch64-linux-gnu/mutter-14 \
LD_LIBRARY_PATH=".:/usr/lib/aarch64-linux-gnu/mutter-14" \
g-ir-scanner --quiet --warn-all --namespace=Gts9uPresented --nsversion=1.0 \
  --identifier-prefix=Gts9u --symbol-prefix=gts9u \
  --library=gts9u-presented --library-path=. \
  --add-include-path=/usr/lib/aarch64-linux-gnu/mutter-14 \
  --include=Clutter-14 --pkg=mutter-clutter-14 --pkg=gobject-2.0 \
  --output=Gts9uPresented-1.0.gir \
  gts9u-presented-watcher.h gts9u-presented-watcher.c

g-ir-compiler --includedir=/usr/lib/aarch64-linux-gnu/mutter-14 \
  Gts9uPresented-1.0.gir -o Gts9uPresented-1.0.typelib
