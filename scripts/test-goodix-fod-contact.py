#!/usr/bin/env python3
"""Compile the actual patched FOD functions against a minimal input harness.

No device access. The original implementation must fail the regression; the
patched implementation must retain the contact until RELEASE. This is not a
kernel build or a physical touchscreen test.
"""
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PATCHES = ROOT / 'kernel/patches'

PRELUDE = r'''
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <sys/types.h>
typedef uint8_t u8;
typedef uint16_t u16;
enum { GOODIX_BERLIN_SAMSUNG_ACTION_PRESS = 1,
       GOODIX_BERLIN_SAMSUNG_ACTION_MOVE = 2,
       GOODIX_BERLIN_SAMSUNG_ACTION_RELEASE = 3 };
enum { GOODIX_BERLIN_FOD_IDLE, GOODIX_BERLIN_FOD_PRESSED,
       GOODIX_BERLIN_FOD_RELEASED };
struct goodix_berlin_core;
struct device { int kobj; struct goodix_berlin_core *data; };
struct device_attribute { int unused; };
struct goodix_berlin_core {
    int fod_lock, irq;
    bool fod_enabled, fod_rect_valid;
    unsigned long fod_suppressed_slots;
    int fod_state;
    u16 fod_x, fod_y, fod_rect[4];
    unsigned long fod_sequence;
    struct device *dev;
};
static int notifications, write_error;
#define mutex_lock(x) ((void)(x))
#define mutex_unlock(x) ((void)(x))
#define disable_irq(x) ((void)(x))
#define dev_warn(...) ((void)0)
static void goodix_berlin_power_off(struct goodix_berlin_core *c) {}
static bool test_bit(u8 id, unsigned long *slots) { return !!(*slots & (1UL << id)); }
static bool test_and_clear_bit(u8 id, unsigned long *slots) {
    bool old = test_bit(id, slots); *slots &= ~(1UL << id); return old;
}
static bool test_and_set_bit(u8 id, unsigned long *slots) {
    bool old = test_bit(id, slots); *slots |= 1UL << id; return old;
}
#define clear_bit(id, slots) ((void)test_and_clear_bit(id, slots))
static void sysfs_notify(int *k, void *unused, const char *attr) { notifications++; }
static int kstrtobool(const char *s, bool *b) {
    if (*s != '0' && *s != '1') return -22;
    *b = *s == '1'; return 0;
}
static struct goodix_berlin_core *dev_get_drvdata(struct device *d) { return d->data; }
static int goodix_berlin_set_fod_mode_locked(struct goodix_berlin_core *c, bool b) {
    return write_error;
}
'''

TEST = r'''
#define CHECK(expr, why) do { if (!(expr)) { puts(why); return 1; } } while (0)
#define EVENT(id, action, x, y) goodix_berlin_suppress_fod_touch(&c, id, action, x, y)
#define PRESS GOODIX_BERLIN_SAMSUNG_ACTION_PRESS
#define MOVE GOODIX_BERLIN_SAMSUNG_ACTION_MOVE
#define RELEASE GOODIX_BERLIN_SAMSUNG_ACTION_RELEASE
int main(void) {
    struct device dev = {0};
    struct goodix_berlin_core c = {.dev=&dev, .fod_rect_valid=true,
                                  .fod_rect={100,100,200,200}};
    dev.data = &c;
    CHECK(!EVENT(0, PRESS, 150,150), "ordinary touch with reader off");
    CHECK(!EVENT(0, RELEASE, 150,150), "ordinary release with reader off");
    CHECK(fod_enable_store(&dev, NULL, "1", 1) == 1, "enable reader");
    CHECK(!EVENT(1, PRESS, 50,50), "outside press must pass");
    CHECK(!EVENT(1, MOVE, 150,150), "pre-existing outside gesture must pass");
    CHECK(EVENT(0, PRESS, 150,150), "reader press must be consumed");
    CHECK(c.fod_state == GOODIX_BERLIN_FOD_PRESSED, "preserve reader press event");
    CHECK(fod_enable_store(&dev, NULL, "0", 1) == 1, "disable after match");
    CHECK(test_bit(0, &c.fod_suppressed_slots), "REGRESSION: mode disable lost held contact");
    int n = notifications;
    CHECK(EVENT(0, MOVE, 250,250), "held finger must stay consumed outside rectangle");
    CHECK(!EVENT(2, PRESS, 150,150), "independent new finger must pass with reader off");
    CHECK(!EVENT(2, RELEASE, 150,150), "independent release must pass");
    CHECK(EVENT(0, RELEASE, 250,250), "original release must be consumed");
    CHECK(!test_bit(0, &c.fod_suppressed_slots), "release must clear suppression");
    CHECK(notifications == n, "closed session must not receive release notifications");
    CHECK(c.fod_state == GOODIX_BERLIN_FOD_IDLE, "closed session remains idle");
    CHECK(!EVENT(0, PRESS, 150,150), "next intentional tap must pass");
    CHECK(!EVENT(0, RELEASE, 150,150), "next intentional release must pass");
    CHECK(fod_enable_store(&dev, NULL, "1", 1) == 1, "reenable");
    CHECK(EVENT(0, PRESS, 150,150), "consume next reader contact");
    CHECK(EVENT(3, PRESS, 150,150), "consume second reader contact independently");
    CHECK(EVENT(0, RELEASE, 150,150), "release while reader enabled");
    CHECK(c.fod_state == GOODIX_BERLIN_FOD_RELEASED, "enabled reader receives release");
    CHECK(test_bit(3, &c.fod_suppressed_slots), "first release must not clear second contact");
    write_error = -5;
    CHECK(fod_enable_store(&dev, NULL, "0", 1) == -5 && c.fod_enabled,
          "failed mode write must preserve enabled state");
    write_error = 0;
    CHECK(fod_enable_store(&dev, NULL, "0", 1) == 1, "disable second contact");
    CHECK(fod_enable_store(&dev, NULL, "0", 1) == 1, "repeated disable is harmless");
    CHECK(EVENT(3, MOVE, 150,150), "repeated disable must preserve suppression");
    CHECK(!EVENT(3, PRESS, 50,50), "fresh PRESS recovers slot after missing RELEASE");
    CHECK(!EVENT(3, MOVE, 60,60), "reused slot is ordinary touch");
    CHECK(!EVENT(3, RELEASE, 60,60), "reused slot release passes");
    c.fod_suppressed_slots = 1;
    CHECK(goodix_berlin_suspend(&dev) == 0 && !c.fod_suppressed_slots,
          "suspend clears retained contact with reader off");
    c.fod_enabled = true;
    c.fod_suppressed_slots = 3;
    CHECK(goodix_berlin_suspend(&dev) == 0 && !c.fod_suppressed_slots && !c.fod_enabled,
          "suspend clears contacts and closes active reader");
    puts("PASS: FOD contact lifetime, independent fingers, slot reuse, notifications, write failure and suspend");
    return 0;
}
'''


def main():
    added = '\n'.join(line[1:] for line in
        (PATCHES / 'support-goodix-samsung-fod.patch').read_text().splitlines()
        if line.startswith('+') and not line.startswith('+++'))
    functions = []
    for signature in ('static bool goodix_berlin_suppress_fod_touch',
                      'static ssize_t fod_enable_store'):
        match = re.search(re.escape(signature) + r'[\s\S]*?\n}', added)
        if not match:
            raise RuntimeError('Cannot locate production function: ' + signature)
        functions.append(match.group())
    cleanup = (PATCHES / 'cleanup-goodix-fod-on-suspend.patch').read_text()
    hunk = re.split(r'^@@.*\n', cleanup, flags=re.M)[1]
    suspend = ('static int goodix_berlin_suspend(struct device *dev)\n' +
               '\n'.join(line[1:] for line in hunk.splitlines()
                         if line.startswith(('+', ' '))) + '\n}')
    functions.insert(1, suspend.strip())
    with tempfile.TemporaryDirectory(prefix='goodix-fod-test-') as directory:
        root = Path(directory)
        source = root / 'drivers/input/touchscreen/goodix_berlin_core.c'
        source.parent.mkdir(parents=True)
        source.write_text('\n\n'.join(functions) + '\n')
        original = source.read_text()
        subprocess.run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(PATCHES /
                        'retain-goodix-fod-contact-until-release.patch')], cwd=root, check=True)
        for label, body in [('original', original), ('fixed', source.read_text())]:
            test = root / (label + '.c')
            binary = root / label
            test.write_text(PRELUDE + body + TEST)
            subprocess.run(['cc', '-std=gnu11', '-O2', '-Wall', '-Werror',
                            str(test), '-o', str(binary)], check=True)
            result = subprocess.run([str(binary)], text=True, capture_output=True)
            if label == 'original':
                assert result.returncode == 1 and 'REGRESSION:' in result.stdout, result
                print('Original implementation reproduces lost-contact regression')
            else:
                assert result.returncode == 0, result.stdout + result.stderr
                print(result.stdout.strip())


if __name__ == '__main__':
    main()
