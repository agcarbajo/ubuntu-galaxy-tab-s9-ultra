#!/usr/bin/python3
"""Pure broker authorization tests, no system bus or sensor access."""
from pathlib import Path
import runpy
import unittest
import tempfile
import types
import sys
from unittest.mock import Mock, patch

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


class BrokerLifecycleTest(unittest.TestCase):
    """Exercise the real broker methods with a private fake bus and lease."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.lease = Path(self.temp.name) / 'ready'
        service = types.ModuleType('dbus.service')
        service.Object = type('Object', (), {'__init__': lambda *_: None})
        service.BusName = Mock()
        service.method = lambda *a, **kw: lambda f: f
        dbus = types.ModuleType('dbus')
        dbus.service = service
        dbus.DBusException = type('DBusException', (Exception,), {'__init__': lambda self, *a, **kw: Exception.__init__(self, *a)})
        dbus.exceptions = dbus
        self.bus = Mock()
        dbus.SystemBus = lambda: self.bus
        self.daemon = Mock()
        self.daemon.GetConnectionUnixUser.return_value = 1000
        dbus.Interface = lambda *a: self.daemon
        glib = Mock(SOURCE_CONTINUE=True)
        fake_modules = {'dbus': dbus, 'dbus.service': service,
                        'dbus.mainloop': types.ModuleType('dbus.mainloop'),
                        'dbus.mainloop.glib': types.SimpleNamespace(DBusGMainLoop=Mock()),
                        'gi.repository': types.SimpleNamespace(GLib=glib)}
        self.patcher = patch.dict(sys.modules, fake_modules)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.globals_patch = patch.dict(module['main'].__globals__, LEASE=self.lease)
        self.globals_patch.start()
        self.addCleanup(self.globals_patch.stop)
        self.broker = module['main']()
        self.props = dict(Active=True, Remote=False, Type='wayland', Class='user',
                          Seat=('seat0', '/seat'), User=(1000, '/user'))
        self.broker.active = Mock(return_value=('104', self.props))
        self.broker.Pulse('104', True, sender=':1.5')

    def test_timer_does_not_query_logind(self):
        self.broker.active.reset_mock()
        for _ in range(8):
            self.assertTrue(self.broker.tick())
        self.broker.active.assert_not_called()
        self.assertTrue(self.lease.exists())

    def test_expiry_still_fails_closed(self):
        self.broker.client = (*self.broker.client[:3], 0)
        self.broker.tick()
        self.assertFalse(self.lease.exists())
        self.assertIsNone(self.broker.client)

    def test_pulse_checks_live_authorization_every_time(self):
        self.broker.active.return_value = ('105', self.props)
        with self.assertRaises(Exception):
            self.broker.Pulse('104', True, sender=':1.5')
        self.assertEqual(self.daemon.GetConnectionUnixUser.call_count, 2)

    def test_seat_change_revokes_lease(self):
        self.broker.active.return_value = ('105', self.props)
        self.broker.session_changed('org.freedesktop.login1.Seat', {'ActiveSession': ('105', '/s')}, [])
        self.assertFalse(self.lease.exists())

    def test_invalidated_session_properties_revalidate(self):
        self.broker.active.return_value = ('104', {**self.props, 'Active': False})
        self.broker.session_changed('org.freedesktop.login1.Session', {}, ['Active'])
        self.assertFalse(self.lease.exists())

    def test_irrelevant_signal_does_not_query_logind(self):
        self.broker.active.reset_mock()
        self.broker.session_changed('org.freedesktop.login1.Session', {'IdleHint': True}, [])
        self.broker.active.assert_not_called()

    def test_logind_disconnect_revokes_lease(self):
        self.broker.disconnected('org.freedesktop.login1', ':1.1', '')
        self.assertFalse(self.lease.exists())

    def test_client_disconnect_revokes_lease(self):
        self.broker.disconnected(':1.5', ':1.5', '')
        self.assertFalse(self.lease.exists())

    def test_session_removal_revokes_lease(self):
        self.broker.session_removed('104', '/s')
        self.assertFalse(self.lease.exists())


if __name__ == '__main__':
    unittest.main()
