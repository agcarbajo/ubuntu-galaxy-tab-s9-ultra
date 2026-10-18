#!/usr/bin/env python3
"""Exercise late/incomplete PipeWire startup without touching real services."""
from pathlib import Path
import runpy
import subprocess
import unittest

root = Path(__file__).resolve().parents[1]
audio = runpy.run_path(str(root / "packaging/ubuntu-gts9u-device/usr/libexec/ubuntu-gts9u-audio-session"))


class Clock:
    now = 0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def card(hifi=True, active="HiFi"):
    return {"name": audio["CARD"], "index": 66,
            "profiles": {"HiFi": {}} if hifi else {"off": {}, "pro-audio": {}},
            "active_profile": active}


class Fake:
    def __init__(self, clock, available_at=0, ready_at=0, failures=0):
        self.clock = clock
        self.available_at = available_at
        self.ready_at = ready_at
        self.failures = failures
        self.restarts = []
        self.selections = 0
        self.active = "HiFi"
        self.output = True

    def available(self):
        return self.clock.now >= self.available_at

    def state(self):
        if self.failures:
            self.failures -= 1
            raise subprocess.TimeoutExpired("pactl", 6)
        complete = self.clock.now >= self.ready_at
        return ([card(complete, self.active)],
                [{"card": 66, "name": "board-speaker"}] if complete and self.output and self.active != "off" else [])

    def restart(self):
        self.restarts.append(self.clock.now)

    def select_hifi(self):
        self.selections += 1
        self.active = "HiFi"

    def repair_realtime_portal(self):
        return False


class PortalTests(unittest.TestCase):
    def session(self, *, active=True, cached=0, actual=200000, refreshed=200000):
        session = audio["Session"].__new__(audio["Session"])
        session.mutations = []
        session.portal_restarted = False

        def command(*args):
            if args[:3] == ("systemctl", "--user", "show"):
                return "active" if active else "inactive"
            if args[:3] == ("systemctl", "--user", "restart"):
                session.mutations.append(args[3:])
                if args[3:] == ("xdg-desktop-portal.service",):
                    session.portal_restarted = True
                return ""
            if args[:2] == ("busctl", "--user"):
                return "x " + str(refreshed if session.portal_restarted else cached)
            if args[:2] == ("busctl", "--system"):
                return "x " + str(actual)
            raise AssertionError(args)

        session.command = command
        return session

    def test_stale_zero_limit_recreates_audio_processes_once(self):
        session = self.session()
        self.assertTrue(session.repair_realtime_portal())
        self.assertEqual(session.mutations, [
            ("xdg-desktop-portal.service",),
            ("pipewire.service", "pipewire-pulse.service", "wireplumber.service")])
        self.assertFalse(session.repair_realtime_portal())
        self.assertEqual(len(session.mutations), 2)

    def test_inactive_healthy_or_unavailable_rtkit_is_untouched(self):
        for options in ({"active": False}, {"cached": 200000}, {"actual": 0}):
            with self.subTest(options=options):
                session = self.session(**options)
                self.assertFalse(session.repair_realtime_portal())
                self.assertEqual(session.mutations, [])

    def test_failed_refresh_does_not_restart_audio_into_bad_limits(self):
        session = self.session(refreshed=0)
        with self.assertRaises(ValueError):
            session.repair_realtime_portal()
        self.assertEqual(session.mutations, [("xdg-desktop-portal.service",)])


class RecoveryTests(unittest.TestCase):
    def run_recovery(self, fake):
        return audio["recover"](fake, clock=fake.clock.time, sleep=fake.clock.sleep)

    def test_healthy_session_is_untouched(self):
        fake = Fake(Clock())
        self.assertTrue(self.run_recovery(fake))
        self.assertEqual((fake.restarts, fake.selections), ([], 0))

    def test_late_ucm_requires_another_restart(self):
        class Cached(Fake):
            cached = True

            def state(self):
                return ([card(not self.cached)], [] if self.cached else [{"card": 66, "name": "speaker"}])

            def restart(self):
                super().restart()
                self.cached = self.clock.now < 20
        fake = Cached(Clock())
        self.assertTrue(self.run_recovery(fake))
        self.assertEqual(fake.restarts, [0, 16, 46])

    def test_late_user_bus_does_not_burst_restarts(self):
        fake = Fake(Clock(), available_at=90, ready_at=500)
        self.assertFalse(self.run_recovery(fake))
        self.assertEqual(fake.restarts, [90, 106])

    def test_permanent_failure_stops_after_three_restarts(self):
        fake = Fake(Clock(), ready_at=500)
        self.assertFalse(self.run_recovery(fake))
        self.assertEqual(fake.restarts, [0, 16, 46])
        self.assertEqual(fake.clock.now, 120)

    def test_selecting_profile_must_create_an_output(self):
        fake = Fake(Clock())
        fake.active = "off"
        fake.output = False
        self.assertFalse(self.run_recovery(fake))
        self.assertEqual(fake.selections, 1)
        self.assertGreaterEqual(fake.restarts[0], 10)

    def test_off_profile_recovers_without_restart(self):
        fake = Fake(Clock())
        fake.active = "off"
        self.assertTrue(self.run_recovery(fake))
        self.assertEqual((fake.restarts, fake.selections), ([], 1))

    def test_failed_query_is_not_success(self):
        fake = Fake(Clock(), failures=2)
        self.assertTrue(self.run_recovery(fake))
        self.assertEqual(fake.clock.now, 4)

    def test_dummy_or_other_card_is_not_board_output(self):
        ready = audio["ready"]
        self.assertFalse(ready([card()], [{"card": 66, "name": "auto_null"}]))
        self.assertFalse(ready([card()], [{"card": 67, "name": "usb-audio"}]))
        self.assertFalse(ready([card(False)], [{"card": 66, "name": "speaker"}]))
        self.assertTrue(ready([card(active="pro-audio")], [{"card": 66, "name": "speaker"}]))

    def test_real_pipewire_shape_without_pulse_card_index(self):
        # Noble PipeWire's actual pactl JSON omits the sink's top-level card.
        sink = {"name": "alsa_output.platform-sound.HiFi__hw_SamsungGalaxyTa_0__sink",
                "properties": {"device.name": "alsa_card.platform-sound", "alsa.card": "0"}}
        self.assertTrue(audio["ready"]([card()], [sink]))
        sink["properties"]["device.name"] = "alsa_card.usb-headset"
        self.assertFalse(audio["ready"]([card()], [sink]))


if __name__ == "__main__":
    unittest.main()
