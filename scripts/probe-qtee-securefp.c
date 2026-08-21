// SPDX-License-Identifier: BSD-3-Clause
// Minimal, read-only QTEE presence probe for Samsung's preloaded securefp TA.
// Uses Qualcomm's quic-teec test helpers for root/client-environment setup.

#define _GNU_SOURCE

#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "tests_private.h"
#include "qtee-client-identity.h"

#define QSEECOM_COMPAT_APP_LOADER_UID UINT32_C(122)
#define QSEECOM_COMPAT_LOOKUP_TA_OP UINT32_C(2)

int main(int argc, char **argv)
{
	const char *app_name = "securefp";
	struct qcomtee_object *root = QCOMTEE_OBJECT_NULL;
	struct qcomtee_object *client_env = QCOMTEE_OBJECT_NULL;
	struct qcomtee_object *app_loader = QCOMTEE_OBJECT_NULL;
	struct qcomtee_object *app_controller = QCOMTEE_OBJECT_NULL;
	struct qcomtee_param params[2] = { 0 };
	qcomtee_result_t result = -1;
	uid_t client_uid = 0;
	int use_client_uid = 0;
	int use_kernel_client_env = 0;
	int app_name_set = 0;
	int i;
	int transport_ret;
	int exit_code = 1;

	for (i = 1; i < argc; i++) {
		if (!strncmp(argv[i], "--client-uid=", 13)) {
			if (use_client_uid || use_kernel_client_env ||
			    qtee_parse_client_uid(argv[i], &client_uid))
				goto usage;
			use_client_uid = 1;
		} else if (!strcmp(argv[i], "--kernel-client-env")) {
			if (use_kernel_client_env || use_client_uid)
				goto usage;
			use_kernel_client_env = 1;
		} else if (!app_name_set) {
			app_name = argv[i];
			app_name_set = 1;
		} else {
			goto usage;
		}
	}
	if (!app_name[0] || strlen(app_name) > 63 || strchr(app_name, '/')) {
		fprintf(stderr, "FAIL: invalid TA name\n");
		return 64;
	}

	root = test_get_root();
	if (root == QCOMTEE_OBJECT_NULL) {
		fprintf(stderr, "FAIL: could not open /dev/tee0\n");
		goto out;
	}
	if (use_client_uid && qtee_drop_client_identity(client_uid))
		goto out;

	client_env = use_kernel_client_env ?
		qtee_get_kernel_compat_client_env(root) :
		test_get_client_env_object(root);
	if (client_env == QCOMTEE_OBJECT_NULL) {
		fprintf(stderr, "FAIL: could not obtain IClientEnv\n");
		goto out;
	}

	app_loader = test_get_service_object(
		client_env, QSEECOM_COMPAT_APP_LOADER_UID);
	if (app_loader == QCOMTEE_OBJECT_NULL) {
		fprintf(stderr,
			"FAIL: could not open QSEECom compat AppLoader UID 122\n");
		goto out;
	}

	params[0].attr = QCOMTEE_UBUF_INPUT;
	params[0].ubuf.addr = (void *)app_name;
	/* IQSEEComCompatAppLoader_lookupTA passes strlen(), without NUL. */
	params[0].ubuf.size = strlen(app_name);
	params[1].attr = QCOMTEE_OBJREF_OUTPUT;
	params[1].object = QCOMTEE_OBJECT_NULL;

	transport_ret = qcomtee_object_invoke(
		app_loader, QSEECOM_COMPAT_LOOKUP_TA_OP, params, 2, &result);
	if (transport_ret) {
		fprintf(stderr, "FAIL: lookupTA transport error %d\n",
			transport_ret);
		goto out;
	}
	if (result != QCOMTEE_OK) {
		fprintf(stderr, "ABSENT/REJECTED: lookupTA(%s) result %d\n",
			app_name, result);
		exit_code = 2;
		goto out;
	}

	app_controller = params[1].object;
	if (app_controller == QCOMTEE_OBJECT_NULL) {
		fprintf(stderr,
			"FAIL: lookupTA succeeded but returned a NULL object\n");
		goto out;
	}

	printf("FOUND: preloaded TA %s is available via UID 122.\n", app_name);
	printf("No operation was invoked; releasing its controller.\n");
	exit_code = 0;

out:
	/* The only operation sent to a returned TA controller is reserved RELEASE. */
	qcomtee_object_refs_dec(app_controller);
	qcomtee_object_refs_dec(app_loader);
	qcomtee_object_refs_dec(client_env);
	qcomtee_object_refs_dec(root);
	return exit_code;

usage:
	fprintf(stderr,
		"Usage: %s [TA-name] [--client-uid=UID | --kernel-client-env]\n",
		argv[0]);
	return 64;
}
