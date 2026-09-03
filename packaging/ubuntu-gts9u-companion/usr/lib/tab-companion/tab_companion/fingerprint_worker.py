# SPDX-License-Identifier: MIT
"""Private fprintd client process; never read templates or change PAM.

Blocking D-Bus calls run only here, not on GTK's main thread. Exiting closes
this private bus connection, releasing a claim even if normal cleanup fails.
"""
import json
import signal
import sys

import dbus
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

from .fingerprint_state import FINGERS, MAX_PRINTS

NAME = "net.reactivated.Fprint"
IFACE = NAME + ".Device"


def emit(event, **fields):
    print(json.dumps(dict(event=event, **fields)), flush=True)


def error_name(error):
    return error.get_dbus_name().rsplit(".", 1)[-1] if isinstance(error, dbus.DBusException) else type(error).__name__


class Client:
    def __init__(self, mode, finger=None):
        self.mode, self.finger = mode, finger
        self.bus = None
        self.device = None
        self.claimed = False
        self.started = False
        self.stopping = False
        self.pending = False
        self.index = 0
        self.prints = []
        self.result = None
        self.loop = GLib.MainLoop()

    def list_prints(self):
        try:
            present = self.device.ListEnrolledFingers("", timeout=15)
            return [f for f in FINGERS if f in present]
        except dbus.DBusException as error:
            if error_name(error) == "NoEnrolledPrints":
                return []
            raise

    def run(self):
        DBusGMainLoop(set_as_default=True)
        try:
            self.bus = dbus.SystemBus(private=True)
            manager = dbus.Interface(self.bus.get_object(NAME, "/net/reactivated/Fprint/Manager"), NAME + ".Manager")
            path = manager.GetDefaultDevice(timeout=65)
            obj = self.bus.get_object(NAME, path)
            self.device = dbus.Interface(obj, IFACE)
            props = dbus.Interface(obj, "org.freedesktop.DBus.Properties")
            self.prints = self.list_prints()
            emit("prints", prints=self.prints)
            if self.mode == "list":
                self.result = dict(status="listed")
                return
            self.device.Claim("", timeout=65)
            self.claimed = True
            # Re-read under the exclusive claim: never replace a finger added
            # by Settings between opening our chooser and pressing Add.
            self.prints = self.list_prints()
            if self.mode == "enroll" and (self.finger in self.prints or len(self.prints) >= MAX_PRINTS):
                self.result = dict(status="failed", error="AlreadyEnrolled")
                return
            if self.mode in ("delete", "scan") and not self.prints:
                self.result = dict(status="failed", error="NoEnrolledPrints")
                return
            if self.mode == "delete":
                if self.finger not in self.prints:
                    self.result = dict(status="failed", error="NoEnrolledPrints")
                    return
                self.device.DeleteEnrolledFinger(self.finger, timeout=30)
                emit("prints", prints=self.list_prints())
                self.result = dict(status="deleted", finger=self.finger)
                return
            self.device.connect_to_signal("EnrollStatus", self.enroll_status)
            self.device.connect_to_signal("VerifyStatus", self.verify_status)
            props.connect_to_signal("PropertiesChanged", self.properties_changed)
            bus_daemon = dbus.Interface(self.bus.get_object("org.freedesktop.DBus", "/org/freedesktop/DBus"), "org.freedesktop.DBus")
            daemon_pid = bus_daemon.GetConnectionUnixProcessID(self.bus.get_name_owner(NAME), timeout=10)
            stages = int(props.Get(IFACE, "num-enroll-stages", timeout=10))
            emit("claimed", pid=int(daemon_pid))
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, self.cancel)
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, self.cancel)
            if self.mode == "enroll":
                self.started = True  # cleanup even after an uncertain Start
                self.device.EnrollStart(self.finger, timeout=30)
            else:
                self.start_candidate()
            emit("ready", stages=max(1, stages))
            self.loop.run()
        except Exception as error:
            self.result = dict(status="failed", error=error_name(error))
        finally:
            self.cleanup()
            emit("result", **(self.result or dict(status="failed", error="Internal")))

    def start_candidate(self):
        # Ubuntu 24.04's fprintd has no VerifyFingerMatched signal. Target each
        # named print to identify it truthfully; never infer identity from a
        # secure slot (slots can collide) or from a journal line. This affects
        # only Companion's scanner, not GNOME's normal VerifyStart("any").
        emit("candidate", finger=self.prints[self.index], index=self.index + 1, count=len(self.prints))
        self.started = True
        self.device.VerifyStart(self.prints[self.index], timeout=30)

    def properties_changed(self, interface, changed, _invalidated):
        if interface == IFACE and "finger-present" in changed and not self.stopping:
            emit("touch" if changed["finger-present"] else "lift")

    def enroll_status(self, result, done):
        if self.mode != "enroll" or self.stopping or self.pending:
            return
        result = str(result)
        emit("progress", result=result)
        if done:
            self.pending = True
            self.result = dict(status="completed" if result == "enroll-completed" else "failed", error=None if result == "enroll-completed" else result)
            GLib.idle_add(self.finish)

    def verify_status(self, result, done):
        if self.mode != "scan" or self.stopping or self.pending:
            return
        result = str(result)
        emit("progress", result=result)
        if not done:
            return
        self.pending = True
        if result == "verify-match":
            self.result = dict(status="matched", finger=self.prints[self.index])
            GLib.idle_add(self.finish)
        elif result == "verify-no-match":
            GLib.idle_add(self.next_candidate)
        else:
            self.result = dict(status="failed", error=result)
            GLib.idle_add(self.finish)

    def next_candidate(self):
        if self.stopping:
            return GLib.SOURCE_REMOVE
        try:
            self.stop_operation()
            self.index += 1
            if self.index == len(self.prints):
                self.result = dict(status="not-matched")
                return self.finish()
            self.pending = False
            self.start_candidate()
        except Exception as error:
            self.result = dict(status="failed", error=error_name(error))
            return self.finish()
        return GLib.SOURCE_REMOVE

    def stop_operation(self):
        if not self.started:
            return
        try:
            if self.mode == "enroll":
                self.device.EnrollStop(timeout=5)
            else:
                self.device.VerifyStop(timeout=5)
        except dbus.DBusException as error:
            if error_name(error) != "NoActionInProgress":
                raise
        self.started = False

    def finish(self):
        self.stopping = True
        self.loop.quit()
        return GLib.SOURCE_REMOVE

    def cancel(self):
        if self.result is None:
            self.result = dict(status="cancelled")
        return self.finish()

    def cleanup(self):
        try:
            self.stop_operation()
        except Exception as error:
            emit("cleanup-error", error=error_name(error))
        try:
            if self.claimed:
                self.device.Release(timeout=5)
                self.claimed = False
        except Exception as error:
            emit("cleanup-error", error=error_name(error))
        finally:
            if self.bus:
                self.bus.close()


def main():
    args = sys.argv[1:]
    if not args or args[0] not in ("list", "enroll", "scan", "delete"):
        raise SystemExit(2)
    mode = args[0]
    finger = args[1] if len(args) == 2 else None
    if (mode in ("enroll", "delete") and finger not in FINGERS) or len(args) > 2:
        raise SystemExit(2)
    Client(mode, finger).run()


if __name__ == "__main__":
    main()
