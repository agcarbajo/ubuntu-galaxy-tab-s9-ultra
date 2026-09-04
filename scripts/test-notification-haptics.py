#!/usr/bin/env python3
"""Exercise notification routing without opening hardware or vibrating."""
from pathlib import Path
import runpy
import sys
import unittest
from unittest.mock import Mock, patch

source = Path(sys.argv.pop(1)) if len(sys.argv) > 1 else (
    Path(__file__).resolve().parents[1]
    / "packaging/ubuntu-gts9u-companion/usr/libexec/tab-companion-hardware")
module = runpy.run_path(str(source))
Service = module["HardwareService"]


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.service = Service.__new__(Service)
        self.service.settings = Mock()
        self.service.settings.get_boolean.return_value = True
        self.service.haptics = Mock()
        self.service.last_notification_haptic = 0

    def send(self, interface, member, when=10):
        message = Mock()
        message.get_type.return_value = module["dbus"].lowlevel.MESSAGE_TYPE_METHOD_CALL
        message.get_interface.return_value = interface
        message.get_member.return_value = member
        with patch.object(module["time"], "monotonic", return_value=when):
            self.service._notification_bus_message(None, message)

    def test_both_notification_protocols(self):
        self.send("org.freedesktop.Notifications", "Notify")
        self.send("org.gtk.Notifications", "AddNotification", 11)
        self.assertEqual(self.service.haptics.vibrate.call_count, 2)

    def test_disabled_setting(self):
        self.service.settings.get_boolean.return_value = False
        self.send("org.freedesktop.Notifications", "Notify")
        self.send("org.gtk.Notifications", "AddNotification", 11)
        self.service.haptics.vibrate.assert_not_called()

    def test_removal_and_unrelated_calls_do_not_vibrate(self):
        self.send("org.gtk.Notifications", "RemoveNotification")
        self.send("org.freedesktop.Notifications", "CloseNotification")
        self.send("org.example.Unrelated", "AddNotification")
        self.service.haptics.vibrate.assert_not_called()

    def test_forwarded_duplicates_are_collapsed(self):
        self.send("org.gtk.Notifications", "AddNotification")
        self.send("org.gtk.Notifications", "AddNotification", 10.01)
        self.send("org.freedesktop.Notifications", "Notify", 10.02)
        self.service.haptics.vibrate.assert_called_once_with(60, 65535)


if __name__ == "__main__":
    unittest.main()
