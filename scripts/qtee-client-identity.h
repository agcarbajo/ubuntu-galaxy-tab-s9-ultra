// SPDX-License-Identifier: BSD-3-Clause
// Helpers for running a QTEE diagnostic with a deliberately reduced identity.

#ifndef QTEE_CLIENT_IDENTITY_H
#define QTEE_CLIENT_IDENTITY_H

#include <errno.h>
#include <grp.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <unistd.h>

static int qtee_parse_client_uid(const char *argument, uid_t *uid)
{
	static const char prefix[] = "--client-uid=";
	unsigned long value;
	char *end;

	if (strncmp(argument, prefix, sizeof(prefix) - 1))
		return -1;
	argument += sizeof(prefix) - 1;
	if (!*argument || *argument == '-')
		return -1;

	errno = 0;
	value = strtoul(argument, &end, 10);
	if (errno || *end || value > UINT_MAX || (uid_t)value != value)
		return -1;

	*uid = (uid_t)value;
	return 0;
}

/*
 * test_get_root() must be called first so /dev/tee0 is already open.  This
 * then drops every local privilege irreversibly before quic-teec serialises
 * getuid() into the credentials object used by registerAsClient.
 */
static int qtee_drop_client_identity(uid_t uid)
{
	if (geteuid() != 0) {
		if (getuid() == uid && geteuid() == uid)
			return 0;
		fprintf(stderr,
			"FAIL: --client-uid requires root or the requested UID\n");
		return -1;
	}

	if (setgroups(0, NULL) ||
	    setresgid((gid_t)uid, (gid_t)uid, (gid_t)uid) ||
	    setresuid(uid, uid, uid)) {
		fprintf(stderr, "FAIL: cannot drop to client UID %u: %s\n",
			(unsigned int)uid, strerror(errno));
		return -1;
	}
	if (getuid() != uid || geteuid() != uid || getgid() != (gid_t)uid ||
	    getegid() != (gid_t)uid) {
		fprintf(stderr, "FAIL: client identity did not change completely\n");
		return -1;
	}

	printf("QTEE client identity irreversibly reduced to UID/GID %u.\n",
	       (unsigned int)uid);
	return 0;
}

#endif
