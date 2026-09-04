#!/usr/bin/env python3
import importlib.util
from pathlib import Path
from unittest import TestCase, main
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('launcher', Path(__file__).with_name('update-to-latest.py'))
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class LauncherTests(TestCase):
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
