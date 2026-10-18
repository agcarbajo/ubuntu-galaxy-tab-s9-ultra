#!/usr/bin/python3
"""Exercise hotplug policy without changing the real display or sound server."""
from pathlib import Path
import runpy
import subprocess
import unittest

source = Path(__file__).resolve().parents[1] / 'packaging/ubuntu-gts9u-device/usr/libexec/ubuntu-gts9u-audio-hotplug'
Recovery = runpy.run_path(str(source))['Recovery']


class Backend:
    connected = True
    active = True
    fail = False

    def __init__(self, profiles=('HiFi',), selected='HiFi'):
        self.state = {'profiles': dict.fromkeys(profiles, {}), 'active_profile': selected}
        self.actions = []

    def display(self):
        return self.connected, self.active

    def card(self):
        return self.state

    def restart(self):
        self.actions.append('reprobe')
        if self.fail:
            raise subprocess.TimeoutExpired('systemctl', 8)

    def select(self, profile):
        self.actions.append(profile)
        self.state['active_profile'] = profile


class Tests(unittest.TestCase):
    def test_missing_profile_is_reprobed_once_per_connection(self):
        backend = Backend()
        recovery = Recovery(backend)
        for _ in range(10):
            recovery.check()
        self.assertEqual(backend.actions, ['reprobe'])
        backend.connected = backend.active = False
        recovery.check()
        backend.connected = backend.active = True
        recovery.check()
        self.assertEqual(backend.actions, ['reprobe', 'reprobe'])

    def test_existing_profile_is_untouched_even_if_jack_unavailable(self):
        backend = Backend(('HiFi', 'HDMI'))
        backend.state['profiles']['HDMI'] = {'available': 'no'}
        Recovery(backend).check()
        self.assertEqual(backend.actions, [])

    def test_off_card_and_untrained_link_are_untouched(self):
        for selected, active in (('off', True), ('HiFi', False)):
            with self.subTest(selected=selected, active=active):
                backend = Backend(selected=selected)
                backend.active = active
                Recovery(backend).check()
                self.assertEqual(backend.actions, [])

    def test_absent_card_is_not_restarted(self):
        backend = Backend()
        backend.state = None
        Recovery(backend).check()
        self.assertEqual(backend.actions, [])

    def test_failed_reprobe_cannot_loop_on_monitor_events(self):
        backend = Backend()
        backend.fail = True
        recovery = Recovery(backend)
        with self.assertRaises(subprocess.TimeoutExpired):
            recovery.check()
        for _ in range(10):
            recovery.check()
        self.assertEqual(backend.actions, ['reprobe'])

    def test_disconnect_returns_hdmi_to_internal_profile(self):
        backend = Backend(('HiFi', 'HDMI'), 'HDMI')
        backend.connected = backend.active = False
        recovery = Recovery(backend)
        recovery.check()
        recovery.check()
        self.assertEqual(backend.actions, ['HiFi'])

    def test_disconnecting_display_preserves_non_hdmi_profiles(self):
        for selected in ('off', 'HiFi', 'pro-audio'):
            backend = Backend(selected=selected)
            backend.connected = backend.active = False
            Recovery(backend).check()
            self.assertEqual(backend.actions, [])


if __name__ == '__main__':
    unittest.main()
