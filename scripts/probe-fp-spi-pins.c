// SPDX-License-Identifier: GPL-2.0-only
// Sample four TLMM lines at high rate through the GPIO character device.
//
// Written to watch the fingerprint SPI while TrustZone runs, but it cannot see
// that bus, and the distinction matters: the TA names its pads qup1_se2_l0..l3,
// and qup1_se2 is gpio36..gpio39, not gpio64..gpio67.  (gpio64..67 are
// qup2_se2; the numbering is the same in the stock tree and in mainline, where
// gpio26 is qup1_se7 in both.)  Those real pads sit inside the reserved range
// this port and the stock tree both keep away from Linux precisely because
// TrustZone owns them, so the kernel does not expose them at all and no
// userspace sampler can reach them.
//
// It is kept as a general sampler — /dev/mem is refused by this kernel and a
// shell loop over debugfs is orders of magnitude too slow for a SPI transfer —
// with the first line selectable so it is not silently pointed at the wrong
// pads again.
//
// Read-only: the lines are requested as inputs and never driven.

#include <errno.h>
#include <fcntl.h>
#include <linux/gpio.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>

#define DEFAULT_FIRST_LINE 36U
#define LINE_COUNT 4U

static const char *const pad_name[LINE_COUNT] = { "l0", "l1", "l2", "l3" };

static unsigned int first_line = DEFAULT_FIRST_LINE;

static double now_seconds(void)
{
	struct timespec ts;

	clock_gettime(CLOCK_MONOTONIC, &ts);
	return (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;
}

int main(int argc, char **argv)
{
	struct gpio_v2_line_request request = { 0 };
	struct gpio_v2_line_values values = { 0 };
	unsigned long counts[1U << LINE_COUNT] = { 0 };
	double first[1U << LINE_COUNT] = { 0 };
	unsigned long samples = 0;
	const char *chip;
	double seconds;
	double start;
	unsigned int i;
	int fd;

	chip = argc > 1 ? argv[1] : "/dev/gpiochip3";
	seconds = argc > 2 ? atof(argv[2]) : 20.0;
	if (argc > 3)
		first_line = (unsigned int)strtoul(argv[3], NULL, 0);
	if (seconds <= 0 || seconds > 600) {
		fprintf(stderr, "usage: %s [GPIOCHIP [SECONDS [FIRST_LINE]]]\n",
			argv[0]);
		return 64;
	}

	fd = open(chip, O_RDONLY | O_CLOEXEC);
	if (fd < 0) {
		fprintf(stderr, "open %s: %s\n", chip, strerror(errno));
		return 1;
	}

	for (i = 0; i < LINE_COUNT; i++)
		request.offsets[i] = first_line + i;
	request.num_lines = LINE_COUNT;
	request.config.flags = GPIO_V2_LINE_FLAG_INPUT;
	strncpy(request.consumer, "gts9u-fp-spi-watch",
		sizeof(request.consumer) - 1);
	if (ioctl(fd, GPIO_V2_GET_LINE_IOCTL, &request) < 0) {
		fprintf(stderr, "requesting gpio%u..%u: %s\n", first_line,
			first_line + LINE_COUNT - 1, strerror(errno));
		close(fd);
		return 1;
	}
	close(fd);

	values.mask = (1U << LINE_COUNT) - 1;
	start = now_seconds();
	while (now_seconds() - start < seconds) {
		if (ioctl(request.fd, GPIO_V2_LINE_GET_VALUES_IOCTL,
			  &values) < 0) {
			fprintf(stderr, "reading values: %s\n",
				strerror(errno));
			close(request.fd);
			return 1;
		}
		if (!counts[values.bits & 0xf])
			first[values.bits & 0xf] = now_seconds() - start;
		counts[values.bits & 0xf]++;
		samples++;
	}
	close(request.fd);

	printf("sampled %lu times over %.1f s\n", samples, seconds);
	for (i = 0; i < (1U << LINE_COUNT); i++) {
		unsigned int bit;

		if (!counts[i])
			continue;
		printf("  ");
		for (bit = 0; bit < LINE_COUNT; bit++)
			printf("%s=%u ", pad_name[bit], !!(i & (1U << bit)));
		printf(" seen %lu times, first at %.3f s\n", counts[i],
		       first[i]);
	}
	return 0;
}
