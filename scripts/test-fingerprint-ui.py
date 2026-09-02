#!/usr/bin/python3
"""Pure broker authorization tests, no system bus or sensor access."""
from pathlib import Path
import runpy
import unittest

module = runpy.run_path(str(Path(__file__).resolve().parents[1] /
    'packaging/ubuntu-gts9u-device/usr/libexec/ubuntu-gts9u-fingerprint-ui'))
authorize = module['authorized']


class PolicyTest(unittest.TestCase):
    def setUp(self):
        self.props = dict(Active=True, Remote=False, Type='wayland', Class='user',
                          Seat=('seat0', '/seat'), User=(1000, '/user'))

    def test_local_user(self):
        self.assertTrue(authorize(1000, '104', '104', self.props))

    def test_greeter(self):
        self.props.update(Class='greeter', User=(108, '/user'))
        self.assertTrue(authorize(108, 'c2', 'c2', self.props))

    def test_x11(self):
        self.props['Type'] = 'x11'
        self.assertTrue(authorize(1000, '104', '104', self.props))

    def test_wrong_uid_including_root(self):
        for uid in (0, 108, 1001):
            self.assertFalse(authorize(uid, '104', '104', self.props))

    def test_wrong_session(self):
        for session in ('', '103', '105'):
            self.assertFalse(authorize(1000, session, '104', self.props))

    def test_invalid_properties(self):
        for key, value in (('Active', False), ('Remote', True), ('Type', 'tty'),
                           ('Class', 'background'), ('Seat', ('seat1', '/seat'))):
            with self.subTest(key=key):
                self.assertFalse(authorize(1000, '104', '104', {**self.props, key: value}))

    def test_missing_properties(self):
        for key in self.props:
            props = self.props.copy()
            props.pop(key)
            self.assertFalse(authorize(1000, '104', '104', props), key)

    def test_lease_has_no_identity_or_result(self):
        self.assertEqual(module['lease_text'](True, 123456), 'ready 123456\n')
        self.assertEqual(module['lease_text'](False, 123456), 'blocked 123456\n')


if __name__ == '__main__':
    unittest.main()
