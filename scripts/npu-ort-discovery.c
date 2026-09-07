// SPDX-License-Identifier: MIT
// Linux FastRPC discovery for the Android-ABI QNN plugin. Mirrors its Linux fallback.
#include <dlfcn.h>
#include <stdio.h>
#include <sys/stat.h>
#include <unistd.h>
#include "onnxruntime_c_api.h"
static const OrtApi *api;
static const OrtEpApi *ep;
static void *library;
static OrtEpFactory *factory_instance;
static OrtHardwareDevice *hardware;
static ReleaseEpApiFactoryFn release_factory;
static OrtStatus* (*get_supported)(OrtEpFactory*,const OrtHardwareDevice* const*,size_t,OrtEpDevice**,size_t,size_t*);
static int detected(void) {
 char data[512];FILE *f=fopen("/sys/firmware/devicetree/base/compatible","rb");if(!f)return 0;
 size_t n=fread(data,1,sizeof(data)-1,f);fclose(f);data[n]=0;int board=0;
 for(size_t i=0;i<n;){size_t len=strnlen(data+i,n-i);if(!strcmp(data+i,"samsung,gts9uwifi"))board=1;i+=len+1;}
 struct stat st;return board && stat("/dev/fastrpc-cdsp",&st)==0 && S_ISCHR(st.st_mode) && access("/dev/fastrpc-cdsp",R_OK|W_OK)==0;
}
static OrtStatus *supported(OrtEpFactory *factory,const OrtHardwareDevice* const *devices,size_t count,OrtEpDevice **out,size_t max,size_t *n) {
 fprintf(stderr,"DISCOVERY detected=%d devices=%zu max=%zu\n",detected(),count,max);
 if(!detected())return get_supported(factory,devices,count,out,max,n);
 const uint32_t vendor='Q'|('C'<<8)|('O'<<16)|('M'<<24);
 for(size_t i=0;i<count;i++)if(api->HardwareDevice_Type(devices[i])==OrtHardwareDeviceType_NPU && api->HardwareDevice_VendorId(devices[i])==vendor)return get_supported(factory,devices,count,out,max,n);
 if(!hardware){OrtStatus *s=ep->CreateHardwareDevice(OrtHardwareDeviceType_NPU,vendor,0,"Qualcomm",NULL,&hardware);if(s)return s;}
 if(count>128)return api->CreateStatus(ORT_FAIL,"Too many hardware devices");
 const OrtHardwareDevice **all=malloc((count+1)*sizeof(*all));if(!all)return api->CreateStatus(ORT_FAIL,"Out of memory");
 memcpy(all,devices,count*sizeof(*all));all[count]=hardware;
 OrtStatus *status=get_supported(factory,all,count+1,out,max,n);free(all);fprintf(stderr,"DISCOVERY output=%zu status=%p\n",*n,(void*)status);return status;
}
__attribute__((visibility("default")))
OrtStatus *CreateEpFactories(const char *name,const OrtApiBase *base,const OrtLogger *logger,OrtEpFactory **factories,size_t maximum,size_t *count) {
 api=base->GetApi(ORT_API_VERSION);if(!api)return NULL;ep=api->GetEpApi();
 if(factory_instance)return api->CreateStatus(ORT_FAIL,"Only one QNN factory is supported per adapter instance");
 library=dlopen("libonnxruntime_providers_qnn.so",RTLD_NOW|RTLD_LOCAL);if(!library)return api->CreateStatus(ORT_FAIL,dlerror());
 CreateEpApiFactoriesFn create=dlsym(library,"CreateEpFactories");release_factory=dlsym(library,"ReleaseEpFactory");
 if(!create||!release_factory)return api->CreateStatus(ORT_FAIL,"Missing QNN factory entry points");
 OrtStatus *status=create(name,base,logger,factories,maximum,count);if(status)return status;
 if(*count!=1){for(size_t i=0;i<*count;i++){OrtStatus *s=release_factory(factories[i]);if(s)api->ReleaseStatus(s);}*count=0;return api->CreateStatus(ORT_FAIL,"Expected one QNN factory");}
 factory_instance=factories[0];get_supported=factory_instance->GetSupportedDevices;factory_instance->GetSupportedDevices=supported;
 return NULL;
}
__attribute__((visibility("default")))
OrtStatus *ReleaseEpFactory(OrtEpFactory *factory) {
 factory->GetSupportedDevices=get_supported;
 OrtStatus *status=release_factory(factory);
 if(hardware){ep->ReleaseHardwareDevice(hardware);hardware=NULL;}
 factory_instance=NULL;if(library){dlclose(library);library=NULL;}return status;
}