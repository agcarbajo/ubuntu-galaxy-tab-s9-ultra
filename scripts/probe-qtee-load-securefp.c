// SPDX-License-Identifier: BSD-3-Clause
// Load Samsung's signed split fingerprint TA and run a bounded diagnostic.

#define _GNU_SOURCE

#include <elf.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "tests_private.h"
#include "qtee-client-identity.h"

#define QSEECOM_COMPAT_APP_LOADER_UID UINT32_C(122)
#define QSEECOM_COMPAT_LOOKUP_TA_OP UINT32_C(2)
#define QSEECOM_COMPAT_LOAD_REGION_OP UINT32_C(0)
#define QSEECOM_COMPAT_LOAD_BUFFER_OP UINT32_C(1)
#define QSEECOM_COMPAT_SEND_REQUEST_OP UINT32_C(0)
#define QSEECOM_COMPAT_UNLOAD_OP UINT32_C(2)
#define FINGERPRINT_TA_NAME "securefp"
#define FINGERPRINT_TA_SEGMENTS 9
#define MAX_DIST_NAME_SIZE 4096U
#define DUALFP_TYPE_CHECK_COMMAND UINT32_C(16)
#define DUALFP_PREPARE_COMMAND UINT32_C(1)
#define DUALFP_MESSAGE_SIZE 64U
/*
 * Samsung's gateway declares an 8-byte payload, but the TA does not take that
 * length at face value: before dispatching any command it re-registers each
 * embedded pointer as a shared buffer of exactly 0x2a4000 bytes, and answers 29
 * for the whole request if that registration fails.  The stock host gets away
 * with declaring 8 because its dmabuf allocations are far larger.  Both buffers
 * must therefore be backed by at least this much memory.
 */
#define DUALFP_SHARED_BUFFER_SIZE 0x2a4000U
#define DUALFP_TYPE_CHECK_PAYLOAD 8U
#define DUALFP_PREPARE_WIRE_SIZE 0x80010U
#define DUALFP_PREPARE_DATA_OFFSET 12U
#define DUALFP_PREPARE_LENGTH_OFFSET 0x8000cU
#define DUALFP_PREPARE_NO_CALIBRATION UINT32_C(2)
#define DUALFP_OUTPUT_POISON 0xa5
#define QCOMTEE_MAX_INBOUND_BUFFER_SIZE (4U * 1024U * 1024U)
#define EL721_SENSOR_NAME UINT32_C(21)
#define EL721_SENSOR_TYPE UINT32_C(8)

static void store_u32(unsigned char *buffer, size_t offset, uint32_t value)
{
	memcpy(buffer + offset, &value, sizeof(value));
}

static uint32_t load_u32(const unsigned char *buffer, size_t offset)
{
	uint32_t value;

	memcpy(&value, buffer + offset, sizeof(value));
	return value;
}

static int read_at(const char *path, void *buffer, size_t size)
{
	FILE *file;
	size_t done;

	file = fopen(path, "rb");
	if (!file) {
		fprintf(stderr, "FAIL: cannot open %s: %s\n", path,
			strerror(errno));
		return -1;
	}
	done = fread(buffer, 1, size, file);
	if (done != size) {
		fprintf(stderr, "FAIL: short read from %s\n", path);
		fclose(file);
		return -1;
	}
	if (fclose(file)) {
		fprintf(stderr, "FAIL: cannot close %s: %s\n", path,
			strerror(errno));
		return -1;
	}
	return 0;
}

static int file_size(const char *path, size_t *size)
{
	FILE *file;
	long end;

	file = fopen(path, "rb");
	if (!file)
		return -1;
	if (fseek(file, 0, SEEK_END)) {
		fclose(file);
		return -1;
	}
	end = ftell(file);
	fclose(file);
	if (end < 0)
		return -1;
	*size = (size_t)end;
	return 0;
}

static int split_path(char *path, size_t path_size, const char *directory,
		      const char *basename, unsigned int segment)
{
	int ret;

	ret = snprintf(path, path_size, "%s/%s.b%02u", directory,
		       basename, segment);
	return ret < 0 || (size_t)ret >= path_size ? -1 : 0;
}

static int assemble_ta(const char *directory, const char *basename,
		       unsigned char **image_out, size_t *image_size_out)
{
	Elf64_Ehdr header;
	Elf64_Phdr phdr[FINGERPRINT_TA_SEGMENTS];
	char path[1024];
	unsigned char *image;
	size_t segment_size[FINGERPRINT_TA_SEGMENTS];
	size_t image_size;
	unsigned int i;

	if (split_path(path, sizeof(path), directory, basename, 0) ||
	    file_size(path, &segment_size[0]) ||
	    segment_size[0] < sizeof(header) + sizeof(phdr)) {
		fprintf(stderr, "FAIL: invalid %s.b00\n", basename);
		return -1;
	}
	if (read_at(path, &header, sizeof(header)))
		return -1;
	if (memcmp(header.e_ident, ELFMAG, SELFMAG) ||
	    header.e_ident[EI_CLASS] != ELFCLASS64 ||
	    header.e_machine != EM_AARCH64 ||
	    header.e_phnum != FINGERPRINT_TA_SEGMENTS ||
	    header.e_phentsize != sizeof(Elf64_Phdr) ||
	    header.e_phoff != sizeof(Elf64_Ehdr)) {
		fprintf(stderr, "FAIL: unexpected signed TA ELF layout\n");
		return -1;
	}

	{
		FILE *file = fopen(path, "rb");

		if (!file || fseek(file, (long)header.e_phoff, SEEK_SET) ||
		    fread(phdr, sizeof(phdr), 1, file) != 1) {
			if (file)
				fclose(file);
			fprintf(stderr, "FAIL: cannot read TA program headers\n");
			return -1;
		}
		fclose(file);
	}

	for (i = 1; i < FINGERPRINT_TA_SEGMENTS; i++) {
		if (split_path(path, sizeof(path), directory, basename, i) ||
		    file_size(path, &segment_size[i])) {
			fprintf(stderr, "FAIL: missing split TA segment b%02u\n", i);
			return -1;
		}
		if (phdr[i].p_offset > SIZE_MAX - segment_size[i]) {
			fprintf(stderr, "FAIL: split TA size overflow\n");
			return -1;
		}
	}
	image_size = phdr[FINGERPRINT_TA_SEGMENTS - 1].p_offset +
		segment_size[FINGERPRINT_TA_SEGMENTS - 1];
	if (image_size < segment_size[0] || image_size > 32 * 1024 * 1024) {
		fprintf(stderr, "FAIL: implausible assembled TA size %zu\n",
			image_size);
		return -1;
	}

	image = calloc(1, image_size);
	if (!image) {
		fprintf(stderr, "FAIL: cannot allocate %zu-byte TA buffer\n",
			image_size);
		return -1;
	}
	for (i = 0; i < FINGERPRINT_TA_SEGMENTS; i++) {
		size_t offset = i ? phdr[i].p_offset : 0;

		if (offset > image_size || segment_size[i] > image_size - offset ||
		    split_path(path, sizeof(path), directory, basename, i) ||
		    read_at(path, image + offset, segment_size[i])) {
			fprintf(stderr, "FAIL: cannot assemble segment b%02u\n", i);
			free(image);
			return -1;
		}
	}

	*image_out = image;
	*image_size_out = image_size;
	printf("Assembled signed %s TA: %zu bytes.\n",
	       basename, image_size);
	return 0;
}

static int lookup_ta(struct qcomtee_object *app_loader, const char *name,
		     struct qcomtee_object **controller,
		     qcomtee_result_t *result)
{
	struct qcomtee_param params[2] = { 0 };

	params[0].attr = QCOMTEE_UBUF_INPUT;
	params[0].ubuf.addr = (void *)name;
	params[0].ubuf.size = strlen(name);
	params[1].attr = QCOMTEE_OBJREF_OUTPUT;
	if (qcomtee_object_invoke(app_loader, QSEECOM_COMPAT_LOOKUP_TA_OP,
				  params, 2, result))
		return -1;
	*controller = params[1].object;
	return 0;
}

static void report_dist_output(const unsigned char *buffer, size_t size)
{
	size_t first = size;
	size_t last = 0;
	size_t i;

	for (i = 0; i < size; i++) {
		if (!buffer[i])
			continue;
		if (first == size)
			first = i;
		last = i;
	}
	if (first == size) {
		fprintf(stderr, "Distribution output is all zero.\n");
		return;
	}
	fprintf(stderr,
		"Distribution output has nonzero bytes at offsets %zu..%zu:",
		first, last);
	for (i = first; i <= last && i < first + 64; i++)
		fprintf(stderr, " %02x", buffer[i]);
	fputc('\n', stderr);
}

static void dump_envelope(const char *label, const unsigned char *buffer)
{
	size_t i;

	printf("  %-8s", label);
	for (i = 0; i < DUALFP_MESSAGE_SIZE; i++) {
		if (i && !(i % 16))
			printf("\n          ");
		printf(" %02x", buffer[i]);
	}
	putchar('\n');
}

static int type_check_ta(struct qcomtee_object *controller,
			 struct qcomtee_object *root, uint32_t sensor_name)
{
	struct qcomtee_object *input = QCOMTEE_OBJECT_NULL;
	struct qcomtee_object *output = QCOMTEE_OBJECT_NULL;
	struct qcomtee_param params[10] = { 0 };
	unsigned char request[DUALFP_MESSAGE_SIZE] = { 0 };
	unsigned char response[DUALFP_MESSAGE_SIZE] = { 0 };
	unsigned char request_out[DUALFP_MESSAGE_SIZE] = { 0 };
	unsigned char response_out[DUALFP_MESSAGE_SIZE] = { 0 };
	uint32_t embedded_offsets[] = { 4, 16 };
	size_t i;
	uint32_t is_64_bit = 1;
	unsigned char *input_data;
	unsigned char *output_data;
	uint32_t trustlet_result;
	uint32_t payload_result;
	qcomtee_result_t result = QCOMTEE_ERROR;
	int ret = -1;

	if (qcomtee_memory_object_alloc(DUALFP_SHARED_BUFFER_SIZE, root,
					&input) ||
	    qcomtee_memory_object_alloc(DUALFP_SHARED_BUFFER_SIZE, root,
					&output)) {
		fprintf(stderr, "FAIL: could not allocate TypeCheck buffers\n");
		goto out;
	}
	input_data = qcomtee_memory_object_addr(input);
	output_data = qcomtee_memory_object_addr(output);
	memset(input_data, 0, DUALFP_SHARED_BUFFER_SIZE);
	/*
	 * Poison rather than zero the output: a zeroed result and an untouched
	 * buffer are indistinguishable otherwise, and "sensor type 0" is exactly
	 * what an unwritten buffer looks like.
	 */
	memset(output_data, DUALFP_OUTPUT_POISON, DUALFP_SHARED_BUFFER_SIZE);

	/* Reconstructed from BAuth_Type_Check in Samsung's arm64 gateway. */
	store_u32(request, 0, DUALFP_TYPE_CHECK_COMMAND);
	store_u32(request, 12, DUALFP_TYPE_CHECK_PAYLOAD);
	store_u32(request, 24, DUALFP_TYPE_CHECK_PAYLOAD);
	store_u32(input_data, 0, DUALFP_TYPE_CHECK_COMMAND);
	/* SensorInfo maps the stock model string "EL721" to sensor-name enum 21. */
	store_u32(input_data, 4, sensor_name);

	params[0].attr = QCOMTEE_UBUF_INPUT;
	params[0].ubuf.addr = request;
	params[0].ubuf.size = sizeof(request);
	params[1].attr = QCOMTEE_UBUF_INPUT;
	params[1].ubuf.addr = response;
	params[1].ubuf.size = sizeof(response);
	params[2].attr = QCOMTEE_UBUF_INPUT;
	params[2].ubuf.addr = embedded_offsets;
	params[2].ubuf.size = sizeof(embedded_offsets);
	params[3].attr = QCOMTEE_UBUF_INPUT;
	params[3].ubuf.addr = &is_64_bit;
	params[3].ubuf.size = sizeof(is_64_bit);
	params[4].attr = QCOMTEE_UBUF_OUTPUT;
	params[4].ubuf.addr = request_out;
	params[4].ubuf.size = sizeof(request_out);
	params[5].attr = QCOMTEE_UBUF_OUTPUT;
	params[5].ubuf.addr = response_out;
	params[5].ubuf.size = sizeof(response_out);
	params[6].attr = QCOMTEE_OBJREF_INPUT;
	params[6].object = input;
	params[7].attr = QCOMTEE_OBJREF_INPUT;
	params[7].object = output;
	params[8].attr = QCOMTEE_OBJREF_INPUT;
	params[8].object = QCOMTEE_OBJECT_NULL;
	params[9].attr = QCOMTEE_OBJREF_INPUT;
	params[9].object = QCOMTEE_OBJECT_NULL;

	if (qcomtee_object_invoke(controller,
				  QSEECOM_COMPAT_SEND_REQUEST_OP,
				  params, 10, &result)) {
		fprintf(stderr, "FAIL: TypeCheck transport error\n");
		goto out;
	}
	/*
	 * The returned request shows whether QTEE patched the embedded buffer
	 * pointers into offsets 4 and 16.  If they come back zero the TA was
	 * handed null buffers, which it rejects regardless of the payload.
	 */
	dump_envelope("request", request_out);
	dump_envelope("response", response_out);
	printf("  out[0..15] ");
	for (i = 0; i < 16; i++)
		printf(" %02x", output_data[i]);
	putchar('\n');
	trustlet_result = load_u32(response_out, 4);
	payload_result = load_u32(output_data, 0);
	printf("TypeCheck name=%u: invoke result %u; trustlet=%u, payload=%u, sensor=%u.\n",
	       sensor_name, result, trustlet_result, payload_result,
	       load_u32(output_data, 4));
	ret = result == QCOMTEE_OK && !trustlet_result && !payload_result ? 0 : -1;

out:
	qcomtee_memory_object_release(output);
	qcomtee_memory_object_release(input);
	return ret;
}

/*
 * Reproduce the first real trusted-sensor operation from a One UI 8 service
 * restart.  Once the driver has cached EL721 as sensor type 8, stock skips
 * TypeCheck; after opening dualfp it sends Prepare (command 1).
 * With no saved Ubuntu calibration, Samsung's host selects mode 2 and supplies
 * no input blob.  This operation initializes the sensor but cannot enrol,
 * identify, capture an image or access a template.
 */
static int prepare_ta(struct qcomtee_object *controller,
		      struct qcomtee_object *root)
{
	struct qcomtee_object *input = QCOMTEE_OBJECT_NULL;
	struct qcomtee_object *output = QCOMTEE_OBJECT_NULL;
	struct qcomtee_param params[10] = { 0 };
	unsigned char request[DUALFP_MESSAGE_SIZE] = { 0 };
	unsigned char response[DUALFP_MESSAGE_SIZE] = { 0 };
	unsigned char request_out[DUALFP_MESSAGE_SIZE] = { 0 };
	unsigned char response_out[DUALFP_MESSAGE_SIZE] = { 0 };
	uint32_t embedded_offsets[] = { 4, 16 };
	uint32_t is_64_bit = 1;
	unsigned char *input_data;
	unsigned char *output_data;
	uint32_t trustlet_result;
	uint32_t payload_result;
	uint32_t sensor_type;
	uint32_t function_status;
	uint32_t output_length;
	qcomtee_result_t result = QCOMTEE_ERROR;
	int ret = -1;

	if (qcomtee_memory_object_alloc(DUALFP_SHARED_BUFFER_SIZE, root,
					&input) ||
	    qcomtee_memory_object_alloc(DUALFP_SHARED_BUFFER_SIZE, root,
					&output)) {
		fprintf(stderr, "FAIL: could not allocate Prepare buffers\n");
		goto out;
	}
	input_data = qcomtee_memory_object_addr(input);
	output_data = qcomtee_memory_object_addr(output);
	memset(input_data, 0, DUALFP_SHARED_BUFFER_SIZE);
	memset(output_data, 0, DUALFP_SHARED_BUFFER_SIZE);

	/* Exact BAuth_Prepare wire layout reconstructed from One UI 8. */
	store_u32(request, 0, DUALFP_PREPARE_COMMAND);
	store_u32(request, 12, DUALFP_PREPARE_WIRE_SIZE);
	store_u32(request, 24, DUALFP_PREPARE_WIRE_SIZE);
	store_u32(input_data, 0, DUALFP_PREPARE_COMMAND);
	store_u32(input_data, 8, DUALFP_PREPARE_NO_CALIBRATION);
	store_u32(input_data, DUALFP_PREPARE_LENGTH_OFFSET, 0);

	params[0].attr = QCOMTEE_UBUF_INPUT;
	params[0].ubuf.addr = request;
	params[0].ubuf.size = sizeof(request);
	params[1].attr = QCOMTEE_UBUF_INPUT;
	params[1].ubuf.addr = response;
	params[1].ubuf.size = sizeof(response);
	params[2].attr = QCOMTEE_UBUF_INPUT;
	params[2].ubuf.addr = embedded_offsets;
	params[2].ubuf.size = sizeof(embedded_offsets);
	params[3].attr = QCOMTEE_UBUF_INPUT;
	params[3].ubuf.addr = &is_64_bit;
	params[3].ubuf.size = sizeof(is_64_bit);
	params[4].attr = QCOMTEE_UBUF_OUTPUT;
	params[4].ubuf.addr = request_out;
	params[4].ubuf.size = sizeof(request_out);
	params[5].attr = QCOMTEE_UBUF_OUTPUT;
	params[5].ubuf.addr = response_out;
	params[5].ubuf.size = sizeof(response_out);
	params[6].attr = QCOMTEE_OBJREF_INPUT;
	params[6].object = input;
	params[7].attr = QCOMTEE_OBJREF_INPUT;
	params[7].object = output;
	params[8].attr = QCOMTEE_OBJREF_INPUT;
	params[8].object = QCOMTEE_OBJECT_NULL;
	params[9].attr = QCOMTEE_OBJREF_INPUT;
	params[9].object = QCOMTEE_OBJECT_NULL;

	if (qcomtee_object_invoke(controller,
				  QSEECOM_COMPAT_SEND_REQUEST_OP,
				  params, 10, &result)) {
		fprintf(stderr, "FAIL: Prepare transport error\n");
		goto out;
	}

	trustlet_result = load_u32(response_out, 4);
	payload_result = load_u32(output_data, 4);
	sensor_type = load_u32(output_data, 0);
	function_status = load_u32(output_data, 8);
	output_length = load_u32(output_data, DUALFP_PREPARE_LENGTH_OFFSET);
	if (output_length > DUALFP_PREPARE_LENGTH_OFFSET -
			    DUALFP_PREPARE_DATA_OFFSET) {
		fprintf(stderr, "FAIL: Prepare returned invalid output length %u\n",
			output_length);
		goto out;
	}
	printf("Prepare: invoke result %u; trustlet=%u, payload=%u, sensor_type=%u, function_status=%u, calibration_bytes=%u.\n",
	       result, trustlet_result, payload_result,
	       sensor_type, function_status,
	       output_length);
	ret = result == QCOMTEE_OK && !trustlet_result && !payload_result &&
	      sensor_type == EL721_SENSOR_TYPE && !function_status ? 0 : -1;
	if (ret)
		fprintf(stderr, "FAIL: Prepare did not initialise EL721 type %u\n",
			EL721_SENSOR_TYPE);

out:
	qcomtee_memory_object_release(output);
	qcomtee_memory_object_release(input);
	return ret;
}

/*
 * Accepts "--type-check", "--type-check=N" and "--type-check=FIRST-LAST".  The
 * range form asks the same question for a run of sensor-name enums inside one
 * load, because loading the 19 MB image is what costs time, not the query.
 */
static int parse_type_check(const char *argument, uint32_t *first,
			    uint32_t *last)
{
	unsigned long low;
	unsigned long high;
	const char *value;
	char *end;

	if (strncmp(argument, "--type-check", 12))
		return -1;
	value = argument + 12;
	if (!*value)
		return 0;
	if (*value != '=')
		return -1;

	value++;
	errno = 0;
	low = strtoul(value, &end, 10);
	if (errno || end == value || low > UINT32_MAX)
		return -1;
	high = low;
	if (*end == '-') {
		value = end + 1;
		errno = 0;
		high = strtoul(value, &end, 10);
		if (errno || end == value || high > UINT32_MAX || high < low)
			return -1;
	}
	if (*end)
		return -1;

	*first = (uint32_t)low;
	*last = (uint32_t)high;
	return 0;
}

int main(int argc, char **argv)
{
	static const char name[] = FINGERPRINT_TA_NAME;
	const char *basename;
	const char *load_name;
	char dist_name[MAX_DIST_NAME_SIZE] = { 0 };
	struct qcomtee_object *root = QCOMTEE_OBJECT_NULL;
	struct qcomtee_object *client_env = QCOMTEE_OBJECT_NULL;
	struct qcomtee_object *app_loader = QCOMTEE_OBJECT_NULL;
	struct qcomtee_object *controller = QCOMTEE_OBJECT_NULL;
	struct qcomtee_object *memory_object = QCOMTEE_OBJECT_NULL;
	struct qcomtee_param params[4] = { 0 };
	unsigned char *image = NULL;
	size_t image_size = 0;
	qcomtee_result_t result = QCOMTEE_ERROR;
	const char *load_method = "loadFromBuffer";
	int loaded_here = 0;
	uint32_t name_first = EL721_SENSOR_NAME;
	uint32_t name_last = EL721_SENSOR_NAME;
	uint32_t sensor_name;
	uid_t client_uid = 0;
	int use_client_uid = 0;
	int use_kernel_client_env = 0;
	int run_type_check = 0;
	int run_prepare = 0;
	int i;
	int exit_code = 1;

	if (argc < 4 || argc > 6)
		goto usage;
	for (i = 4; i < argc; i++) {
		if (!strncmp(argv[i], "--type-check", 12)) {
			if (run_type_check || run_prepare ||
			    parse_type_check(argv[i], &name_first, &name_last))
				goto usage;
			run_type_check = 1;
		} else if (!strcmp(argv[i], "--prepare")) {
			if (run_prepare || run_type_check)
				goto usage;
			run_prepare = 1;
		} else if (!strncmp(argv[i], "--client-uid=", 13)) {
			if (use_client_uid || use_kernel_client_env ||
			    qtee_parse_client_uid(argv[i], &client_uid))
				goto usage;
			use_client_uid = 1;
		} else if (!strcmp(argv[i], "--kernel-client-env")) {
			if (use_kernel_client_env || use_client_uid)
				goto usage;
			use_kernel_client_env = 1;
		} else {
			goto usage;
		}
	}
	basename = argv[2];
	load_name = argv[3];
	/* Read the signed image before an optional irreversible UID drop. */
	if (assemble_ta(argv[1], basename, &image, &image_size))
		goto out;
	root = test_get_root();
	if (root == QCOMTEE_OBJECT_NULL)
		goto out;
	if (use_client_uid && qtee_drop_client_identity(client_uid))
		goto out;
	client_env = use_kernel_client_env ?
		qtee_get_kernel_compat_client_env(root) :
		test_get_client_env_object(root);
	if (client_env == QCOMTEE_OBJECT_NULL)
		goto out;
	app_loader = test_get_service_object(client_env,
					     QSEECOM_COMPAT_APP_LOADER_UID);
	if (app_loader == QCOMTEE_OBJECT_NULL)
		goto out;

	if (lookup_ta(app_loader, name, &controller, &result)) {
		fprintf(stderr, "FAIL: initial lookupTA transport error\n");
		goto out;
	}
	if (result == QCOMTEE_OK && controller != QCOMTEE_OBJECT_NULL) {
		printf("FOUND: %s is already loaded; no load was attempted.\n",
		       name);
		exit_code = 0;
		for (sensor_name = name_first; run_type_check; sensor_name++) {
			if (type_check_ta(controller, root, sensor_name))
				exit_code = 1;
			if (sensor_name == name_last)
				break;
		}
		if (run_prepare && prepare_ta(controller, root))
			exit_code = 1;
		goto out;
	}
	qcomtee_object_refs_dec(controller);
	controller = QCOMTEE_OBJECT_NULL;
	printf("lookupTA(%s) returned %u; trying the signed stock image.\n",
	       name, result);

	if (image_size > QCOMTEE_MAX_INBOUND_BUFFER_SIZE) {
		load_method = "loadFromRegion";
		if (qcomtee_memory_object_alloc(image_size, root,
						&memory_object)) {
			fprintf(stderr,
				"FAIL: could not allocate %zu-byte TEE memory object\n",
				image_size);
			goto out;
		}
		memcpy(qcomtee_memory_object_addr(memory_object), image,
		       image_size);
		params[0].attr = QCOMTEE_UBUF_INPUT;
		params[0].ubuf.addr = (void *)load_name;
		params[0].ubuf.size = strlen(load_name);
		params[1].attr = QCOMTEE_OBJREF_INPUT;
		params[1].object = memory_object;
		params[2].attr = QCOMTEE_OBJREF_OUTPUT;
		if (qcomtee_object_invoke(app_loader,
					  QSEECOM_COMPAT_LOAD_REGION_OP,
					  params, 3, &result)) {
			fprintf(stderr, "FAIL: loadFromRegion transport error\n");
			goto out;
		}
		controller = params[2].object;
	} else {
		params[0].attr = QCOMTEE_UBUF_INPUT;
		params[0].ubuf.addr = image;
		params[0].ubuf.size = image_size;
		params[1].attr = QCOMTEE_UBUF_INPUT;
		params[1].ubuf.addr = (void *)load_name;
		params[1].ubuf.size = strlen(load_name);
		params[2].attr = QCOMTEE_UBUF_OUTPUT;
		params[2].ubuf.addr = dist_name;
		params[2].ubuf.size = sizeof(dist_name);
		params[3].attr = QCOMTEE_OBJREF_OUTPUT;
		if (qcomtee_object_invoke(app_loader,
					  QSEECOM_COMPAT_LOAD_BUFFER_OP,
					  params, 4, &result)) {
			fprintf(stderr, "FAIL: loadFromBuffer transport error\n");
			goto out;
		}
		controller = params[3].object;
	}
	if (result != QCOMTEE_OK || controller == QCOMTEE_OBJECT_NULL) {
		fprintf(stderr, "REJECTED: %s(%s) result %u\n",
			load_method, load_name, result);
		if (!strcmp(load_method, "loadFromBuffer")) {
			fprintf(stderr, "Distribution output: %zu bytes\n",
				params[2].ubuf.size);
			report_dist_output((const unsigned char *)dist_name,
					   sizeof(dist_name));
		}
		exit_code = 2;
		goto out;
	}
	printf("LOADED: QTEE accepted Samsung's signed %s image as %s.\n",
	       basename, load_name);
	if (!run_type_check && !run_prepare)
		printf("No biometric operation was requested.\n");
	{
		static const char *const lookup_names[] = {
			FINGERPRINT_TA_NAME,
			"dualfp",
		};
		size_t lookup_index;

		for (lookup_index = 0;
		     lookup_index < sizeof(lookup_names) / sizeof(lookup_names[0]);
		     lookup_index++) {
			struct qcomtee_object *found = QCOMTEE_OBJECT_NULL;
			qcomtee_result_t lookup_result = QCOMTEE_ERROR;

			if (lookup_ta(app_loader, lookup_names[lookup_index], &found,
				      &lookup_result)) {
				fprintf(stderr, "WARN: lookupTA(%s) transport error\n",
					lookup_names[lookup_index]);
			} else {
				printf("lookupTA(%s) after load returned %u (%s).\n",
				       lookup_names[lookup_index], lookup_result,
				       found == QCOMTEE_OBJECT_NULL ? "no object" :
				       "controller object");
			}
			qcomtee_object_refs_dec(found);
		}
	}
	if (dist_name[0])
		printf("Distribution name: %s\n", dist_name);
	loaded_here = 1;
	exit_code = 0;
	for (sensor_name = name_first; run_type_check; sensor_name++) {
		if (type_check_ta(controller, root, sensor_name))
			exit_code = 1;
		if (sensor_name == name_last)
			break;
	}
	if (run_prepare && prepare_ta(controller, root))
		exit_code = 1;
	goto out;

usage:
	fprintf(stderr,
		"usage: %s SPLIT_DIRECTORY BASENAME LOAD_NAME [--type-check[=FIRST[-LAST]] | --prepare] [--client-uid=UID | --kernel-client-env]\n",
		argv[0]);
	return 64;

out:
	if (loaded_here && controller != QCOMTEE_OBJECT_NULL) {
		qcomtee_result_t unload_result = QCOMTEE_ERROR;

		if (qcomtee_object_invoke(controller,
					  QSEECOM_COMPAT_UNLOAD_OP,
					  NULL, 0, &unload_result) ||
		    unload_result != QCOMTEE_OK) {
			fprintf(stderr, "WARN: unload(%s) result %d\n",
				load_name, unload_result);
			exit_code = 1;
		} else {
			printf("UNLOADED: %s; session closed cleanly.\n",
			       load_name);
		}
	}
	free(image);
	qcomtee_memory_object_release(memory_object);
	qcomtee_object_refs_dec(controller);
	qcomtee_object_refs_dec(app_loader);
	qcomtee_object_refs_dec(client_env);
	qcomtee_object_refs_dec(root);
	return exit_code;
}
