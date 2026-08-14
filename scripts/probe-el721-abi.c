// SPDX-License-Identifier: GPL-2.0-only
/* Read-only smoke test for the restricted EL721 compatibility ABI. */

#define _GNU_SOURCE

#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

#define FP_MODEL_INFO 0x1f

struct egis_ioc_transfer {
	uint64_t tx_buf;
	uint64_t rx_buf;
	uint32_t len;
	uint32_t speed_hz;
	uint16_t delay_usecs;
	uint8_t bits_per_word;
	uint8_t cs_change;
	uint8_t opcode;
	uint8_t pad[3];
};

#define EGIS_IOC_MESSAGE _IOW('k', 0, char[sizeof(struct egis_ioc_transfer)])

int main(void)
{
	struct egis_ioc_transfer transfer = { 0 };
	char model[10] = { 0 };
	int fd;

	fd = open("/dev/esfp0", O_RDWR | O_CLOEXEC);
	if (fd < 0) {
		perror("open /dev/esfp0");
		return 1;
	}

	transfer.rx_buf = (uintptr_t)model;
	transfer.opcode = FP_MODEL_INFO;
	if (ioctl(fd, EGIS_IOC_MESSAGE, &transfer) < 0) {
		perror("FP_MODEL_INFO");
		close(fd);
		return 1;
	}
	if (strcmp(model, "X916") != 0) {
		fprintf(stderr, "unexpected model: %s\n", model);
		close(fd);
		return 1;
	}

	memset(&transfer, 0, sizeof(transfer));
	errno = 0;
	if (ioctl(fd, EGIS_IOC_MESSAGE, &transfer) != -1 ||
	    errno != EOPNOTSUPP) {
		fprintf(stderr, "raw opcode was not rejected: errno=%d\n", errno);
		close(fd);
		return 1;
	}

	printf("EL721 model %s; raw operations rejected\n", model);
	close(fd);
	return 0;
}
