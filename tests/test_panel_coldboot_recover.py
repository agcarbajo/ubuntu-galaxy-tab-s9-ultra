"""Exercise the shell helper against a simulated PM sysfs write failure."""
import pathlib
import subprocess
import tempfile
import unittest


HELPER = pathlib.Path(__file__).resolve().parents[1] / (
    "packaging/ubuntu-gts9u-device/usr/libexec/ubuntu-gts9u-panel-coldboot-recover"
)


class PanelRecoveryTest(unittest.TestCase):
    def run_case(self, failure, failures, expected_attempts, expected_status):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            for name, content in (("test", "[none] platform"), ("state", ""),
                                  ("freeze", "0"), ("attempts", "0")):
                (root / name).write_text(content)
            script = HELPER.read_text()
            for old, new in (("/sys/power/pm_test", "test"),
                             ("/sys/power/state", "state"),
                             ("/sys/power/suspend_stats/failed_freeze", "freeze")):
                script = script.replace(old, str(root / new))
            # Simulate the kernel returning EIO from the state write, with
            # either a freezer failure or a device failure in suspend_stats.
            prelude = f"""
echo() {{
    if [ "$*" = mem ]; then
        n=$(cat '{root}/attempts'); n=$((n + 1))
        printf '%s' "$n" > '{root}/attempts'
        if [ "$n" -le {failures} ]; then
            if [ '{failure}' = freeze ]; then
                printf '%s' "$n" > '{root}/freeze'
            fi
            return 1
        fi
    fi
    printf '%s\\n' "$*"
}}
sleep() {{ :; }}
dmesg() {{ :; }}
"""
            result = subprocess.run(["/bin/sh"], input=prelude + script,
                                    text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, expected_status, result.stderr)
            self.assertEqual(int((root / "attempts").read_text()), expected_attempts)
            self.assertEqual((root / "test").read_text().strip(), "none")

    def test_success_does_not_repeat_cycle(self):
        self.run_case("freeze", 0, 1, 0)

    def test_aborted_freeze_is_retried(self):
        self.run_case("freeze", 1, 2, 0)

    def test_retry_limit_restores_pm_test(self):
        self.run_case("freeze", 9, 3, 1)

    def test_device_failure_is_not_retried(self):
        self.run_case("device", 1, 1, 1)


if __name__ == "__main__":
    unittest.main()
