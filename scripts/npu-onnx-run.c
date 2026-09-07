// SPDX-License-Identifier: MIT
#include <ctype.h>
#include <dlfcn.h>
#include <errno.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include "onnxruntime_c_api.h"

static const OrtApi *api;
#define CHECK(call) do { OrtStatus *s = (call); if (s) { fprintf(stderr, "%s: %s\n", #call, api->GetErrorMessage(s)); api->ReleaseStatus(s); return 1; } } while (0)

struct tensor { char *name; OrtTypeInfo *type; ONNXTensorElementDataType dtype; int64_t *dims; size_t rank, elements, bytes; void *data; OrtValue *value; };

static double seconds(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec + t.tv_nsec / 1e9; }

static size_t element_size(ONNXTensorElementDataType type) {
    switch (type) {
    case ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT: case ONNX_TENSOR_ELEMENT_DATA_TYPE_INT32: case ONNX_TENSOR_ELEMENT_DATA_TYPE_UINT32: return 4;
    case ONNX_TENSOR_ELEMENT_DATA_TYPE_UINT8: case ONNX_TENSOR_ELEMENT_DATA_TYPE_INT8: case ONNX_TENSOR_ELEMENT_DATA_TYPE_BOOL: return 1;
    case ONNX_TENSOR_ELEMENT_DATA_TYPE_UINT16: case ONNX_TENSOR_ELEMENT_DATA_TYPE_INT16: case ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT16: case ONNX_TENSOR_ELEMENT_DATA_TYPE_BFLOAT16: return 2;
    case ONNX_TENSOR_ELEMENT_DATA_TYPE_INT64: case ONNX_TENSOR_ELEMENT_DATA_TYPE_DOUBLE: case ONNX_TENSOR_ELEMENT_DATA_TYPE_UINT64: return 8;
    default: return 0;
    }
}

static void safe_name(char *out, size_t size, size_t index, const char *name, const char *suffix) {
    int n = snprintf(out, size, "%zu-", index); if (n < 0 || (size_t)n >= size) return;
    size_t pos = (size_t)n;
    while (*name && pos + strlen(suffix) + 1 < size) { unsigned char c = (unsigned char)*name++; out[pos++] = (isalnum(c) || c == '.' || c == '-' || c == '_') ? (char)c : '_'; }
    snprintf(out + pos, size - pos, "%s", suffix);
}

static int load_shape(const char *directory, size_t index, const char *name, int64_t *dims, size_t rank) {
    char leaf[256], path[1024], line[2048]; safe_name(leaf, sizeof(leaf), index, name, ".shape"); snprintf(path, sizeof(path), "%s/%s", directory, leaf);
    FILE *file = fopen(path, "r"); if (!file) return -1;
    if (!fgets(line, sizeof(line), file) || fclose(file)) return -1;
    char *cursor = line;
    for (size_t i = 0; i < rank; i++) { char *end; errno = 0; long long value = strtoll(cursor, &end, 10); if (errno || end == cursor || value <= 0) return -1; dims[i] = (int64_t)value; cursor = end; while (*cursor == ',' || isspace((unsigned char)*cursor)) cursor++; }
    return *cursor && *cursor != '\n' ? -1 : 0;
}

static int inspect_input(OrtSession *session, OrtAllocator *allocator, size_t index, const char *directory, struct tensor *tensor) {
    const OrtTensorTypeAndShapeInfo *shape;
    CHECK(api->SessionGetInputName(session, index, allocator, &tensor->name)); CHECK(api->SessionGetInputTypeInfo(session, index, &tensor->type)); CHECK(api->CastTypeInfoToTensorInfo(tensor->type, &shape)); CHECK(api->GetTensorElementType(shape, &tensor->dtype));
    size_t unit = element_size(tensor->dtype); if (!unit) { fprintf(stderr, "Unsupported tensor type %d for %s\n", tensor->dtype, tensor->name); return 1; }
    CHECK(api->GetDimensionsCount(shape, &tensor->rank)); if (!tensor->rank || tensor->rank > 16) return 1;
    tensor->dims = calloc(tensor->rank, sizeof(*tensor->dims)); if (!tensor->dims) return 1; CHECK(api->GetDimensions(shape, tensor->dims, tensor->rank));
    int dynamic = 0; for (size_t i = 0; i < tensor->rank; i++) dynamic |= tensor->dims[i] <= 0;
    if (dynamic && load_shape(directory, index, tensor->name, tensor->dims, tensor->rank)) { fprintf(stderr, "Dynamic input %s needs %zu-%s.shape\n", tensor->name, index, tensor->name); return 1; }
    tensor->elements = 1;
    for (size_t i = 0; i < tensor->rank; i++) { if (tensor->dims[i] <= 0 || (uint64_t)tensor->elements > 1000000000ULL / (uint64_t)tensor->dims[i]) return 1; tensor->elements *= (size_t)tensor->dims[i]; }
    tensor->bytes = tensor->elements * unit; return 0;
}

static int load_input(const char *source, size_t index, struct tensor *tensor, OrtMemoryInfo *memory, int legacy) {
    char leaf[256], path[1024]; if (legacy) snprintf(path, sizeof(path), "%s", source); else { safe_name(leaf, sizeof(leaf), index, tensor->name, ".raw"); snprintf(path, sizeof(path), "%s/%s", source, leaf); }
    FILE *file = fopen(path, "rb"); if (!file) { perror(path); return 1; }
    tensor->data = malloc(tensor->bytes); if (!tensor->data) { fclose(file); return 1; }
    if (fread(tensor->data, 1, tensor->bytes, file) != tensor->bytes || fgetc(file) != EOF) { fprintf(stderr, "Input size mismatch: %s needs %zu bytes\n", path, tensor->bytes); fclose(file); return 1; } fclose(file);
    CHECK(api->CreateTensorWithDataAsOrtValue(memory, tensor->data, tensor->bytes, tensor->dims, tensor->rank, tensor->dtype, &tensor->value));
    printf("INPUT index=%zu name=%s type=%d elements=%zu bytes=%zu\n", index, tensor->name, tensor->dtype, tensor->elements, tensor->bytes); return 0;
}

static int save_output(const char *destination, size_t index, const char *name, OrtValue *value, int legacy) {
    OrtTensorTypeAndShapeInfo *shape; ONNXTensorElementDataType dtype; size_t elements;
    CHECK(api->GetTensorTypeAndShape(value, &shape)); CHECK(api->GetTensorShapeElementCount(shape, &elements)); CHECK(api->GetTensorElementType(shape, &dtype));
    size_t unit = element_size(dtype); if (!unit || elements > 1000000000ULL / unit) return 1;
    void *data; CHECK(api->GetTensorMutableData(value, &data));
    if (dtype == ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT) { float *values = data; for (size_t i = 0; i < elements; i++) if (!isfinite(values[i])) return 1; }
    char leaf[256], path[1024]; if (legacy) snprintf(path, sizeof(path), "%s", destination); else { safe_name(leaf, sizeof(leaf), index, name, ".raw"); snprintf(path, sizeof(path), "%s/%s", destination, leaf); }
    FILE *file = fopen(path, "wb"); if (!file) { perror(path); return 1; } if (fwrite(data, unit, elements, file) != elements || fclose(file)) return 1;
    printf("OUTPUT index=%zu name=%s type=%d elements=%zu bytes=%zu file=%s\n", index, name, dtype, elements, unit * elements, path); api->ReleaseTensorTypeAndShapeInfo(shape); return 0;
}

int main(int argc, char **argv) {
    if (argc < 5) { fprintf(stderr, "Usage: %s model.onnx input-path output-path runs [symbol=value ...]\n", argv[0]); return 2; }
    unsigned runs = (unsigned)strtoul(argv[4], NULL, 10); if (!runs || runs > 100000) return 2;
    int profile_enabled = getenv("GTS9U_ONNX_DISABLE_PROFILE") == NULL;
    struct stat input_stat, output_stat; if (stat(argv[2], &input_stat)) { perror(argv[2]); return 2; }
    int legacy = S_ISREG(input_stat.st_mode);
    if (!legacy && (!S_ISDIR(input_stat.st_mode) || stat(argv[3], &output_stat) || !S_ISDIR(output_stat.st_mode))) { fprintf(stderr, "Multi-tensor mode requires existing input and output directories\n"); return 2; }
    setvbuf(stdout, NULL, _IOLBF, 0);
    void *lib = dlopen("libonnxruntime.so", RTLD_NOW | RTLD_LOCAL); if (!lib) { fprintf(stderr, "%s\n", dlerror()); return 1; }
    const OrtApiBase *(*get_base)(void) = dlsym(lib, "OrtGetApiBase"); if (!get_base) return 1;
    printf("ORT=%s\n", get_base()->GetVersionString()); api = get_base()->GetApi(ORT_API_VERSION); if (!api) return 1;
    OrtEnv *env; OrtSessionOptions *options; OrtSession *session;
    CHECK(api->CreateEnv(ORT_LOGGING_LEVEL_WARNING, "gts9u-onnx", &env)); CHECK(api->RegisterExecutionProviderLibrary(env, "QNN", "libgts9u_ort_qnn.so"));
    const OrtEpDevice *const *devices; size_t device_count; const OrtEpDevice *selected = NULL; CHECK(api->GetEpDevices(env, &devices, &device_count));
    for (size_t i = 0; i < device_count; i++) { const char *name = api->EpDevice_EpName(devices[i]); printf("EP_DEVICE=%s\n", name); if (strstr(name, "QNN")) selected = devices[i]; }
    if (!selected) return 1;
    CHECK(api->CreateSessionOptions(&options));
    const char *keys[] = {"backend_path", "enable_htp_fp16_precision", "htp_performance_mode", "profiling_level", "profiling_file_path"};
    const char *values[] = {"libQnnHtp.so", "1", "balanced", "basic", "qnn-profile.csv"};
    CHECK(api->SessionOptionsAppendExecutionProvider_V2(options, env, &selected, 1, keys, values, profile_enabled ? 5 : 3)); CHECK(api->AddSessionConfigEntry(options, "session.disable_cpu_ep_fallback", "1"));
    CHECK(api->SetIntraOpNumThreads(options, 2)); CHECK(api->SetInterOpNumThreads(options, 1)); CHECK(api->SetSessionGraphOptimizationLevel(options, ORT_ENABLE_ALL)); if (profile_enabled) CHECK(api->EnableProfiling(options, "ort-profile"));
    for (int i = 5; i < argc; i++) { char *equals = strchr(argv[i], '='); if (!equals || equals == argv[i] || !equals[1]) return 2; *equals = '\0'; int64_t value = strtoll(equals + 1, NULL, 10); if (value <= 0) return 2; CHECK(api->AddFreeDimensionOverrideByName(options, argv[i], value)); printf("DIM_OVERRIDE name=%s value=%lld\n", argv[i], (long long)value); }
    double started = seconds(); CHECK(api->CreateSession(env, argv[1], options, &session)); printf("SESSION_SECONDS=%.6f\n", seconds() - started);
    size_t input_count, output_count; CHECK(api->SessionGetInputCount(session, &input_count)); CHECK(api->SessionGetOutputCount(session, &output_count));
    if (!input_count || !output_count || (legacy && (input_count != 1 || output_count != 1))) { fprintf(stderr, "Legacy mode requires one input and one output\n"); return 2; }
    OrtAllocator *allocator; OrtMemoryInfo *memory; CHECK(api->GetAllocatorWithDefaultOptions(&allocator)); CHECK(api->CreateCpuMemoryInfo(OrtArenaAllocator, OrtMemTypeDefault, &memory));
    struct tensor *inputs = calloc(input_count, sizeof(*inputs)); char **output_names = calloc(output_count, sizeof(*output_names)); OrtValue **outputs = calloc(output_count, sizeof(*outputs)); const char **input_names = calloc(input_count, sizeof(*input_names)); const OrtValue **input_values = calloc(input_count, sizeof(*input_values));
    if (!inputs || !output_names || !outputs || !input_names || !input_values) return 1;
    for (size_t i = 0; i < input_count; i++) { if (inspect_input(session, allocator, i, argv[2], &inputs[i]) || load_input(argv[2], i, &inputs[i], memory, legacy)) return 1; input_names[i] = inputs[i].name; input_values[i] = inputs[i].value; }
    for (size_t i = 0; i < output_count; i++) CHECK(api->SessionGetOutputName(session, i, allocator, &output_names[i]));
    started = seconds();
    for (unsigned run = 0; run < runs; run++) { for (size_t i = 0; i < output_count; i++) { if (outputs[i]) api->ReleaseValue(outputs[i]); outputs[i] = NULL; } CHECK(api->Run(session, NULL, input_names, input_values, input_count, (const char *const *)output_names, output_count, outputs)); }
    printf("RUNS=%u TOTAL_SECONDS=%.6f INPUTS=%zu OUTPUTS=%zu\n", runs, seconds() - started, input_count, output_count);
    for (size_t i = 0; i < output_count; i++) if (save_output(argv[3], i, output_names[i], outputs[i], legacy)) return 1;
    if (profile_enabled) { char *profile; CHECK(api->SessionEndProfiling(session, allocator, &profile)); printf("ORT_PROFILE=%s\n", profile); allocator->Free(allocator, profile); } else { puts("ORT_PROFILE=disabled"); }
    for (size_t i = 0; i < input_count; i++) { api->ReleaseValue(inputs[i].value); api->ReleaseTypeInfo(inputs[i].type); allocator->Free(allocator, inputs[i].name); free(inputs[i].dims); free(inputs[i].data); }
    for (size_t i = 0; i < output_count; i++) { api->ReleaseValue(outputs[i]); allocator->Free(allocator, output_names[i]); }
    free(inputs); free(output_names); free(outputs); free(input_names); free(input_values); api->ReleaseMemoryInfo(memory); api->ReleaseSession(session); api->ReleaseSessionOptions(options);
    CHECK(api->UnregisterExecutionProviderLibrary(env, "QNN")); api->ReleaseEnv(env); dlclose(lib); puts("PASS ONNX HTP inference; CPU fallback disabled"); return 0;
}
