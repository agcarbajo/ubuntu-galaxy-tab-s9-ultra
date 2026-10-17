/* SPDX-License-Identifier: MIT
 *
 * liblog_capture.so: the LD_PRELOAD shim the secure fingerprint supervisor
 * loads into Samsung's SPU daemons (sec_nvm, spdaemon) under Bionic's linker.
 *
 * The daemons log through Android's liblog, which is not part of the runtime
 * assembled from the tablet's own system and vendor images.  This file
 * replaces the two entry points they import and writes each message to stderr,
 * which the supervisor redirects into /var/log/ubuntu-gts9u-fingerprint/
 * <daemon>.log and scans for "SP Apps were loaded successfully".
 *
 * It must stay free of glibc: it is linked with -nostdlib so that vsnprintf()
 * and write() are resolved at run time against Bionic's libc.so, and it must
 * not import anything else (no stack protector, no builtins).  The validated
 * 2026-09-01 binary exported exactly __android_log_print and
 * __android_log_buf_print and imported exactly vsnprintf and write; this source
 * reproduces that behaviour: "[tag] message\n", truncated to 2 KiB.
 */
#include <stdarg.h>
#include <stddef.h>

#define LINE_MAX 2048

int vsnprintf(char *buffer, size_t size, const char *format, va_list args);
long write(int fd, const void *buffer, size_t count);

static int capture_log(const char *tag, const char *format, va_list args)
{
	char line[LINE_MAX];
	int used = 0;
	int length;

	if (tag) {
		line[used++] = '[';
		while (*tag && used <= LINE_MAX - 4)
			line[used++] = *tag++;
		line[used++] = ']';
		line[used++] = ' ';
	}
	length = vsnprintf(line + used, LINE_MAX - used, format, args);
	if (length < 0)
		return length;
	length += used;
	if (length > LINE_MAX - 2)
		length = LINE_MAX - 2;
	line[length++] = '\n';
	write(2, line, length);
	return length;
}

int __android_log_buf_print(int buffer_id, int priority, const char *tag,
			    const char *format, ...)
{
	va_list args;
	int length;

	(void)buffer_id;
	(void)priority;
	va_start(args, format);
	length = capture_log(tag, format, args);
	va_end(args);
	return length;
}

int __android_log_print(int priority, const char *tag, const char *format, ...)
{
	va_list args;
	int length;

	(void)priority;
	va_start(args, format);
	length = capture_log(tag, format, args);
	va_end(args);
	return length;
}
