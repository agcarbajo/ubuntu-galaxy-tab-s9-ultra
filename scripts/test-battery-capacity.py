from pathlib import Path
import re
import runpy
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'kernel/drivers/sm5714_battery.c'


def function(text, name):
    match = re.search(r'static int ' + name + r'\([^;]+?\n\{.*?\n\}', text, re.S)
    if not match:
        raise AssertionError('Missing tested function: ' + name)
    return match[0]


class CapacityTests(unittest.TestCase):
    def test_real_driver_scaling_and_status(self):
        text = SOURCE.read_text()
        code = r'''
#include <assert.h>
#include <stdbool.h>
#define POWER_SUPPLY_STATUS_DISCHARGING 0
#define POWER_SUPPLY_STATUS_CHARGING 1
#define POWER_SUPPLY_STATUS_FULL 2
#define POWER_SUPPLY_STATUS_NOT_CHARGING 3
#define SM5714_CHG_STATUS1_VBUS_POK 1
#define SM5714_CHG_STATUS2_TOPOFF 32
#define SM5714_CHG_STATUS2_CHG_ON 8
#define clamp(v, lo, hi) ((v) < (lo) ? (lo) : ((v) > (hi) ? (hi) : (v)))
'''
        code += function(text, 'sm5714_capacity_scaled') + '\n'
        code += function(text, 'sm5714_status_from_regs') + r'''
int main(void) {
    int maximum = 990;
    bool full = false;
    assert(sm5714_capacity_scaled(687, false, &maximum, &full) == 69);
    assert(sm5714_capacity_scaled(950, false, &maximum, &full) == 95);
    assert(maximum == 990);
    assert(sm5714_capacity_scaled(950, true, &maximum, &full) == 100);
    assert(maximum == 931);
    assert(sm5714_capacity_scaled(970, true, &maximum, &full) == 100);
    assert(maximum == 950);
    assert(sm5714_capacity_scaled(960, true, &maximum, &full) == 100);
    assert(maximum == 950);
    assert(sm5714_capacity_scaled(950, false, &maximum, &full) == 100);
    assert(sm5714_capacity_scaled(900, false, &maximum, &full) == 94);
    assert(sm5714_capacity_scaled(0, false, &maximum, &full) == 0);
    assert(sm5714_capacity_scaled(600, true, &maximum, &full) == 63);
    assert(maximum == 950);
    assert(!full);
    assert(sm5714_capacity_scaled(1200, true, &maximum, &full) == 100);
    assert(maximum == 1000);
    assert(sm5714_status_from_regs(0, 40, false, false) == POWER_SUPPLY_STATUS_DISCHARGING);
    assert(sm5714_status_from_regs(1, 40, false, true) == POWER_SUPPLY_STATUS_DISCHARGING);
    assert(sm5714_status_from_regs(1, 40, true, false) == POWER_SUPPLY_STATUS_CHARGING);
    assert(sm5714_status_from_regs(1, 40, false, false) == POWER_SUPPLY_STATUS_FULL);
    assert(sm5714_status_from_regs(1, 8, false, false) == POWER_SUPPLY_STATUS_CHARGING);
    assert(sm5714_status_from_regs(1, 0, false, false) == POWER_SUPPLY_STATUS_NOT_CHARGING);
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'capacity.c'
            source.write_text(code)
            binary = Path(tmp) / 'capacity'
            subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', str(source), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.scale, self.state, self.ready = [root / name for name in ('scale', 'state', 'run/ready')]
        self.scale.write_text('990\n')
        module = runpy.run_path(str(SOURCE.parents[2] /
            'packaging/ubuntu-gts9u-device/usr/libexec/ubuntu-gts9u-battery-capacity'))
        self.sync = lambda action: module['synchronize'](action, self.scale, self.state, self.ready)

    def test_early_uevent_does_not_overwrite_saved_scale(self):
        self.state.write_text('931\n')
        self.sync('save')
        self.assertEqual(self.state.read_text(), '931\n')
        self.sync('restore')
        self.assertEqual(self.scale.read_text(), '931\n')
        self.assertTrue(self.ready.exists())

    def test_save_learned_scale_and_no_repeated_writes(self):
        self.sync('restore')
        self.scale.write_text('931\n')
        self.sync('save')
        self.assertEqual(self.state.read_text(), '931\n')
        stamp = self.state.stat().st_mtime_ns
        self.sync('save')
        self.assertEqual(self.state.stat().st_mtime_ns, stamp)

    def test_invalid_saved_scale_is_not_applied(self):
        for value in ('0', '699', '1001', 'not a number'):
            self.state.write_text(value)
            self.sync('restore')
            self.assertEqual(self.scale.read_text(), '990\n')

    def test_old_kernel_is_untouched(self):
        self.scale.unlink()
        self.sync('restore')
        self.assertFalse(self.ready.exists())
        self.assertFalse(self.state.exists())

    def test_pump_uses_unscaled_soc(self):
        source = SOURCE.with_name('sm5440_direct.c').read_text()
        self.assertEqual(source.count('capacity = sm5714_battery_get_raw_capacity();'), 2)
        self.assertNotIn('sm5440_psy_get(sm->battery, POWER_SUPPLY_PROP_CAPACITY)', source)


if __name__ == '__main__':
    unittest.main()
