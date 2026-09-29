#!/usr/bin/env python3
import importlib.util
import json
import sys
from pathlib import Path
from unittest import TestCase, main
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('launcher', Path(__file__).with_name('update-to-latest.py'))
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class LauncherTests(TestCase):
    def test_main_imports_the_complete_real_backend_from_one_revision(self):
        source = Path(__file__).resolve().parents[1] / 'packaging/ubuntu-gts9u-companion/usr/lib/tab-companion/tab_companion'
        commit = 'a' * 40
        fetched = []
        def fetch(url, limit):
            fetched.append(url)
            if url.endswith('/commits/main'):
                return json.dumps({'sha': commit}).encode()
            self.assertIn('/' + commit + '/', url)
            return (source / url.rsplit('/', 1)[1]).read_bytes()
        # Isolate module imports as well as sys.path; no updater action runs.
        with patch.dict(sys.modules), patch.object(sys, 'path', sys.path.copy()), \
             patch.object(launcher.os, 'geteuid', return_value=0), \
             patch.object(launcher, 'fetch', side_effect=fetch), \
             patch.object(launcher, 'update') as update:
            for name in tuple(sys.modules):
                if name == 'tab_companion' or name.startswith('tab_companion.'):
                    del sys.modules[name]
            launcher.main()
            core, bundle = update.call_args.args
            self.assertTrue(callable(core.prepare))
            self.assertTrue(callable(bundle.inspect))
            self.assertEqual(core.policy.PROTOCOL, 2)
        self.assertEqual(len(fetched), 4)

    def setUp(self):
        self.core = Mock()
        self.core.status.return_value = {'state': 'ready'}
        self.bundle = Mock()
        self.bundle.release.return_value = {'tag': 'v1.1.0'}
        self.bundle.release_state.return_value = 'newer'

    def test_decline_never_prepares_or_reboots(self):
        with patch('builtins.input', return_value='n'), patch.object(launcher.subprocess, 'run') as run:
            launcher.update(self.core, self.bundle)
        self.core.main.assert_not_called()
        run.assert_not_called()

    def test_confirmation_prepares_then_reboots(self):
        with patch('builtins.input', return_value='y'), patch.object(launcher.subprocess, 'run') as run:
            launcher.update(self.core, self.bundle)
        self.core.main.assert_called_once_with(['--latest'])
        run.assert_called_once_with(['systemctl', 'reboot'], check=True)

    def test_failure_does_not_reboot(self):
        self.core.main.side_effect = RuntimeError('preparation failed')
        with patch('builtins.input', return_value='y'), patch.object(launcher.subprocess, 'run') as run:
            with self.assertRaises(RuntimeError):
                launcher.update(self.core, self.bundle)
        run.assert_not_called()

    def test_incomplete_preparation_does_not_reboot(self):
        self.core.status.return_value = {'state': 'failed'}
        with patch('builtins.input', return_value='y'), patch.object(launcher.subprocess, 'run') as run:
            with self.assertRaises(RuntimeError):
                launcher.update(self.core, self.bundle)
        run.assert_not_called()

    def test_current_version_does_not_prompt_or_reboot(self):
        self.bundle.release_state.return_value = 'current'
        with patch('builtins.input') as ask, patch.object(launcher.subprocess, 'run') as run:
            launcher.update(self.core, self.bundle)
        ask.assert_not_called()
        run.assert_not_called()
        self.core.main.assert_not_called()


if __name__ == '__main__':
    main()
