from pathlib import Path
import ast
import runpy
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RecoveryTests(unittest.TestCase):
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
        source = ROOT / 'packaging/ubuntu-gts9u-companion/usr/lib/tab-companion/tab_companion/window.py'
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
