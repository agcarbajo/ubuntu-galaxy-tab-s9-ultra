// SPDX-License-Identifier: GPL-2.0-only
/* CMA allocation/lifetime probe. Never starts a VM or transfers ownership. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>

#define CREATE_CMA _IO('A', 0x14)
#define CREATE_VM _IO('G', 0x0)
struct cma_mapping {
	uint32_t label;
	uint64_t guest_addr;
	uint32_t flags, guest_mem_fd;
	uint64_t offset, size;
};
#define MAP_CMA _IOW('A', 0x15, struct cma_mapping)
_Static_assert(sizeof(struct cma_mapping) == 40, "CMA ABI layout");

static void require(int ok, const char *what)
{
	if (!ok) {
		fprintf(stderr, "FAIL: %s (errno=%d: %s)\n", what, errno, strerror(errno));
		exit(EXIT_FAILURE);
	}
}

struct contender { int device, fd, error; pthread_barrier_t *barrier; };
static void *compete(void *data)
{
	struct contender *c = data;
	pthread_barrier_wait(c->barrier);
	c->fd = ioctl(c->device, CREATE_CMA);
	c->error = errno;
	return NULL;
}

static int wait_for_reclaim(int device)
{
	for (int i = 0; i < 500; i++) {
		int fd = ioctl(device, CREATE_CMA);
		if (fd >= 0 || errno != EBUSY)
			return fd;
		/* VM teardown runs on the kernel workqueue. */
		usleep(10000);
	}
	return -1;
}

static void exclusive_creation(int device)
{
	pthread_barrier_t barrier;
	pthread_t threads[8];
	struct contender contenders[8];
	int winners = 0;
	require(!pthread_barrier_init(&barrier, NULL, 8), "barrier init");
	for (int i = 0; i < 8; i++) {
		contenders[i] = (struct contender){ .device = device, .barrier = &barrier };
		require(!pthread_create(&threads[i], NULL, compete, &contenders[i]), "thread create");
	}
	for (int i = 0; i < 8; i++) {
		require(!pthread_join(threads[i], NULL), "thread join");
		if (contenders[i].fd >= 0)
			winners++;
		else
			require(contenders[i].error == EBUSY, "concurrent loser returns EBUSY");
	}
	require(winners == 1, "exactly one concurrent CMA descriptor");
	for (int i = 0; i < 8; i++)
		if (contenders[i].fd >= 0)
			close(contenders[i].fd);
	pthread_barrier_destroy(&barrier);
	puts("PASS exclusive concurrent creation");
}

int main(int argc, char **argv)
{
	const char *path = argc > 1 ? argv[1] : "/dev/gunyah-vm-cma";
	const size_t size = 16UL * 1024 * 1024;
	int device = open(path, O_RDWR | O_CLOEXEC);
	int manager, vm;
	require(device >= 0, "open CMA pool");
	setvbuf(stdout, NULL, _IONBF, 0);
	exclusive_creation(device);
	manager = open("/dev/gunyah", O_RDWR | O_CLOEXEC);
	require(manager >= 0, "open Gunyah");
	for (int round = 0; round < 3; round++) {
		int fd = ioctl(device, CREATE_CMA);
		unsigned char *ram;
		struct cma_mapping map = { .guest_addr = 0x80000000,
			.flags = 0x27, .guest_mem_fd = fd, .size = size };
		require(fd >= 0, "create CMA fd");
		require((fcntl(fd, F_GETFD) & FD_CLOEXEC) != 0, "CLOEXEC");
		ram = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_PRIVATE, fd, 0);
		require(ram == MAP_FAILED && errno == EINVAL, "reject private mapping");
		ram = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 4096);
		require(ram == MAP_FAILED && errno == EINVAL, "reject nonzero mmap offset");
		ram = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
		require(ram != MAP_FAILED, "map contiguous memory");
		for (size_t i = 0; i < size; i++)
			require(ram[i] == 0, "new allocation is zeroed");
		memset(ram, 0xa5, size);
		vm = ioctl(manager, CREATE_VM, 0);
		require(vm >= 0, "create non-starting VM");
		map.offset = UINT64_MAX - 4095;
		require(ioctl(vm, MAP_CMA, &map) < 0 && errno == EOVERFLOW, "reject offset overflow");
		map.offset = size;
		require(ioctl(vm, MAP_CMA, &map) < 0 && errno == EINVAL, "reject out-of-range offset");
		map.offset = 0;
		require(ioctl(vm, MAP_CMA, &map) == 0, "register CMA memory");
		require(ioctl(vm, MAP_CMA, &map) < 0 && errno == EEXIST, "reject duplicate label");
		close(fd);
		require(ioctl(device, CREATE_CMA) < 0 && errno == EBUSY, "VMA/VM retain allocation");
		for (size_t i = 0; i < size; i++)
			require(ram[i] == 0xa5, "mapping survives fd close");
		require(!munmap(ram, size), "unmap");
		require(ioctl(device, CREATE_CMA) < 0 && errno == EBUSY, "VM retains allocation without VMA");
		close(vm);
		fd = wait_for_reclaim(device);
		require(fd >= 0, "asynchronous VM reclaim completes");
		close(fd);
		printf("PASS allocation/zeroing/bounds/lifetime/reclaim round %d\n", round + 1);
	}
	exclusive_creation(device);
	close(manager);
	close(device);
	puts("CMA_SMOKE_PASS: no VM was started");
	return 0;
}
