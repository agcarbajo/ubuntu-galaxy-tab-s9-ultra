// SPDX-License-Identifier: BSD-3-Clause
// Load and unload one signed QSEECom-compatible TA without invoking it.

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
#define QSEECOM_COMPAT_LOAD_BUFFER_OP UINT32_C(1)
#define QSEECOM_COMPAT_LOOKUP_TA_OP UINT32_C(2)
#define QSEECOM_COMPAT_UNLOAD_OP UINT32_C(2)
#define MAX_TA_SIZE (32U * 1024U * 1024U)
#define MAX_DIST_NAME_SIZE 4096U

static int read_image(const char *path, unsigned char **image_out,
		      size_t *size_out)
{
	Elf64_Ehdr header;
	unsigned char *image;
	FILE *file;
	long end;

	file = fopen(path, "rb");
	if (!file) {
		fprintf(stderr, "FAIL: cannot open %s: %s\n", path,
			strerror(errno));
		return -1;
	}
	if (fseek(file, 0, SEEK_END) || (end = ftell(file)) < 0 ||
	    (size_t)end < sizeof(header) || (size_t)end > MAX_TA_SIZE ||
	    fseek(file, 0, SEEK_SET)) {
		fprintf(stderr, "FAIL: invalid TA size\n");
		fclose(file);
		return -1;
	}
	image = malloc((size_t)end);
	if (!image || fread(image, 1, (size_t)end, file) != (size_t)end) {
		fprintf(stderr, "FAIL: cannot read TA image\n");
		free(image);
		fclose(file);
		return -1;
	}
	fclose(file);
	memcpy(&header, image, sizeof(header));
	if (memcmp(header.e_ident, ELFMAG, SELFMAG) ||
	    header.e_ident[EI_CLASS] != ELFCLASS64 ||
	    header.e_machine != EM_AARCH64) {
		fprintf(stderr, "FAIL: TA is not an AArch64 ELF image\n");
		free(image);
		return -1;
	}
	*image_out = image;
	*size_out = (size_t)end;
	return 0;
}

static int lookup_ta(struct qcomtee_object *loader, const char *name,
		     struct qcomtee_object **controller,
		     qcomtee_result_t *result)
{
	struct qcomtee_param params[2] = { 0 };

	params[0].attr = QCOMTEE_UBUF_INPUT;
	params[0].ubuf.addr = (void *)name;
	params[0].ubuf.size = strlen(name);
	params[1].attr = QCOMTEE_OBJREF_OUTPUT;
	if (qcomtee_object_invoke(loader, QSEECOM_COMPAT_LOOKUP_TA_OP,
				  params, 2, result))
		return -1;
	*controller = params[1].object;
	return 0;
}

int main(int argc, char **argv)
{
	const char *path;
	const char *load_name;
	const char *lookup_name = NULL;
	char dist_name[MAX_DIST_NAME_SIZE] = { 0 };
	struct qcomtee_object *root = QCOMTEE_OBJECT_NULL;
	struct qcomtee_object *client_env = QCOMTEE_OBJECT_NULL;
	struct qcomtee_object *loader = QCOMTEE_OBJECT_NULL;
	struct qcomtee_object *controller = QCOMTEE_OBJECT_NULL;
	struct qcomtee_object *lookup_controller = QCOMTEE_OBJECT_NULL;
	struct qcomtee_param params[4] = { 0 };
	unsigned char *image = NULL;
	size_t image_size = 0;
	qcomtee_result_t result = QCOMTEE_ERROR;
	int use_kernel_client_env = 0;
	int lookup_name_set = 0;
	int i;
	int loaded_here = 0;
	int exit_code = 1;

	if (argc < 3 || argc > 5) {
		fprintf(stderr,
			"usage: %s TA_IMAGE LOAD_NAME [LOOKUP_AFTER] [--kernel-client-env]\n",
			argv[0]);
		return 64;
	}
	path = argv[1];
	load_name = argv[2];
	for (i = 3; i < argc; i++) {
		if (!strcmp(argv[i], "--kernel-client-env")) {
			if (use_kernel_client_env)
				goto usage;
			use_kernel_client_env = 1;
		} else if (!lookup_name_set) {
			lookup_name = argv[i];
			lookup_name_set = 1;
		} else {
			goto usage;
		}
	}
	if (!load_name[0] || strlen(load_name) > 63 || strchr(load_name, '/') ||
	    (lookup_name && (!lookup_name[0] || strlen(lookup_name) > 63 ||
			     strchr(lookup_name, '/')))) {
		fprintf(stderr, "FAIL: invalid TA name\n");
		return 64;
	}
	if (read_image(path, &image, &image_size))
		return 1;

	root = test_get_root();
	if (root == QCOMTEE_OBJECT_NULL)
		goto out;
	client_env = use_kernel_client_env ?
		qtee_get_kernel_compat_client_env(root) :
		test_get_client_env_object(root);
	if (client_env == QCOMTEE_OBJECT_NULL)
		goto out;
	loader = test_get_service_object(client_env,
					 QSEECOM_COMPAT_APP_LOADER_UID);
	if (loader == QCOMTEE_OBJECT_NULL)
		goto out;

	if (lookup_ta(loader, load_name, &controller, &result)) {
		fprintf(stderr, "FAIL: initial lookup transport error\n");
		goto out;
	}
	if (result != QCOMTEE_OK || controller == QCOMTEE_OBJECT_NULL) {
		qcomtee_object_refs_dec(controller);
		controller = QCOMTEE_OBJECT_NULL;
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
		if (qcomtee_object_invoke(loader,
					  QSEECOM_COMPAT_LOAD_BUFFER_OP,
					  params, 4, &result)) {
			fprintf(stderr, "FAIL: load transport error\n");
			goto out;
		}
		controller = params[3].object;
		if (result != QCOMTEE_OK || controller == QCOMTEE_OBJECT_NULL) {
			fprintf(stderr,
				"REJECTED: loadFromBuffer(%s) result %d (distribution output %zu bytes)\n",
				load_name, result, params[2].ubuf.size);
			exit_code = 2;
			goto out;
		}
		loaded_here = 1;
		printf("LOADED: %s (%zu bytes)\n", load_name, image_size);
	} else {
		printf("FOUND: %s was already loaded\n", load_name);
	}

	if (lookup_name) {
		if (lookup_ta(loader, lookup_name, &lookup_controller, &result)) {
			fprintf(stderr, "FAIL: post-load lookup transport error\n");
			goto out;
		}
		if (result == QCOMTEE_OK &&
		    lookup_controller != QCOMTEE_OBJECT_NULL)
			printf("FOUND: dependency %s is available\n", lookup_name);
		else
			printf("ABSENT: dependency %s lookup result %d\n",
			       lookup_name, result);
	}
	exit_code = 0;

out:
	qcomtee_object_refs_dec(lookup_controller);
	if (loaded_here && controller != QCOMTEE_OBJECT_NULL) {
		qcomtee_result_t unload_result = QCOMTEE_ERROR;

		if (qcomtee_object_invoke(controller, QSEECOM_COMPAT_UNLOAD_OP,
					  NULL, 0, &unload_result) ||
		    unload_result != QCOMTEE_OK) {
			fprintf(stderr, "WARN: unload(%s) result %d\n",
				load_name, unload_result);
			exit_code = 1;
		} else {
			printf("UNLOADED: %s; no TA request was invoked\n", load_name);
		}
	}
	free(image);
	qcomtee_object_refs_dec(controller);
	qcomtee_object_refs_dec(loader);
	qcomtee_object_refs_dec(client_env);
	qcomtee_object_refs_dec(root);
	return exit_code;

usage:
	fprintf(stderr,
		"usage: %s TA_IMAGE LOAD_NAME [LOOKUP_AFTER] [--kernel-client-env]\n",
		argv[0]);
	return 64;
}
