#!/usr/bin/env python3
"""Only synthetic events; never opens an input device or starts a live capture."""
from pathlib import Path
import runpy
import sys
from unittest.mock import patch

source = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "packaging/ubuntu-gts9u-companion/usr/libexec/tab-companion-hardware"
module = runpy.run_path(str(source))
capture = module["KeyboardCapture"]()
with patch.object(module["time"], "monotonic", return_value=100):
    capture.record(30, 1)
    assert not capture.events
    capture.begin(":test-owner")
    capture.record(30, 1)
with patch.object(module["time"], "monotonic", return_value=119.999):
    capture.record(30, 2)
    capture.record(30, 0)
with patch.object(module["time"], "monotonic", return_value=120):
    capture.record(31, 1)
    assert len(capture.events) == 3
    try:
        capture.finish(":other-caller")
        raise AssertionError("Another caller could retrieve the keys")
    except ValueError:
        pass
    report = capture.finish(":test-owner")
    assert [e["value"] for e in report["events"]] == [1, 2, 0]
    assert capture.owner is None and not capture.events
    capture.record(32, 1)
    assert not capture.events
    capture.begin(":test-owner")
    for _ in range(10001):
        capture.record(30, 1)
    assert len(capture.events) == 10000 and capture.dropped == 1
    capture.clear()
    assert not capture.events and capture.owner is None
print("PASS opt-in capture, 20-second deadline, press/release/repeat, caller isolation, clearing and size cap")
