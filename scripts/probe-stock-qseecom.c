// SPDX-License-Identifier: MIT
// Minimal Android/bionic probe for Samsung's stock QSEECom compatibility API.

typedef unsigned int uint32_t;

struct QSEECom_handle;

extern int QSEECom_start_app(struct QSEECom_handle **handle,
			     const char *path, const char *name,
			     uint32_t shared_buffer_size);
extern int QSEECom_shutdown_app(struct QSEECom_handle **handle);
extern int dprintf(int fd, const char *format, ...);
extern void _exit(int status);

void _start(void)
{
	struct QSEECom_handle *handle = (void *)0;
	int shutdown_result = -1;
	int result;

	result = QSEECom_start_app(&handle, "/vendor/firmware_mnt/image",
				   "securefp", 128U);
	dprintf(1, "QSEECom_start_app(securefp)=%d handle=%p\n", result,
		handle);
	if (!result && handle)
		shutdown_result = QSEECom_shutdown_app(&handle);
	dprintf(1, "QSEECom_shutdown_app=%d handle=%p\n", shutdown_result,
		handle);
	_exit(result ? 2 : (shutdown_result ? 3 : 0));
}
