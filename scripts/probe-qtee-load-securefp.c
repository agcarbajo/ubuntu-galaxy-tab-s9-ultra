// SPDX-License-Identifier: BSD-3-Clause
// Load Samsung's signed split fingerprint TA without invoking it.

#include <elf.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "tests_private.h"

#define QSEECOM_COMPAT_APP_LOADER_UID UINT32_C(122)
#define QSEECOM_COMPAT_LOOKUP_TA_OP UINT32_C(2)
#define QSEECOM_COMPAT_LOAD_BUFFER_OP UINT32_C(1)
#define FINGERPRINT_TA_BASENAME "fingerpr"
#define FINGERPRINT_TA_NAME "securefp"
#define FINGERPRINT_TA_SEGMENTS 9

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
		      unsigned int segment)
{
	int ret;

	ret = snprintf(path, path_size, "%s/%s.b%02u", directory,
		       FINGERPRINT_TA_BASENAME, segment);
	return ret < 0 || (size_t)ret >= path_size ? -1 : 0;
}

static int assemble_ta(const char *directory, unsigned char **image_out,
		       size_t *image_size_out)
{
	Elf64_Ehdr header;
	Elf64_Phdr phdr[FINGERPRINT_TA_SEGMENTS];
	char path[1024];
	unsigned char *image;
	size_t segment_size[FINGERPRINT_TA_SEGMENTS];
	size_t image_size;
	unsigned int i;

	if (split_path(path, sizeof(path), directory, 0) ||
	    file_size(path, &segment_size[0]) ||
	    segment_size[0] < sizeof(header) + sizeof(phdr)) {
		fprintf(stderr, "FAIL: invalid %s.b00\n", FINGERPRINT_TA_BASENAME);
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
		if (split_path(path, sizeof(path), directory, i) ||
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
		    split_path(path, sizeof(path), directory, i) ||
		    read_at(path, image + offset, segment_size[i])) {
			fprintf(stderr, "FAIL: cannot assemble segment b%02u\n", i);
			free(image);
			return -1;
		}
	}

	*image_out = image;
	*image_size_out = image_size;
	printf("Assembled signed %s TA: %zu bytes.\n",
	       FINGERPRINT_TA_BASENAME, image_size);
	return 0;
}

static int lookup_ta(struct qcomtee_object *app_loader,
		     struct qcomtee_object **controller,
		     qcomtee_result_t *result)
{
	static const char name[] = FINGERPRINT_TA_NAME;
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

int main(int argc, char **argv)
{
	static const char name[] = FINGERPRINT_TA_NAME;
	const char *load_name;
	char dist_name[64] = { 0 };
	struct qcomtee_object *root = QCOMTEE_OBJECT_NULL;
	struct qcomtee_object *client_env = QCOMTEE_OBJECT_NULL;
	struct qcomtee_object *app_loader = QCOMTEE_OBJECT_NULL;
	struct qcomtee_object *controller = QCOMTEE_OBJECT_NULL;
	struct qcomtee_param params[4] = { 0 };
	unsigned char *image = NULL;
	size_t image_size = 0;
	qcomtee_result_t result = QCOMTEE_ERROR;
	int exit_code = 1;

	if (argc < 2 || argc > 3) {
		fprintf(stderr, "usage: %s DIRECTORY_WITH_FINGERPR_SPLITS [LOAD_NAME]\n",
			argv[0]);
		return 64;
	}
	load_name = argc == 3 ? argv[2] : name;
	root = test_get_root();
	if (root == QCOMTEE_OBJECT_NULL)
		goto out;
	client_env = test_get_client_env_object(root);
	if (client_env == QCOMTEE_OBJECT_NULL)
		goto out;
	app_loader = test_get_service_object(client_env,
					     QSEECOM_COMPAT_APP_LOADER_UID);
	if (app_loader == QCOMTEE_OBJECT_NULL)
		goto out;

	if (lookup_ta(app_loader, &controller, &result)) {
		fprintf(stderr, "FAIL: initial lookupTA transport error\n");
		goto out;
	}
	if (result == QCOMTEE_OK && controller != QCOMTEE_OBJECT_NULL) {
		printf("FOUND: %s is already loaded; no load was attempted.\n",
		       name);
		exit_code = 0;
		goto out;
	}
	qcomtee_object_refs_dec(controller);
	controller = QCOMTEE_OBJECT_NULL;
	printf("lookupTA(%s) returned %u; trying the signed stock image.\n",
	       name, result);

	if (assemble_ta(argv[1], &image, &image_size))
		goto out;
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
	if (qcomtee_object_invoke(app_loader, QSEECOM_COMPAT_LOAD_BUFFER_OP,
				  params, 4, &result)) {
		fprintf(stderr, "FAIL: loadFromBuffer transport error\n");
		goto out;
	}
	controller = params[3].object;
	if (result != QCOMTEE_OK || controller == QCOMTEE_OBJECT_NULL) {
		fprintf(stderr, "REJECTED: loadFromBuffer(%s) result %u\n",
			load_name, result);
		exit_code = 2;
		goto out;
	}
	printf("LOADED: QTEE accepted Samsung's signed %s image as %s.\n",
	       FINGERPRINT_TA_BASENAME, load_name);
	printf("No application object or biometric operation was requested.\n");
	if (dist_name[0])
		printf("Distribution name: %s\n", dist_name);
	exit_code = 0;

out:
	free(image);
	qcomtee_object_refs_dec(controller);
	qcomtee_object_refs_dec(app_loader);
	qcomtee_object_refs_dec(client_env);
	qcomtee_object_refs_dec(root);
	return exit_code;
}
