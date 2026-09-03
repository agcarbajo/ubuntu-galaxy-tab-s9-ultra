#!/usr/bin/env python3
"""Synthetic fprintd ONLY for an isolated test bus, never the real system bus."""
import os
import sys
import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

if not os.environ.get("DBUS_SYSTEM_BUS_ADDRESS", "").startswith("unix:path=/tmp/"):
    raise SystemExit("Refusing to mock the real system bus")
DBusGMainLoop(set_as_default=True)
bus = dbus.SystemBus(private=True)
name = dbus.service.BusName("net.reactivated.Fprint", bus)
IFACE = "net.reactivated.Fprint.Device"


class Manager(dbus.service.Object):
    @dbus.service.method("net.reactivated.Fprint.Manager", out_signature="o")
    def GetDefaultDevice(self):
        return "/net/reactivated/Fprint/Device/0"


class Device(dbus.service.Object):
    def __init__(self):
        super().__init__(bus, "/net/reactivated/Fprint/Device/0")
        self.owner = None
        self.operation = None
        self.scenario = sys.argv[1]
        self.prints = ["right-index-finger", "left-index-finger"]
        if self.scenario == "full":
            self.prints = [hand + "-" + digit for hand in ("right", "left") for digit in ("thumb", "index-finger", "middle-finger", "ring-finger", "little-finger")]
        self.calls = []
        bus.add_signal_receiver(self.owner_changed, "NameOwnerChanged", "org.freedesktop.DBus")

    def owner_changed(self, name, old, new):
        if name == self.owner and not new:
            self.owner = self.operation = None

    @dbus.service.method(IFACE, in_signature="s", out_signature="as")
    def ListEnrolledFingers(self, _user):
        return self.prints

    @dbus.service.method(IFACE, in_signature="s", sender_keyword="sender")
    def Claim(self, user, sender=None):
        if user != "":
            raise RuntimeError("Only current user allowed")
        if self.owner:
            raise dbus.DBusException("claimed", name=IFACE.rsplit(".", 1)[0] + ".Error.AlreadyInUse")
        self.owner = sender
        self.calls.append("Claim")

    @dbus.service.method(IFACE)
    def Release(self):
        self.calls.append("Release")
        self.owner = self.operation = None

    @dbus.service.method(IFACE, in_signature="s")
    def DeleteEnrolledFinger(self, finger):
        self.calls.append("Delete:" + finger)
        self.prints.remove(finger)

    @dbus.service.method(IFACE, in_signature="s")
    def EnrollStart(self, finger):
        self.calls.append("Enroll:" + finger)
        self.operation = "enroll"
        if self.scenario != "wait":
            GLib.timeout_add(40, self.enroll_done, finger)

    def enroll_done(self, finger):
        self.PropertiesChanged(IFACE, {"finger-present": True}, [])
        self.EnrollStatus("enroll-stage-passed", False)
        self.EnrollStatus("enroll-retry-scan", False)
        self.prints.append(finger)
        self.EnrollStatus("enroll-completed", True)
        return False

    @dbus.service.method(IFACE)
    def EnrollStop(self):
        self.calls.append("EnrollStop")
        self.operation = None

    @dbus.service.method(IFACE, in_signature="s")
    def VerifyStart(self, finger):
        self.calls.append("Verify:" + finger)
        self.operation = "verify"
        if self.scenario != "wait":
            GLib.timeout_add(40, self.verify_done, finger)

    def verify_done(self, finger):
        self.PropertiesChanged(IFACE, {"finger-present": True}, [])
        if self.scenario == "error":
            self.VerifyStatus("verify-unknown-error", True)
            return False
        self.VerifyStatus("verify-match" if self.scenario == "match" and finger == "left-index-finger" else "verify-no-match", True)
        return False

    @dbus.service.method(IFACE)
    def VerifyStop(self):
        self.calls.append("VerifyStop")
        self.operation = None

    @dbus.service.method("org.freedesktop.DBus.Properties", in_signature="ss", out_signature="v")
    def Get(self, _interface, prop):
        return dbus.Int32(18) if prop == "num-enroll-stages" else dbus.Boolean(False)

    @dbus.service.method("io.test.Control", out_signature="as")
    def Calls(self):
        return self.calls

    @dbus.service.method("io.test.Control", out_signature="b")
    def Claimed(self):
        return bool(self.owner)

    @dbus.service.signal(IFACE, signature="sb")
    def EnrollStatus(self, result, done):
        pass

    @dbus.service.signal(IFACE, signature="sb")
    def VerifyStatus(self, result, done):
        pass

    @dbus.service.signal("org.freedesktop.DBus.Properties", signature="sa{sv}as")
    def PropertiesChanged(self, interface, changed, invalidated):
        pass


manager = Manager(bus, "/net/reactivated/Fprint/Manager")
device = Device()
print("READY", flush=True)
GLib.MainLoop().run()
