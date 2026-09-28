#!/usr/bin/env python3
"""Temporary-file tests; no network, systemd activation or tablet writes."""
import json
import hashlib
import io
import os
from pathlib import Path
import sys
import tempfile
import zipfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] /
                      "packaging/ubuntu-gts9u-companion/usr/lib/tab-companion"))
from tab_companion import update_policy as p, update_monitor as m, update_core as core


class PolicyTests(unittest.TestCase):
    def plan(self, **changes):
        return {"format": 2, "minimum_updater_protocol": 2, "minimum_port_version": "1.3.0",
                "suite": "noble", "source_suites": ["noble"], "update_kind": "kernel",
                "data_policy": "preserve", **changes}

    def test_legacy_contract_preserved(self):
        p.check_installed({"format": 1, "suite": "noble"}, "noble")
        with self.assertRaises(ValueError):
            p.check_installed({"format": 1, "suite": "noble"}, "resolute")

    def test_future_same_suite_and_kernel_version_not_hardcoded(self):
        p.check_installed(self.plan(suite="resolute", source_suites=["resolute"]), "resolute", "1.4.0")

    def test_bridge_release_required(self):
        for installed in ("1.2.0", "", None):
            with patch("tab_companion.update_bundle.current", return_value={}):
                with self.assertRaisesRegex(ValueError, "1.3.0"):
                    p.check_installed(self.plan(), "noble", installed)
        p.check_installed(self.plan(), "noble", "1.3.0")

    def test_local_zip_downgrade_is_rejected_too(self):
        with self.assertRaisesRegex(ValueError, "Downgrades"):
            p.check_installed({"format": 1, "suite": "noble", "version": "1.2.0"}, "noble", "1.3.0")

    def test_distribution_never_inferred_from_metadata(self):
        with self.assertRaisesRegex(ValueError, "full-system recovery"):
            p.check_installed(self.plan(update_kind="distribution", suite="resolute"), "noble", "1.3.0")
        with self.assertRaises(ValueError):
            p.check_installed(self.plan(suite="resolute", source_suites=["noble", "resolute"]), "noble", "1.3.0")

    def test_explicit_handoff_contract_and_offline_refusal(self):
        plan = self.plan(update_kind="distribution", suite="resolute",
            backend_strategy="official-release-backend-v1", backend_file="UPDATE/updater.pyz",
            backend_entry_protocol=1, recovery="full-system-root-v1")
        p.check_installed(plan, "noble", "1.3.0", allow_handoff=True)
        with self.assertRaisesRegex(ValueError, "verified release backend"):
            p.check_installed(plan, "noble", "1.3.0")

    def test_unknown_protocol_and_unsafe_fields(self):
        for field, value in (("format", 3), ("minimum_updater_protocol", 3),
                             ("minimum_updater_protocol", True), ("suite", "../etc"),
                             ("suite", 26), ("source_suites", []), ("update_kind", "script"),
                             ("data_policy", "replace"), ("minimum_port_version", "--force")):
            with self.subTest(field=field), self.assertRaises(ValueError):
                p.validate(self.plan(**{field: value}))

    def test_os_release_is_parsed_without_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "os-release"
            path.write_text('ID=ubuntu\nUBUNTU_CODENAME=resolute\nVERSION_ID="26.04"\n')
            self.assertEqual(p.ubuntu_suite(path), "resolute")
            path.write_text('ID=ubuntu\nUBUNTU_CODENAME="$(touch /tmp/unsafe)"\n')
            with self.assertRaises(ValueError):
                p.ubuntu_suite(path)


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, XDG_CACHE_HOME=self.tmp.name)
        self.env.start()
        self.current = patch.object(m.bundle, "current", return_value={"version": "1.3.0", "tag": "v1.3.0"})
        self.current.start()
        self.info = {"tag": "v1.4.0", "supports_updates": True, "sha256": "a" * 64}

    def tearDown(self):
        self.current.stop()
        self.env.stop()
        self.tmp.cleanup()

    def test_once_per_week_and_clock_change(self):
        value, _ = m.record(self.info, now=1000)
        self.assertFalse(m.due(value, 1000 + m.WEEK - 1))
        self.assertTrue(m.due(value, 1000 + m.WEEK))
        self.assertTrue(m.due(value, 900))
        self.assertTrue(m.due({"checked_at": "bad"}, 1000))

    def test_badge_survives_restart_but_clears_after_update(self):
        m.record(self.info)
        self.assertTrue(m.available(m.load()))
        with patch.object(m.bundle, "current", return_value={"version": "1.4.0", "tag": "v1.4.0"}):
            self.assertFalse(m.available(m.load()))

    def test_notification_dedup_and_new_asset(self):
        _, key = m.record(self.info, notify=True)
        self.assertIsNotNone(key)
        m.notified(key)
        self.assertIsNone(m.record(self.info, notify=True)[1])
        self.assertIsNotNone(m.record({**self.info, "sha256": "b" * 64}, notify=True)[1])

    def test_unknown_current_and_unsupported_do_not_notify(self):
        with patch.object(m.bundle, "current", return_value={}):
            self.assertIsNone(m.record(self.info, notify=True)[1])
        self.assertIsNone(m.record({**self.info, "supports_updates": False}, notify=True)[1])

    def test_manual_check_does_not_consume_notification(self):
        m.record(self.info)
        self.assertIsNotNone(m.record(self.info, notify=True)[1])

    def test_corrupt_cache_and_user_only_permissions(self):
        m.record(self.info)
        self.assertEqual(m.cache_path().stat().st_mode & 0o777, 0o600)
        m.cache_path().write_text("not json")
        self.assertEqual(m.load(), {})


class HandoffTests(unittest.TestCase):
    """exec is intercepted: no bundled code is ever executed by these tests."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        memory = io.BytesIO()
        with zipfile.ZipFile(memory, "w") as program:
            program.writestr("__main__.py", "raise RuntimeError('fixture must never run')\n")
        self.backend = memory.getvalue()
        self.archive = self.root / "release.zip"
        with zipfile.ZipFile(self.archive, "w") as archive:
            archive.writestr("UPDATE/updater.pyz", self.backend)
        self.manifest = {"tag": "v1.4.0", "files": {"UPDATE/updater.pyz": {
            "size": len(self.backend), "sha256": hashlib.sha256(self.backend).hexdigest()}}}
        self.info = {"tag": "v1.4.0", "supports_updates": True,
                     "size": self.archive.stat().st_size, "sha256": m.bundle.sha256(self.archive)}

    def tearDown(self):
        self.tmp.cleanup()

    def test_foreign_or_modified_local_zip_never_executes(self):
        for field, value in (("sha256", "0" * 64), ("tag", "v1.3.0"),
                             ("supports_updates", False), ("size", 1)):
            with patch.object(core, "STATE", self.root), patch.object(core.os, "execv") as execute:
                with self.assertRaises(ValueError):
                    core.handoff_release_backend(self.archive, self.manifest, {**self.info, field: value})
                execute.assert_not_called()
                self.assertFalse((self.root / "handoff").exists())

    def test_authenticated_backend_is_retained_and_exec_uses_fixed_arguments(self):
        class Dispatched(BaseException):
            pass
        with patch.object(core, "STATE", self.root), patch.object(core, "run") as run, \
             patch.object(core, "owned_directory", side_effect=lambda path: path.mkdir()), \
             patch.dict(os.environ, {"GTS9U_UPDATER_HANDOFF": ""}), \
             patch.object(core.bundle, "release", return_value=self.info) as official, \
             patch.object(core.os, "execv", side_effect=Dispatched) as execute:
            with self.assertRaises(Dispatched):
                core.handoff_release_backend(self.archive, self.manifest)
            official.assert_called_once_with("v1.4.0")
            run.assert_not_called()
            executable, argv = execute.call_args.args
            self.assertEqual(executable, "/usr/bin/python3")
            self.assertEqual(argv[2], "--zip")
            self.assertEqual(Path(argv[1]).read_bytes(), self.backend)
            self.assertEqual(Path(argv[3]).read_bytes(), self.archive.read_bytes())
            self.assertEqual(Path(argv[3]).stat().st_mode & 0o777, 0o600)

    def test_recursive_handoff_is_blocked(self):
        with patch.dict(os.environ, {"GTS9U_UPDATER_HANDOFF": self.info["sha256"]}), \
             patch.object(core.os, "execv") as execute:
            with self.assertRaisesRegex(ValueError, "recursive"):
                core.handoff_release_backend(self.archive, self.manifest, self.info)
            execute.assert_not_called()

    def test_inner_backend_digest_is_verified_too(self):
        self.manifest["files"]["UPDATE/updater.pyz"]["sha256"] = "0" * 64
        with patch.object(core.os, "execv") as execute:
            with self.assertRaisesRegex(ValueError, "checksum"):
                core.handoff_release_backend(self.archive, self.manifest, self.info)
            execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
