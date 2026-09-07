// SPDX-License-Identifier: MIT
// SM8550 CDSP temporary power workaround. Supervisor stops CDSP before this process.
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
#include <stdbool.h>
#include <signal.h>
#include <HTP/QnnHtpDevice.h>
#include <unistd.h>
#include <HTP/QnnHtpCommon.h>
#include <HTP/QnnHtpProfile.h>

#define CHECK(call) do { Qnn_ErrorHandle_t e = (call); if (e != QNN_SUCCESS) { \
  fprintf(stderr, "%s failed: 0x%" PRIx64 "\n", #call, (uint64_t)e); exit(1); } } while (0)
static QNN_INTERFACE_VER_TYPE api;
static volatile sig_atomic_t stopping;

static void stop_requested(int sig)
{
  (void)sig;
  stopping = 1;
}
static void logger(const char *fmt, QnnLog_Level_t level, uint64_t time, va_list args)
{
  (void)level; (void)time;
  vfprintf(stderr, fmt, args);
  fputc('\n', stderr);
}

int main(void)
{
  signal(SIGTERM, stop_requested);
  signal(SIGINT, stop_requested);
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
  const char *build;
  CHECK(api.logCreate(logger, QNN_LOG_LEVEL_WARN, &log));
  CHECK(api.backendGetBuildId(&build));
  printf("BACKEND=HTP build=%s\n", build);
  CHECK(api.backendCreate(log, NULL, &backend));
  CHECK(api.deviceCreate(log, NULL, &device));
  QnnDevice_Infrastructure_t infrastructure = NULL;
  CHECK(api.deviceGetInfrastructure(&infrastructure));
  QnnHtpDevice_Infrastructure_t *htp = (QnnHtpDevice_Infrastructure_t *)infrastructure;
  if (!htp || htp->infraType != QNN_HTP_DEVICE_INFRASTRUCTURE_TYPE_PERF) return 1;
  uint32_t power_id;
  CHECK(htp->perfInfra.createPowerConfigId(0, 0, &power_id));
  QnnHtpPerfInfrastructure_PowerConfig_t power = QNN_HTP_PERF_INFRASTRUCTURE_POWER_CONFIG_INIT;
  power.option = QNN_HTP_PERF_INFRASTRUCTURE_POWER_CONFIGOPTION_DCVS_V3;
  power.dcvsV3Config.contextId = power_id;
  power.dcvsV3Config.setDcvsEnable = 1;
  power.dcvsV3Config.dcvsEnable = 0;
  power.dcvsV3Config.powerMode = QNN_HTP_PERF_INFRASTRUCTURE_POWERMODE_PERFORMANCE_MODE;
  power.dcvsV3Config.setSleepLatency = 1;
  power.dcvsV3Config.sleepLatency = 40;
  power.dcvsV3Config.setSleepDisable = 1;
  power.dcvsV3Config.sleepDisable = 1;
  power.dcvsV3Config.setBusParams = 1;
  power.dcvsV3Config.busVoltageCornerMin = DCVS_VOLTAGE_VCORNER_SVS;
  power.dcvsV3Config.busVoltageCornerTarget = DCVS_VOLTAGE_VCORNER_SVS;
  power.dcvsV3Config.busVoltageCornerMax = DCVS_VOLTAGE_VCORNER_SVS;
  power.dcvsV3Config.setCoreParams = 1;
  power.dcvsV3Config.coreVoltageCornerMin = DCVS_VOLTAGE_VCORNER_SVS;
  power.dcvsV3Config.coreVoltageCornerTarget = DCVS_VOLTAGE_VCORNER_SVS;
  power.dcvsV3Config.coreVoltageCornerMax = DCVS_VOLTAGE_VCORNER_SVS;
  const QnnHtpPerfInfrastructure_PowerConfig_t *powers[] = { &power, NULL };
  CHECK(htp->perfInfra.setPowerConfig(power_id, powers));
  const char *path = getenv("GTS9U_NPU_READY");
  if (!path) return 2;
  const char *stop_path = getenv("GTS9U_NPU_STOP");
  FILE *ready = fopen(path, "w");
  if (!ready) return 1;
  fputs("ready\n", ready); fclose(ready);
  puts("POWER_KEEPER_READY");
  unsigned interval_ms = 100;
  const char *interval_text = getenv("GTS9U_KEEPER_INTERVAL_MS");
  if (interval_text) {
    char *end = NULL;
    unsigned long parsed = strtoul(interval_text, &end, 10);
    if (!*interval_text || *end || parsed < 50 || parsed > 20000) {
      fprintf(stderr, "GTS9U_KEEPER_INTERVAL_MS must be 50..20000\n");
      return 2;
    }
    interval_ms = (unsigned)parsed;
  }
  printf("KEEPER_INTERVAL_MS=%u\n", interval_ms);
  for (unsigned n = 0;
       !stopping && (!stop_path || access(stop_path, F_OK) != 0); n++) {
    power.dcvsV3Config.sleepLatency = 40 + (n & 1);
    CHECK(htp->perfInfra.setPowerConfig(power_id, powers));
    if ((n % 50U) == 0U) {
      struct timespec now;
      if (clock_gettime(CLOCK_BOOTTIME, &now) == 0)
        printf("KEEPER_TICK=%u boottime=%lld.%09ld\n", n,
               (long long)now.tv_sec, now.tv_nsec);
    }
    usleep(interval_ms * 1000U);
  }
  CHECK(htp->perfInfra.destroyPowerConfigId(power_id));
  CHECK(api.deviceFree(device));
  CHECK(api.backendFree(backend));
  CHECK(api.logFree(log));
  puts("POWER_KEEPER_STOPPED");
  return 0;
}
