#!/usr/bin/env python3
"""Pure state + real Gio worker on private synthetic D-Bus; no biometric data."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packaging/ubuntu-gts9u-companion/usr/lib/tab-companion"))
from gi.repository import GLib
import dbus
from tab_companion.fingerprint_state import FingerprintState, FINGERS, MAX_PRINTS
from tab_companion.fingerprint import FingerprintManager


class StateTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.state = FingerprintState("enroll", clock=lambda: self.now)

    def test_ten_unique_fingers(self):
        self.assertEqual(MAX_PRINTS, 10)
        self.assertEqual(len(set(FINGERS)), 10)

    def test_retry_feedback_survives_lift(self):
        self.state.event(dict(event="progress", result="enroll-retry-scan"))
        self.state.event(dict(event="lift"))
        self.assertEqual(self.state.data["feedback"], "retry")

    def test_inactivity_renews_on_touch(self):
        self.now = 29
        self.assertEqual(self.state.remaining(), 1)
        self.state.event({"event": "touch"})
        self.now = 58
        self.assertEqual(self.state.remaining(), 1)
        self.now = 59
        self.assertEqual(self.state.remaining(), 0)

    def test_long_session_has_no_total_deadline(self):
        for i in range(200):
            self.now = i * 25
            self.state.touch()
        self.assertEqual(self.state.remaining(), 30)

    def test_progress_does_not_fake_contact(self):
        self.now = 29
        self.state.event({"event": "progress", "result": "enroll-stage-passed"})
        self.assertEqual(self.state.remaining(), 1)
        self.assertEqual(self.state.data["accepted"], 0)
        self.assertEqual(self.state.data["stages"], 0)

    def test_duplicate_journal_contact_does_not_extend(self):
        line = "EL721 contact pressed=1 released=0 sequence=1 delta=1"
        self.state.journal(line)
        self.now = 29
        self.state.journal(line)
        self.assertEqual(self.state.remaining(), 1)

    def test_quality_contacts_renew(self):
        self.now = 29
        self.state.journal("EL721 contact pressed=1 released=0 sequence=2 delta=1")
        self.assertEqual(self.state.remaining(), 30)

    def test_secure_aggregates(self):
        self.state.journal("EL721 sample result=0 final=0 coverage=62 accepted=10 template=0")
        self.assertEqual(self.state.data["accepted"], 10)
        self.assertEqual(self.state.data["coverage"], 62)
        self.assertEqual(self.state.data["status"], "starting")

    def test_journal_never_authenticates(self):
        self.state.journal("EL721 verify result=0 final=0 matched_slot=3")
        self.assertNotEqual(self.state.data["status"], "matched")

    def test_candidate_is_not_a_match(self):
        self.state.event(dict(event="candidate", finger=FINGERS[0], index=1, count=2))
        self.assertIsNone(self.state.data.get("matched_finger"))

    def test_no_match_is_not_service_error(self):
        self.state.event(dict(event="result", status="not-matched"))
        self.assertEqual(self.state.data["status"], "not-matched")


class WorkerTests(unittest.TestCase):
    scenario = "match"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="companion-fingerprint-")
        self.old_address = os.environ.get("DBUS_SYSTEM_BUS_ADDRESS")
        self.old_state = os.environ.get("XDG_STATE_HOME")
        self.daemon = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--print-address=1", "--address=unix:path=" + self.temp.name + "/bus"], stdout=subprocess.PIPE, text=True)
        os.environ["DBUS_SYSTEM_BUS_ADDRESS"] = self.daemon.stdout.readline().strip()
        os.environ["XDG_STATE_HOME"] = self.temp.name
        self.fake = subprocess.Popen([sys.executable, str(ROOT / "scripts/fixtures/fprintd-companion.py"), self.scenario], stdout=subprocess.PIPE, text=True)
        self.assertEqual(self.fake.stdout.readline().strip(), "READY")
        self.bus = dbus.bus.BusConnection(os.environ["DBUS_SYSTEM_BUS_ADDRESS"])
        self.obj = self.bus.get_object("net.reactivated.Fprint", "/net/reactivated/Fprint/Device/0")
        self.control = dbus.Interface(self.obj, "io.test.Control")
        self.device = dbus.Interface(self.obj, "net.reactivated.Fprint.Device")

    def tearDown(self):
        self.bus.close()
        for process in (self.fake, self.daemon):
            process.terminate()
            process.wait(timeout=5)
            process.stdout.close()
        for key, old in (("DBUS_SYSTEM_BUS_ADDRESS", self.old_address), ("XDG_STATE_HOME", self.old_state)):
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old
        self.temp.cleanup()

    def operation(self, mode, finger=None, cancel=False, expire=False):
        loop = GLib.MainLoop()
        result = []
        manager = FingerprintManager(lambda state: None, lambda state: (result.append(state), loop.quit()))
        with patch.object(GLib, "get_user_state_dir", return_value=self.temp.name):
            manager.start(mode, finger)
        if cancel or expire:
            def act():
                if manager.state.data["status"] != "running":
                    return True
                if cancel:
                    manager.stop()
                else:
                    manager.state.deadline = 0
                return False
            GLib.timeout_add(30, act)
        timeout = GLib.timeout_add_seconds(8, lambda: (loop.quit(), False)[1])
        loop.run()
        GLib.source_remove(timeout)
        self.assertTrue(result, "Worker did not finish")
        self.assertFalse(self.control.Claimed(), "Device claim leaked")
        return result[0], manager

    def test_list_never_claims(self):
        state, _ = self.operation("list")
        self.assertEqual(state["status"], "listed")
        self.assertEqual(len(state["prints"]), 2)
        self.assertEqual(list(self.control.Calls()), [])

    def test_identifies_second_finger_without_changing_prints(self):
        state, manager = self.operation("scan")
        self.assertEqual(state["status"], "matched")
        self.assertEqual(state["matched_finger"], "left-index-finger")
        self.assertEqual(list(self.device.ListEnrolledFingers("")), list(FINGERS[:2]))
        self.assertEqual(list(self.control.Calls()), ["Claim", "Verify:right-index-finger", "VerifyStop", "Verify:left-index-finger", "VerifyStop", "Release"])
        self.assertEqual(os.stat(manager.log_path).st_mode & 0o777, 0o600)

    def test_add_unused_finger(self):
        state, _ = self.operation("enroll", "right-thumb")
        self.assertEqual(state["status"], "completed")
        self.assertIn("right-thumb", self.device.ListEnrolledFingers(""))
        self.assertIn("EnrollStop", self.control.Calls())

    def test_add_existing_never_replaces(self):
        state, _ = self.operation("enroll", "right-index-finger")
        self.assertEqual(state["error"], "AlreadyEnrolled")
        self.assertFalse(any(c.startswith("Enroll:") for c in self.control.Calls()))

    def test_delete_only_named_print(self):
        state, _ = self.operation("delete", "left-index-finger")
        self.assertEqual(state["status"], "deleted")
        self.assertEqual(list(self.device.ListEnrolledFingers("")), ["right-index-finger"])


class CancellationTests(WorkerTests):
    scenario = "wait"
    test_identifies_second_finger_without_changing_prints = None
    test_add_unused_finger = None

    def test_cancel_enroll_preserves_prints(self):
        state, manager = self.operation("enroll", "right-thumb", cancel=True)
        self.assertEqual(state["status"], "cancelled")
        self.assertEqual(len(self.device.ListEnrolledFingers("")), 2)
        self.assertIn('"status": "cancelled"', Path(manager.log_path).read_text())

    def test_idle_scan_timeout(self):
        state, _ = self.operation("scan", expire=True)
        self.assertEqual(state["status"], "timeout")
        self.assertIn("VerifyStop", self.control.Calls())


class RejectionTests(WorkerTests):
    scenario = "reject"
    test_identifies_second_finger_without_changing_prints = None

    def test_all_fingers_reject(self):
        state, _ = self.operation("scan")
        self.assertEqual(state["status"], "not-matched")
        self.assertIsNone(state["matched_finger"])


class CapacityTests(WorkerTests):
    scenario = "full"
    test_add_existing_never_replaces = None
    test_add_unused_finger = None
    test_delete_only_named_print = None
    test_identifies_second_finger_without_changing_prints = None
    test_list_never_claims = None

    def test_ten_listed_and_eleventh_cannot_replace(self):
        state, _ = self.operation("list")
        self.assertEqual(len(state["prints"]), 10)
        state, _ = self.operation("enroll", "left-thumb")
        self.assertEqual(state["error"], "AlreadyEnrolled")
        self.assertEqual(len(self.device.ListEnrolledFingers("")), 10)

    def test_ten_candidates_exhaust_without_wrap(self):
        state, _ = self.operation("scan")
        self.assertEqual(state["status"], "not-matched")
        self.assertEqual(len([c for c in self.control.Calls() if c.startswith("Verify:")]), 10)


class ErrorTests(CapacityTests):
    scenario = "error"
    test_ten_listed_and_eleventh_cannot_replace = None
    test_ten_candidates_exhaust_without_wrap = None

    def test_error_does_not_advance_or_reject(self):
        state, _ = self.operation("scan")
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["error"], "verify-unknown-error")
        self.assertEqual(len([c for c in self.control.Calls() if c.startswith("Verify:")]), 1)


if __name__ == "__main__":
    unittest.main()
