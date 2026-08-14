// SPDX-License-Identifier: BSD-3-Clause
// Enumerate the operations of QTEE's Diagnostics service.
//
// The legacy SIP diagnostic SMC (service 6, command 2) answers "not supported"
// on this firmware, which fits QTEE 5.2 having moved diagnostics behind its
// object interface.  Only operation 0, queryHeapInfo, is documented in the
// quic-teec tests.  This walks the low operation numbers with an output buffer
// and reports what each returns, looking for the secure-world log: the EL721 TA
// records there why its SPI setup fails.
//
// Read-only: it never sends an input payload and never loads or invokes a TA.

#include <ctype.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "tests_private.h"

#define DIAGNOSTICS_UID 143U
#define MAX_OPERATION 31U
#define OUTPUT_SIZE 8192U

static void report_ascii(const unsigned char *buffer, size_t size)
{
	size_t printable = 0;
	size_t run = 0;
	size_t best = 0;
	size_t i;

	for (i = 0; i < size; i++) {
		if (isprint(buffer[i]) || buffer[i] == '\n' || buffer[i] == '\t') {
			printable++;
			run++;
			if (run > best)
				best = run;
		} else {
			run = 0;
		}
	}
	printf("      %zu/%zu printable, longest run %zu\n", printable, size,
	       best);
	if (best >= 8) {
		size_t shown = size < 256 ? size : 256;

		printf("      text: ");
		for (i = 0; i < shown; i++)
			putchar(isprint(buffer[i]) || buffer[i] == '\n' ?
				buffer[i] : '.');
		putchar('\n');
	}
}

static void report_head(const unsigned char *buffer)
{
	size_t i;

	printf("      head:");
	for (i = 0; i < 32; i++)
		printf(" %02x", buffer[i]);
	putchar('\n');
}

int main(void)
{
	struct qcomtee_object *root = QCOMTEE_OBJECT_NULL;
	struct qcomtee_object *client_env = QCOMTEE_OBJECT_NULL;
	struct qcomtee_object *service = QCOMTEE_OBJECT_NULL;
	unsigned char *output;
	unsigned int op;
	int exit_code = 1;

	output = malloc(OUTPUT_SIZE);
	if (!output) {
		fprintf(stderr, "FAIL: cannot allocate output buffer\n");
		return 1;
	}

	root = test_get_root();
	if (root == QCOMTEE_OBJECT_NULL)
		goto out;
	client_env = test_get_client_env_object(root);
	if (client_env == QCOMTEE_OBJECT_NULL)
		goto out;
	service = test_get_service_object(client_env, DIAGNOSTICS_UID);
	if (service == QCOMTEE_OBJECT_NULL) {
		fprintf(stderr, "FAIL: Diagnostics service (UID %u) unavailable\n",
			DIAGNOSTICS_UID);
		goto out;
	}
	printf("Diagnostics service UID %u obtained.\n", DIAGNOSTICS_UID);

	for (op = 0; op <= MAX_OPERATION; op++) {
		struct qcomtee_param params[1] = { 0 };
		qcomtee_result_t result = QCOMTEE_ERROR;

		memset(output, 0, OUTPUT_SIZE);
		params[0].attr = QCOMTEE_UBUF_OUTPUT;
		params[0].ubuf.addr = output;
		params[0].ubuf.size = OUTPUT_SIZE;

		if (qcomtee_object_invoke(service, op, params, 1, &result)) {
			printf("  op %2u: transport error\n", op);
			continue;
		}
		if (result != QCOMTEE_OK) {
			printf("  op %2u: result %u\n", op, result);
			continue;
		}
		printf("  op %2u: OK, %zu bytes returned\n", op,
		       params[0].ubuf.size);
		if (params[0].ubuf.size) {
			report_head(output);
			report_ascii(output, params[0].ubuf.size < OUTPUT_SIZE ?
				     params[0].ubuf.size : OUTPUT_SIZE);
		}
	}
	exit_code = 0;

out:
	qcomtee_object_refs_dec(service);
	qcomtee_object_refs_dec(client_env);
	qcomtee_object_refs_dec(root);
	free(output);
	return exit_code;
}
