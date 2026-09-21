from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class IlluminationTests(unittest.TestCase):
    def test_actual_request_light_and_cleanup_functions(self):
        source = (ROOT / 'packaging/libfprint/el721.c').read_text()
        functions = []
        for name in ('udfps_light', 'udfps_prepare_light', 'udfps_end'):
            match = re.search(r'static (?:gboolean|void)\n' + name + r' \(.*?^\}', source, re.M | re.S)
            self.assertIsNotNone(match, name)
            functions.append(match[0])
        harness = r'''
#include <glib.h>
#include <glib/gstdio.h>
#include <string.h>
#include "el721-ui-lease.h"
static const char *request_path, *visual_path;
#define EL721_PANEL "panel"
#define EL721_TOUCH "touch"
#define EL721_LIGHT_REQUEST request_path
#define EL721_VISUAL_STATE visual_path
typedef struct {
    gboolean udfps_active, udfps_lit, touch_inhibited, enroll_armed;
    gint64 light_requested, capture_deadline, udfps_refreshed, visual_refreshed;
    guint64 fod_sequence;
    guint32 enroll_arm_status;
} FpiDeviceEl721;
static int panel_on, panel_off;
static gboolean fail_write;
static gboolean write_child(const gchar *directory, const gchar *name,
                            const gchar *value, GError **error) {
    (void) name;
    if (g_str_equal(directory, EL721_PANEL)) {
        if (g_str_equal(value, "1\n")) panel_on++; else panel_off++;
        if (fail_write) {
            g_set_error_literal(error, G_FILE_ERROR, G_FILE_ERROR_FAILED, "test I/O failure");
            return FALSE;
        }
    }
    return TRUE;
}
'''
        harness += '\n'.join(functions) + r'''
int main(int argc, char **argv) {
    g_assert_cmpint(argc, ==, 2);
    request_path = argv[1];
    g_autofree gchar *active = g_strconcat(request_path, ".active", NULL);
    visual_path = active;
    FpiDeviceEl721 self = {.udfps_active = TRUE};
    g_assert_true(udfps_prepare_light(&self, NULL));
    g_assert_cmpint(panel_on, ==, 0);
    g_assert_cmpint(panel_off, ==, 0);
    g_assert_false(self.udfps_lit);
    g_assert_cmpint(self.capture_deadline, ==, self.light_requested + G_USEC_PER_SEC);
    g_assert_true(g_file_test(request_path, G_FILE_TEST_EXISTS));
    g_autofree gchar *ack = g_strdup_printf("ready %" G_GINT64_FORMAT "\n", self.capture_deadline);
    g_assert_true(el721_ui_light_ready(ack, self.light_requested, g_get_monotonic_time()));
    g_assert_true(udfps_light(&self, TRUE, NULL));
    g_assert_cmpint(panel_on, ==, 1);
    g_assert_true(self.udfps_lit);
    g_assert_true(udfps_light(&self, FALSE, NULL));
    g_assert_false(g_file_test(request_path, G_FILE_TEST_EXISTS));
    g_assert_cmpint(self.light_requested, ==, 0);
    g_assert_false(self.udfps_lit);
    g_assert_true(udfps_prepare_light(&self, NULL));
    fail_write = TRUE;
    udfps_end(&self);
    g_assert_false(self.udfps_active);
    g_assert_false(g_file_test(request_path, G_FILE_TEST_EXISTS));
    g_assert_cmpint(self.light_requested, ==, 0);
    g_assert_cmpint(panel_on, ==, 1);
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cfile, binary = root / 'handshake.c', root / 'handshake'
            cfile.write_text(harness)
            flags = shlex.split(subprocess.check_output(
                ['pkg-config', '--cflags', '--libs', 'glib-2.0'], text=True))
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                '-I', str(ROOT / 'packaging/libfprint'), str(cfile), '-o', str(binary), *flags], check=True)
            subprocess.run([str(binary), str(root / 'light')], check=True)


if __name__ == '__main__':
    unittest.main()
