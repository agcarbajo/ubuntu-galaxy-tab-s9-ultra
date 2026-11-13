from pathlib import Path
import ast
import runpy
import os
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class RecoveryTests(unittest.TestCase):
    def test_packaged_dropin_covers_all_shell_modes(self):
        units = ROOT / 'packaging/ubuntu-gts9u-device/usr/lib/systemd/user'
        dropin = units / 'org.gnome.Shell@.service.d/90-gts9u-extension-recovery.conf'
        self.assertIn('ExecStopPost=-/usr/libexec/ubuntu-gts9u-extension-failure %n', dropin.read_text())
        for mode in ('wayland', 'x11'):
            self.assertFalse((units / f'org.gnome.Shell@{mode}.service.d/90-gts9u-extension-recovery.conf').exists())

    def test_modes_remove_only_false_failure_markers(self):
        helper = runpy.run_path(str(ROOT / 'packaging/ubuntu-gts9u-device/usr/libexec/ubuntu-gts9u-extension-failure'))
        for mode in ('wayland', 'x11', 'ubuntu', 'gdm', 'gnome', 'ubuntu-xorg'):
            unit = f'org.gnome.Shell@{mode}.service'
            for result, active, keep in (('success', 200, False), ('timeout', 200, False),
                                         ('timeout', 0, True), ('signal', 200, True),
                                         ('core-dump', 200, True), ('oom-kill', 200, True)):
                with self.subTest(mode=mode, result=result, active=active), tempfile.TemporaryDirectory() as tmp:
                    marker = Path(tmp) / 'gnome-shell-disable-extensions'
                    marker.touch()
                    response = SimpleNamespace(returncode=0, stdout=f'Result={result}\nExecMainStartTimestampMonotonic=100\nActiveEnterTimestampMonotonic={active}\n')
                    with patch.dict(os.environ, {'XDG_RUNTIME_DIR': tmp, 'SERVICE_RESULT': result}), \
                         patch('sys.argv', ['helper', unit]), patch('subprocess.run', return_value=response) as run:
                        helper['main']()
                    self.assertEqual(marker.exists(), keep)
                    self.assertIn(unit, run.call_args.args[0])

    def test_rejects_other_units(self):
        helper = runpy.run_path(str(ROOT / 'packaging/ubuntu-gts9u-device/usr/libexec/ubuntu-gts9u-extension-failure'))
        for unit in ('other.service', 'org.gnome.Shell@.service', '--all',
                     'org.gnome.Shell@ubuntu.service/other'):
            with self.subTest(unit=unit), patch('sys.argv', ['helper', unit]), \
                 patch('subprocess.run') as run, self.assertRaises(SystemExit):
                helper['main']()
            run.assert_not_called()

    def test_stop_timeout_is_not_an_extension_crash(self):
        helper = runpy.run_path(str(ROOT / 'packaging/ubuntu-gts9u-device/usr/libexec/ubuntu-gts9u-extension-failure'))
        check = helper['should_disable']
        self.assertFalse(check({'Result': 'timeout', 'ActiveEnterTimestampMonotonic': '200', 'ExecMainStartTimestampMonotonic': '100'}))
        self.assertTrue(check({'Result': 'timeout', 'ActiveEnterTimestampMonotonic': '0', 'ExecMainStartTimestampMonotonic': '100'}))
        self.assertTrue(check({'Result': 'timeout', 'ActiveEnterTimestampMonotonic': '100', 'ExecMainStartTimestampMonotonic': '200'}))
        self.assertFalse(check({'Result': 'success', 'ExecMainCode': '1', 'ExecMainStatus': '0'}))
        self.assertTrue(check({'Result': 'oom-kill', 'ExecMainCode': '2', 'ExecMainStatus': '9'}))
        self.assertTrue(check({'Result': 'core-dump', 'ExecMainCode': '3', 'ExecMainStatus': '11'}))
        self.assertTrue(check({'Result': 'signal', 'ExecMainCode': '2', 'ExecMainStatus': '6'}))
        self.assertTrue(check({'Result': 'exit-code', 'ExecMainCode': '1', 'ExecMainStatus': '2'}))
        self.assertFalse(check({'Result': 'exit-code', 'ExecMainCode': '1', 'ExecMainStatus': '1'}))
        self.assertTrue(check({}))


class CompanionToggleTests(unittest.TestCase):
    def test_global_and_individual_disables_are_visible_and_recoverable(self):
        source = ROOT / 'external/galaxy-companion/packaging/galaxy-companion/usr/lib/galaxy-companion/galaxy_companion/window.py'
        names = ('_shell_extension_enabled', '_boot_tile_toggled')
        functions = [node for node in ast.walk(ast.parse(source.read_text()))
                     if isinstance(node, ast.FunctionDef) and node.name in names]
        values = {'enabled-extensions': ['other', 'dualboot@agcarbajo.github.io'],
                  'disabled-extensions': [], 'disable-user-extensions': False}
        settings = SimpleNamespace(get_strv=lambda key: values[key],
            get_boolean=lambda key: values[key], set_strv=lambda key, value: values.update({key: value}),
            set_boolean=lambda key, value: values.update({key: value}))
        namespace = {'Gio': SimpleNamespace(Settings=SimpleNamespace(new=lambda _: settings)),
                     'GLib': SimpleNamespace(Error=RuntimeError)}
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), 'exec'), namespace)
        owner = SimpleNamespace(SHELL_EXTENSION_UUID='dualboot@agcarbajo.github.io')
        enabled = lambda: namespace['_shell_extension_enabled'](owner)
        toggle = lambda value: namespace['_boot_tile_toggled'](owner, SimpleNamespace(get_active=lambda: value), None)
        self.assertTrue(enabled())
        values['disable-user-extensions'] = True
        self.assertFalse(enabled())
        values['disabled-extensions'] = ['other-disabled', owner.SHELL_EXTENSION_UUID]
        toggle(True)
        self.assertTrue(enabled())
        self.assertEqual(values['disabled-extensions'], ['other-disabled'])
        self.assertIn('other', values['enabled-extensions'])
        toggle(False)
        self.assertFalse(enabled())
        self.assertEqual(values['enabled-extensions'], ['other'])


if __name__ == '__main__':
    unittest.main()
