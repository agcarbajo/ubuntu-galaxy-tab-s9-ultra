// SPDX-License-Identifier: MIT
// Quantized MatMul + Relu smoke test. Only the HTP backend is loaded.
#include <dlfcn.h>
#include <inttypes.h>
#include <math.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <QnnInterface.h>
#include <HTP/QnnHtpCommon.h>
#include <HTP/QnnHtpProfile.h>

#define CHECK(call) do { Qnn_ErrorHandle_t e = (call); if (e != QNN_SUCCESS) { \
  fprintf(stderr, "%s failed: 0x%" PRIx64 "\n", #call, (uint64_t)e); exit(1); } } while (0)
#define N 32
static QNN_INTERFACE_VER_TYPE api;
static uint64_t accel_cycles;

static void logger(const char *fmt, QnnLog_Level_t level, uint64_t time, va_list args)
{
  (void)level; (void)time;
  vfprintf(stderr, fmt, args);
  fputc('\n', stderr);
}

static void event(QnnProfile_EventId_t id, unsigned depth)
{
  QnnProfile_EventData_t data = QNN_PROFILE_EVENT_DATA_INIT;
  const QnnProfile_EventId_t *children;
  uint32_t count;
  if (depth > 16) { fprintf(stderr, "Invalid profile depth\n"); exit(1); }
  CHECK(api.profileGetEventData(id, &data));
  printf("PROFILE type=%u unit=%u value=%" PRIu64 " name=%s\n",
         data.type, data.unit, data.value, data.identifier ? data.identifier : "");
  if (data.type == QNN_HTP_PROFILE_EVENTTYPE_GRAPH_EXECUTE_ACCEL_TIME_CYCLE)
    accel_cycles += data.value;
  CHECK(api.profileGetSubEvents(id, &children, &count));
  for (uint32_t i = 0; i < count; i++) event(children[i], depth + 1);
}

static Qnn_Tensor_t tensor(const char *name, Qnn_TensorType_t type,
                           uint32_t *dims, float scale)
{
  Qnn_Tensor_t t = QNN_TENSOR_INIT;
  t.v1.name = name;
  t.v1.type = type;
  t.v1.dataType = QNN_DATATYPE_UFIXED_POINT_8;
  t.v1.quantizeParams.encodingDefinition = QNN_DEFINITION_DEFINED;
  t.v1.quantizeParams.quantizationEncoding = QNN_QUANTIZATION_ENCODING_SCALE_OFFSET;
  t.v1.quantizeParams.scaleOffsetEncoding.scale = scale;
  t.v1.quantizeParams.scaleOffsetEncoding.offset = -128;
  t.v1.rank = 2;
  t.v1.dimensions = dims;
  t.v1.memType = QNN_TENSORMEMTYPE_RAW;
  return t;
}

int main(int argc, char **argv)
{
  unsigned runs = 100;
  if (argc == 2) {
    char *end;
    unsigned long value = strtoul(argv[1], &end, 10);
    if (*end || value < 1 || value > 10000) return 2;
    runs = value;
  } else if (argc != 1) return 2;
  setvbuf(stdout, NULL, _IOLBF, 0);
  void *lib = dlopen("libQnnHtp.so", RTLD_NOW | RTLD_LOCAL);
  if (!lib) { fprintf(stderr, "%s\n", dlerror()); return 1; }
  Qnn_ErrorHandle_t (*get_providers)(const QnnInterface_t ***, uint32_t *) =
    dlsym(lib, "QnnInterface_getProviders");
  if (!get_providers) return 1;
  const QnnInterface_t **providers;
  uint32_t count;
  CHECK(get_providers(&providers, &count));
  unsigned found = 0;
  for (uint32_t i = 0; i < count; i++) {
    if (providers[i]->backendId == QNN_BACKEND_ID_HTP &&
        providers[i]->apiVersion.coreApiVersion.major == QNN_API_VERSION_MAJOR &&
        providers[i]->apiVersion.coreApiVersion.minor >= QNN_API_VERSION_MINOR) {
      api = providers[i]->QNN_INTERFACE_VER_NAME;
      found = 1;
      break;
    }
  }
  if (!found) { fprintf(stderr, "No compatible HTP provider\n"); return 1; }
  Qnn_LogHandle_t log;
  Qnn_BackendHandle_t backend;
  Qnn_DeviceHandle_t device;
  Qnn_ContextHandle_t context;
  Qnn_GraphHandle_t graph;
  Qnn_ProfileHandle_t profile;
  const char *build;
  CHECK(api.logCreate(logger, QNN_LOG_LEVEL_INFO, &log));
  CHECK(api.backendGetBuildId(&build));
  printf("BACKEND=HTP build=%s\n", build);
  CHECK(api.backendCreate(log, NULL, &backend));
  const char *wait_device = getenv("GTS9U_WAIT_DEVICE");
  if (wait_device) {
    struct timespec start, now, delay = {0, 100000};
    if (clock_gettime(CLOCK_MONOTONIC, &start)) return 1;
    while (access(wait_device, F_OK)) {
      if (clock_gettime(CLOCK_MONOTONIC, &now) || now.tv_sec - start.tv_sec >= 10) {
        fprintf(stderr, "Timed out waiting for %s\n", wait_device);
        return 1;
      }
      nanosleep(&delay, NULL);
    }
  }
  CHECK(api.deviceCreate(log, NULL, &device));
  CHECK(api.contextCreate(backend, device, NULL, &context));
  CHECK(api.graphCreate(context, "gts9u_matmul_relu", NULL, &graph));
  uint32_t dims[] = {N, N};
  uint8_t a[N*N], b[N*N], result[N*N];
  Qnn_Tensor_t inputs[] = {tensor("a", QNN_TENSOR_TYPE_APP_WRITE, dims, .125f),
                           tensor("b", QNN_TENSOR_TYPE_APP_WRITE, dims, .125f)};
  Qnn_Tensor_t mid = tensor("product", QNN_TENSOR_TYPE_NATIVE, dims, .25f);
  Qnn_Tensor_t out = tensor("result", QNN_TENSOR_TYPE_APP_READ, dims, .25f);
  CHECK(api.tensorCreateGraphTensor(graph, &inputs[0]));
  CHECK(api.tensorCreateGraphTensor(graph, &inputs[1]));
  CHECK(api.tensorCreateGraphTensor(graph, &mid));
  CHECK(api.tensorCreateGraphTensor(graph, &out));
  Qnn_OpConfig_t op = QNN_OPCONFIG_INIT;
  op.v1.name = "matmul";
  op.v1.packageName = "qti.aisw";
  op.v1.typeName = "MatMul";
  op.v1.numOfInputs = 2; op.v1.inputTensors = inputs;
  op.v1.numOfOutputs = 1; op.v1.outputTensors = &mid;
  CHECK(api.graphAddNode(graph, op));
  op.v1.name = "relu"; op.v1.typeName = "Relu";
  op.v1.numOfInputs = 1; op.v1.inputTensors = &mid;
  op.v1.outputTensors = &out;
  CHECK(api.graphAddNode(graph, op));
  CHECK(api.graphFinalize(graph, NULL, NULL));
  CHECK(api.profileCreate(backend, QNN_PROFILE_LEVEL_DETAILED, &profile));
  inputs[0].v1.clientBuf = (Qnn_ClientBuffer_t){a, sizeof(a)};
  inputs[1].v1.clientBuf = (Qnn_ClientBuffer_t){b, sizeof(b)};
  out.v1.clientBuf = (Qnn_ClientBuffer_t){result, sizeof(result)};
  unsigned max_error = 0;
  for (unsigned run = 0; run < runs; run++) {
    for (unsigned i = 0; i < N*N; i++) {
      a[i] = 128 + (int)((i * 13 + run * 7) % 15) - 7;
      b[i] = 128 + (int)((i * 3 + run * 5) % 7) - 3;
    }
    memset(result, 0xff, sizeof(result));
    CHECK(api.graphExecute(graph, inputs, 2, &out, 1, profile, NULL));
    for (unsigned row = 0; row < N; row++) for (unsigned col = 0; col < N; col++) {
      int sum = 0;
      for (unsigned k = 0; k < N; k++)
        sum += ((int)a[row*N+k] - 128) * ((int)b[k*N+col] - 128);
      int expected = 128 + (int)lroundf(fmaxf(0, sum / 16.f));
      unsigned error = abs((int)result[row*N+col] - expected);
      if (error > max_error) max_error = error;
      if (error > 1) {
        fprintf(stderr, "FAIL run=%u row=%u col=%u got=%u expected=%d\n",
                run, row, col, result[row*N+col], expected);
        return 1;
      }
    }
  }
  const QnnProfile_EventId_t *events;
  CHECK(api.profileGetEvents(profile, &events, &count));
  for (uint32_t i = 0; i < count; i++) event(events[i], 0);
  if (!accel_cycles) { fprintf(stderr, "FAIL: no HTP accelerator cycles in profile\n"); return 1; }
  CHECK(api.profileFree(profile));
  CHECK(api.contextFree(context, NULL));
  CHECK(api.deviceFree(device));
  CHECK(api.backendFree(backend));
  CHECK(api.logFree(log));
  /* The HTP runtime registers process-exit callbacks. Keep its DSO mapped until
   * process teardown; dlclose() here leaves those callbacks pointing at unmapped
   * code with QAIRT 2.45 on Android, after all QNN handles were released. */
  printf("PASS HTP MatMul+Relu runs=%u elements=%u max_quantized_error=%u accel_cycles=%" PRIu64 "\n",
         runs, runs*N*N, max_error, accel_cycles);
  return 0;
}
