#!/usr/bin/env python3
"""Offline tests: no D-Bus, sensor, biometric input or installed GI required."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest

fake_glib = types.SimpleNamespace(get_user_name=lambda: "synthetic-user")
gi = types.ModuleType("gi")
gi.repository = types.SimpleNamespace(Gio=types.SimpleNamespace(), GLib=fake_glib)
sys.modules["gi"] = gi
sys.modules["gi.repository"] = gi.repository
source = Path(__file__).resolve().parents[1] / "packaging/ubuntu-gts9u-companion/usr/lib/tab-companion/tab_companion/fingerprint_test.py"
spec = importlib.util.spec_from_file_location("fingerprint_test", source)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class FingerprintTests(unittest.TestCase):
    def setUp(self):
        self.test = mod.FingerprintTest(lambda state: None, lambda state: None)
        self.test.state = dict(mode="verify", retries=0, verify_result=None, verify_done=False)

    def result(self, text, code=0):
        self.test._consume("client", text)
        return mod.final_status(self.test.state, code, None)

    def test_verify_never_enrolls(self):
        self.assertEqual(mod.test_command("verify")[3:],
                         ["fprintd-verify", "-f", "right-index-finger", "synthetic-user"])

    def test_enroll_explicit(self):
        self.assertEqual(mod.test_command("enroll")[3], "fprintd-enroll")

    def test_invalid_mode(self):
        with self.assertRaises(ValueError):
            mod.test_command("delete")

    def test_match(self):
        self.assertEqual(self.result("Verify result: verify-match (done)"), "matched")

    def test_nonmatch(self):
        self.assertEqual(self.result("Verify result: verify-no-match (done)", 1), "not-matched")

    def test_error_not_rejection(self):
        self.assertEqual(self.result("Verify result: verify-unknown-error (done)", 1), "failed")

    def test_exit_zero_insufficient(self):
        self.assertEqual(mod.final_status(self.test.state, 0, None), "failed")

    def test_not_done_insufficient(self):
        self.assertEqual(self.result("Verify result: verify-match (not done)"), "failed")

    def test_match_with_cleanup_error(self):
        self.assertEqual(self.result("Verify result: verify-match (done)", 1), "failed")

    def test_journal_cannot_report_match(self):
        self.test._consume("journal", "Verify result: verify-match (done)")
        self.assertEqual(mod.final_status(self.test.state, 0, None), "failed")

    def test_retry_counter(self):
        for status in mod.VERIFY_RETRIES:
            self.test._consume("client", f"Verify result: {status} (not done)")
        self.assertEqual(self.test.state["retries"], 4)
        self.assertFalse(self.test.state["verify_done"])

    def test_cancel_wins(self):
        self.result("Verify result: verify-match (done)")
        self.assertEqual(mod.final_status(self.test.state, 0, "cancelled"), "cancelled")

    def test_timeout_wins(self):
        self.assertEqual(mod.final_status(self.test.state, None, "timeout"), "timeout")

    def test_enroll_signal_ignored_in_verify(self):
        self.test._consume("client", "Enroll result: enroll-completed")
        self.assertEqual(mod.final_status(self.test.state, 0, None), "failed")

    def test_enroll_aggregates(self):
        self.test.state.update(mode="enroll", stage=0)
        self.test._consume("journal", "EL721 sample result=0 final=0 coverage=100 accepted=17 template=1000")
        self.assertEqual(self.test.state["accepted"], 17)
        self.assertEqual(self.test.state["template_bytes"], 1000)
        self.assertEqual(mod.final_status(self.test.state, 0, None), "completed")

    def test_late_verdict_replaces_early_failure(self):
        self.assertEqual(mod.final_status(self.test.state, 1, None), "failed")
        self.assertEqual(self.result("Verify result: verify-no-match (done)", 1), "not-matched")


if __name__ == "__main__":
    unittest.main()
