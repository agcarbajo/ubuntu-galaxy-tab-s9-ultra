/* SPDX-License-Identifier: MIT
 *
 * libvmmem.so replacement for the SPU daemons running under Ubuntu.
 *
 * Qualcomm's vendor libvmmem talks to the mem_buf driver to share DMA-BUFs
 * between HLOS and the SPSS virtual machine.  Mainline has no mem_buf; on
 * this port the SPSS/HLOS shared region is a static carveout exposed through
 * the qcom,sp-hlos heap, so the daemons' probe through this library only has
 * to succeed and say so.  This file reproduces the behaviour of the
 * hand-built stub validated on 2026-09-01 (exports CreateVmMem, FreeVmMem,
 * FindVmByName and ShareDmabuf; imports only write; no NEEDED entry), as
 * recovered from its disassembly:
 *
 *  - CreateVmMem() returns a token and logs that mem_buf is absent;
 *  - FindVmByName() recognises "qcom,cp_spss_hlos_shared" (VMID 9) and
 *    "qcom,hlos" (VMID 10) for that token, and -1 for anything else;
 *  - ShareDmabuf() accepts a request for exactly two VMs with read/write
 *    permission (3) on a valid fd and reports success without issuing
 *    MEM_BUF_IOC_SHARE; anything else is rejected with -1.
 *
 * Built with -nostdlib so it links against Bionic's libc at run time.
 */
#include <stddef.h>

long write(int fd, const void *buffer, size_t count);

static int vm_token;

static void write_string(const char *text)
{
	size_t length = 0;

	if (!text)
		return;
	while (text[length] && length < 96)
		length++;
	write(2, text, length);
}

static int strings_equal(const char *a, const char *b)
{
	if (!a || !b)
		return 0;
	while (*a && *a == *b) {
		a++;
		b++;
	}
	return *a == *b;
}

void *CreateVmMem(void)
{
	static const char message[] =
		"[vmmem-compat] no mem_buf device; using HLOS/SPSS static-access probe\n";

	write(2, message, sizeof message - 1);
	return &vm_token;
}

void FreeVmMem(void *handle)
{
	(void)handle;
}

int FindVmByName(void *handle, const char *name)
{
	static const char prefix[] = "[vmmem-compat] vm=";
	static const char newline[] = "\n";

	if (handle != &vm_token)
		return -1;
	write(2, prefix, sizeof prefix - 1);
	write_string(name);
	write(2, newline, 1);
	if (strings_equal(name, "qcom,cp_spss_hlos_shared"))
		return 9;
	if (strings_equal(name, "qcom,hlos"))
		return 10;
	return -1;
}

int ShareDmabuf(void *handle, int fd, const int *vmids, const int *permissions,
		size_t count)
{
	static const char success[] =
		"[vmmem-compat] bypassing unavailable MEM_BUF_IOC_SHARE for probe\n";
	static const char failure[] = "[vmmem-compat] invalid share request\n";

	if (handle == &vm_token && fd >= 0 && vmids && permissions && count == 2 &&
	    permissions[0] == 3 && permissions[1] == 3) {
		write(2, success, sizeof success - 1);
		return 0;
	}
	write(2, failure, sizeof failure - 1);
	return -1;
}
