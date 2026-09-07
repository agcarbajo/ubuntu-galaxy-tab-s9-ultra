// SPDX-License-Identifier: MIT
// Bounded startup traffic; supervisor terminates it when the power owner is ready.
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <pthread.h>
#include <sched.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>
#include <misc/fastrpc.h>
#define THREADS 12
static int fd, ready;
static pthread_barrier_t gate;
static double start;
static double seconds(void) { struct timespec ts; clock_gettime(CLOCK_MONOTONIC,&ts); return ts.tv_sec+ts.tv_nsec/1e9; }
static void *worker(void *value)
{
    int id=(int)(intptr_t)value;
    uint32_t count=255, attrs[255]={0};
    uint64_t completed=0;
    struct fastrpc_invoke_args args[2]={
        {.ptr=(uintptr_t)&count,.length=sizeof(count),.fd=-1},
        {.ptr=(uintptr_t)attrs,.length=sizeof(attrs),.fd=-1},
    };
    struct fastrpc_invoke invoke={.handle=2,.sc=0x10100,.args=(uintptr_t)args};
    cpu_set_t cpus; CPU_ZERO(&cpus); CPU_SET(4+id%3,&cpus);
    pthread_setaffinity_np(pthread_self(),sizeof(cpus),&cpus);
    pthread_barrier_wait(&gate);
    if (!ready) return NULL;
    while (seconds()-start<35) {
        int ret=ioctl(fd,FASTRPC_IOCTL_INVOKE,&invoke);
        if (ret) { fprintf(stderr,"worker=%d ret=%d errno=%d completed=%" PRIu64 "\n",id,ret,errno,completed); return NULL; }
        completed++;
        if (completed==1 || completed%1000==0)
            printf("worker=%d completed=%" PRIu64 " elapsed=%.3f\n",id,completed,seconds()-start);
    }
    printf("DONE worker=%d completed=%" PRIu64 "\n",id,completed);
    return NULL;
}
int main(void)
{
    pthread_t workers[THREADS];
    setbuf(stdout,NULL);
    fd=open("/dev/fastrpc-cdsp-secure",O_RDWR|O_CLOEXEC);
    if(fd<0) {perror("open");return 2;}
    pthread_barrier_init(&gate,NULL,THREADS+1);
    for(int i=0;i<THREADS;i++) if(pthread_create(&workers[i],NULL,worker,(void*)(intptr_t)i)) return 2;
    printf("Capability pipeline prepared threads=%d\n",THREADS);
    int ret=ioctl(fd,FASTRPC_IOCTL_INIT_ATTACH);
    ready=!ret; start=seconds();
    printf("Root attachment result=%d errno=%d\n",ret,errno);
    pthread_barrier_wait(&gate);
    for(int i=0;i<THREADS;i++) pthread_join(workers[i],NULL);
    close(fd);
    return ready?0:1;
}
