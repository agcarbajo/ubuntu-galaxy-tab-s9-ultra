#!/bin/bash
# Build the optional native Linux Vulkan/CPU engine on the SM-X910 itself.
set -euo pipefail
if [ "$(id -u)" != 0 ] || [ "$#" != 1 ]; then
    echo "Usage: sudo $0 /path/to/llama-source.tar.gz" >&2
    exit 2
fi
archive=$(realpath "$1")
work=/var/tmp/gts9u-llama-vulkan-build
target=/opt/gts9u-npu-vulkan
rm -rf "$work"
install -d -m0755 "$work/source" "$work/build"
tar -xzf "$archive" -C "$work/source"
cmake -S "$work/source" -B "$work/build" -G Ninja \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$target" \
    -DGGML_VULKAN=ON -DGGML_NATIVE=OFF -DGGML_CPU_ARM_ARCH=armv8.6-a+dotprod+i8mm \
    -DGGML_OPENMP=OFF \
    -DLLAMA_CURL=OFF -DLLAMA_BUILD_SERVER=ON -DLLAMA_BUILD_TESTS=OFF \
    -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_TOOLS=ON -DBUILD_SHARED_LIBS=ON
cmake --build "$work/build" --target llama-server llama-cli llama-bench -j4
install -d -m0755 "$target/bin" "$target/lib"
for binary in llama-server llama-cli llama-bench; do
    install -m0755 "$work/build/bin/$binary" "$target/bin/$binary"
done
for library in "$work/build/bin/"*.so "$work/build/bin/"*.so.*; do
    [ -e "$library" ] || continue
    cp -a "$library" "$target/lib/"
done
printf '%s\n' '427291b5b34cd914a31b3fd3b61a68f6184f4b9f' > "$target/source-revision"
LD_LIBRARY_PATH="$target/lib" "$target/bin/llama-server" --list-devices
