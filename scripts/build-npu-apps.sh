#!/bin/bash
# Run inside the pinned Snapdragon Android toolchain, with the repository mounted.
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
: "${APP_WORK:?Set APP_WORK to the Linux source/build directory}"
: "${APP_OUTPUT:?Set APP_OUTPUT to a new bundle directory}"
: "${ANDROID_NDK_ROOT:?Use the pinned Snapdragon toolchain v0.7 (NDK r29)}"
: "${HEXAGON_SDK_ROOT:?Hexagon SDK 6.6.0.0 is required}"
: "${HEXAGON_TOOLS_ROOT:?Hexagon Tools 19.0.07 is required}"
: "${QWEN_MODEL:?Path to official Qwen3-1.7B-Q8_0.gguf}"
: "${WHISPER_MODEL:?Path to ggml-tiny.bin}"
: "${LLAMA_UI_ARCHIVE:?Path to the verified llama-ui dist.tar.gz}"
test ! -e "$APP_OUTPUT"
printf '%s  %s\n' 061b54daade076b5d3362dac252678d17da8c68f07560be70818cace6590cb1a "$QWEN_MODEL" | sha256sum -c -
printf '%s  %s\n' be07e048e1e599ad46341c8d2a135645097a538221678b7acdd1b1919c6e1b21 "$WHISPER_MODEL" | sha256sum -c -
printf '%s  %s\n' 5c06c8aebfc61f694c29d54f6d80e4460ee9040c7dfec456047cef02703e9b1d "$LLAMA_UI_ARCHIVE" | sha256sum -c -
mkdir -p "$APP_WORK" "$APP_OUTPUT"
for component in llama whisper; do
    if [ "$component" = llama ]; then
        revision=427291b5b34cd914a31b3fd3b61a68f6184f4b9f
        targets=(llama-server llama-completion test-backend-ops htp-v73)
    else
        revision=52a939a2a762224e255d366c1182b2af4dd1a032
        targets=(whisper-cli whisper-server htp-v73)
    fi
    source="$APP_WORK/$component.cpp"
    if [ ! -d "$source" ]; then
        git clone "https://github.com/ggml-org/$component.cpp.git" "$source"
        git -C "$source" checkout --detach "$revision"
    fi
    test "$(git -C "$source" rev-parse HEAD)" = "$revision"
    if [ "$component" = whisper ]; then
        patch="$repo/configs/npu/whisper-split-conversion-copy.patch"
        if git -C "$source" apply --check "$patch" 2>/dev/null; then
            git -C "$source" apply "$patch"
        else
            git -C "$source" apply --reverse --check "$patch"
        fi
    else
        patch="$repo/configs/npu/llama-hexagon-iova-window.patch"
        if git -C "$source" apply --check "$patch" 2>/dev/null; then
            git -C "$source" apply "$patch"
        else
            git -C "$source" apply --reverse --check "$patch"
        fi
        mkdir -p "$source/tools/ui/dist"
        tar -xzf "$LLAMA_UI_ARCHIVE" -C "$source/tools/ui/dist"
    fi
    build="$source/build-gts9u"
    cmake -S "$source" -B "$build" -G Ninja -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_TOOLCHAIN_FILE="$ANDROID_NDK_ROOT/build/cmake/android.toolchain.cmake" \
        -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-30 -DGGML_NATIVE=OFF \
        -DGGML_HEXAGON=ON -DGGML_OPENCL=OFF -DGGML_OPENMP=OFF -DLLAMA_OPENSSL=OFF \
        -DPREBUILT_LIB_DIR=android_aarch64 -DHEXAGON_SDK_ROOT="$HEXAGON_SDK_ROOT" \
        -DHEXAGON_TOOLS_ROOT="$HEXAGON_TOOLS_ROOT"
    cmake --build "$build" --target "${targets[@]}" -j "${JOBS:-4}"
    destination="$APP_OUTPUT/$component"
    mkdir -p "$destination"/{bin,lib,dsp,models,licenses}
    for executable in "${targets[@]}"; do
        [ "$executable" = htp-v73 ] || cp "$build/bin/$executable" "$destination/bin/"
    done
    cp -L "$build/bin/"*.so* "$destination/lib/"
    cp "$build/ggml/src/ggml-hexagon/libggml-htp-v73.so" "$destination/dsp/"
    cp "$ANDROID_NDK_ROOT/toolchains/llvm/prebuilt/linux-x86_64/sysroot/usr/lib/aarch64-linux-android/libc++_shared.so" "$destination/lib/"
    cp "$source/LICENSE" "$destination/licenses/"
    if [ "$component" = llama ]; then
        mkdir -p "$destination/patches"
        cp "$repo/configs/npu/llama-hexagon-iova-window.patch" "$destination/patches/"
    fi
    printf '%s\n' "$revision" > "$destination/source-revision"
done
cp "$QWEN_MODEL" "$APP_OUTPUT/llama/models/Qwen3-1.7B-Q8_0.gguf"
cp "$WHISPER_MODEL" "$APP_OUTPUT/whisper/models/ggml-tiny.bin"
cp "$LLAMA_UI_ARCHIVE" "$APP_OUTPUT/llama/llama-ui-dist.tar.gz"
mkdir "$APP_OUTPUT/integration"
cp "$repo/scripts/gts9u-npu-app.py" "$repo/scripts/gts9u-ai-studio.py" "$APP_OUTPUT/integration/"
cp "$repo/configs/npu/model-catalog.json" "$APP_OUTPUT/integration/"
cp "$repo/configs/npu/verified-models.json" "$APP_OUTPUT/integration/"
cp "$repo/configs/npu/io.github.agcarbajo.LocalAI.desktop" "$APP_OUTPUT/integration/"
(cd "$APP_OUTPUT" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
echo "Built $APP_OUTPUT"
