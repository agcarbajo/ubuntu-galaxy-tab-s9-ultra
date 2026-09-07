// SPDX-License-Identifier: GPL-2.0-only
/*
 * Non-destructive userspace ABI probe for the Linux Gunyah VM manager.
 *
 * This deliberately never issues GH_VM_START.  It proves that /dev/gunyah can
 * create an anonymous VM, accept ordinary shared userspace RAM, create a proxy
 * scheduled vCPU and expose the vCPU run page.  Closing the descriptors tears
 * every object down without loading guest firmware.
 */

#define _GNU_SOURCE

#include <errno.h>
#include <fcntl.h>
#include <getopt.h>
#include <inttypes.h>
#include <linux/ioctl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>

#define GH_IOCTL_TYPE 'G'
#define GH_CREATE_VM _IO(GH_IOCTL_TYPE, 0x0)

enum gh_mem_flags {
	GH_MEM_ALLOW_READ = 1UL << 0,
	GH_MEM_ALLOW_WRITE = 1UL << 1,
	GH_MEM_ALLOW_EXEC = 1UL << 2,
};

struct gh_userspace_memory_region {
	uint32_t label;
	uint32_t flags;
	uint64_t guest_phys_addr;
	uint64_t memory_size;
	uint64_t userspace_addr;
};

#define GH_VM_SET_USER_MEM_REGION \
	_IOW(GH_IOCTL_TYPE, 0x1, struct gh_userspace_memory_region)

enum gh_fn_type {
	GH_FN_VCPU = 1,
};

struct gh_fn_vcpu_arg {
	uint32_t id;
};

struct gh_fn_desc {
	uint32_t type;
	uint32_t arg_size;
	uint64_t arg;
};

#define GH_VM_ADD_FUNCTION _IOW(GH_IOCTL_TYPE, 0x4, struct gh_fn_desc)
#define GH_VCPU_MMAP_SIZE _IO(GH_IOCTL_TYPE, 0x6)

static void usage(FILE *stream, const char *name)
{
	fprintf(stream,
		"Usage: %s [--device PATH] [--manager-only] "
		"[--memory-mib N] [--vcpu ID]\n"
		"\n"
		"Default: create a VM, register 16 MiB at GPA 0x80000000, "
		"create vCPU 0 and map its run page. The VM is never started.\n",
		name);
}

static int fail_errno(const char *operation)
{
	fprintf(stderr, "FAIL %-24s errno=%d (%s)\n", operation, errno,
		strerror(errno));
	return EXIT_FAILURE;
}

int main(int argc, char **argv)
{
	static const struct option options[] = {
		{ "device", required_argument, NULL, 'd' },
		{ "manager-only", no_argument, NULL, 'm' },
		{ "memory-mib", required_argument, NULL, 'r' },
		{ "vcpu", required_argument, NULL, 'c' },
		{ "help", no_argument, NULL, 'h' },
		{ NULL, 0, NULL, 0 },
	};
	const uint64_t guest_phys_addr = UINT64_C(0x80000000);
	const char *device = "/dev/gunyah";
	uint64_t memory_mib = 16;
	uint64_t memory_size;
	uint64_t vcpu_id = 0;
	void *memory = MAP_FAILED;
	void *run_page = MAP_FAILED;
	long run_size;
	int manager_only = 0;
	int manager_fd = -1;
	int vm_fd = -1;
	int vcpu_fd = -1;
	int option;
	int result = EXIT_FAILURE;

	while ((option = getopt_long(argc, argv, "d:mr:c:h", options, NULL)) != -1) {
		char *end = NULL;
		uint64_t value;

		switch (option) {
		case 'd':
			device = optarg;
			break;
		case 'm':
			manager_only = 1;
			break;
		case 'r':
		case 'c':
			errno = 0;
			value = strtoull(optarg, &end, 0);
			if (errno || !end || *end) {
				fprintf(stderr, "invalid numeric argument: %s\n", optarg);
				return EXIT_FAILURE;
			}
			if (option == 'r')
				memory_mib = value;
			else
				vcpu_id = value;
			break;
		case 'h':
			usage(stdout, argv[0]);
			return EXIT_SUCCESS;
		default:
			usage(stderr, argv[0]);
			return EXIT_FAILURE;
		}
	}

	if (optind != argc || memory_mib == 0 || memory_mib > 4096 ||
	    vcpu_id > UINT32_MAX) {
		usage(stderr, argv[0]);
		return EXIT_FAILURE;
	}
	memory_size = memory_mib * UINT64_C(1024) * 1024;

	manager_fd = open(device, O_RDWR | O_CLOEXEC);
	if (manager_fd < 0)
		return fail_errno("open manager");
	printf("PASS %-24s %s fd=%d\n", "open manager", device, manager_fd);

	vm_fd = ioctl(manager_fd, GH_CREATE_VM, 0UL);
	if (vm_fd < 0) {
		fail_errno("GH_CREATE_VM");
		goto out;
	}
	printf("PASS %-24s vmfd=%d\n", "GH_CREATE_VM", vm_fd);

	if (manager_only) {
		result = EXIT_SUCCESS;
		goto out;
	}

	memory = mmap(NULL, memory_size, PROT_READ | PROT_WRITE,
		      MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
	if (memory == MAP_FAILED) {
		fail_errno("mmap guest RAM");
		goto out;
	}
	memset(memory, 0xa5, (size_t)sysconf(_SC_PAGESIZE));

	{
		struct gh_userspace_memory_region region = {
			.label = 0,
			.flags = GH_MEM_ALLOW_READ | GH_MEM_ALLOW_WRITE |
				 GH_MEM_ALLOW_EXEC,
			.guest_phys_addr = guest_phys_addr,
			.memory_size = memory_size,
			.userspace_addr = (uintptr_t)memory,
		};

		if (ioctl(vm_fd, GH_VM_SET_USER_MEM_REGION, &region) < 0) {
			fail_errno("GH_VM_SET_USER_MEM_REGION");
			goto out;
		}
	}
	printf("PASS %-24s gpa=0x%" PRIx64 " size=%" PRIu64 " MiB\n",
	       "register guest RAM", guest_phys_addr, memory_mib);

	{
		struct gh_fn_vcpu_arg vcpu = { .id = (uint32_t)vcpu_id };
		struct gh_fn_desc function = {
			.type = GH_FN_VCPU,
			.arg_size = sizeof(vcpu),
			.arg = (uintptr_t)&vcpu,
		};

		vcpu_fd = ioctl(vm_fd, GH_VM_ADD_FUNCTION, &function);
		if (vcpu_fd < 0) {
			fail_errno("GH_VM_ADD_FUNCTION(vCPU)");
			goto out;
		}
	}
	printf("PASS %-24s id=%" PRIu64 " vcpufd=%d\n", "create vCPU",
	       vcpu_id, vcpu_fd);

	run_size = ioctl(vcpu_fd, GH_VCPU_MMAP_SIZE, 0UL);
	if (run_size <= 0) {
		if (run_size == 0)
			errno = EPROTO;
		fail_errno("GH_VCPU_MMAP_SIZE");
		goto out;
	}
	printf("PASS %-24s bytes=%ld\n", "vCPU run area size", run_size);

	run_page = mmap(NULL, (size_t)run_size, PROT_READ | PROT_WRITE,
			MAP_SHARED, vcpu_fd, 0);
	if (run_page == MAP_FAILED) {
		fail_errno("mmap vCPU run area");
		goto out;
	}
	printf("PASS %-24s address=%p\n", "map vCPU run area", run_page);
	printf("PASS %-24s VM was not started; closing all resources\n",
	       "non-destructive probe");
	result = EXIT_SUCCESS;

out:
	if (run_page != MAP_FAILED)
		munmap(run_page, (size_t)run_size);
	if (vcpu_fd >= 0)
		close(vcpu_fd);
	if (vm_fd >= 0)
		close(vm_fd);
	if (memory != MAP_FAILED)
		munmap(memory, memory_size);
	if (manager_fd >= 0)
		close(manager_fd);
	return result;
}
