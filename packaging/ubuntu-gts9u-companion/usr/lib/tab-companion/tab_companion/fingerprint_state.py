# SPDX-License-Identifier: MIT
"""Pure presentation state. Journal data is progress, never authentication."""
import math
import re
import time

FINGERS = (
    "right-index-finger", "left-index-finger", "right-thumb", "left-thumb",
    "right-middle-finger", "left-middle-finger", "right-ring-finger",
    "left-ring-finger", "right-little-finger", "left-little-finger",
)
MAX_PRINTS = len(FINGERS)
IDLE_SECONDS = 30
SAMPLE = re.compile(r"EL721 sample result=(\d+) final=(\d+) coverage=(\d+) accepted=(\d+) template=(\d+)")
CONTACT = re.compile(r"EL721 contact pressed=1 released=0 sequence=(\d+)")


class FingerprintState:
    def __init__(self, mode, finger=None, clock=time.monotonic):
        self.clock = clock
        self.deadline = clock() + IDLE_SECONDS
        self.last_contact = None
        self.data = dict(mode=mode, finger=finger, status="starting", remaining=30,
                         accepted=0, coverage=0, stages=0, total_stages=18,
                         retries=0, aggregates=False, contact_seen=False, feedback="place", prints=[])

    def touch(self):
        self.deadline = self.clock() + IDLE_SECONDS
        self.data["remaining"] = IDLE_SECONDS

    def remaining(self):
        value = max(0, math.ceil(self.deadline - self.clock()))
        self.data["remaining"] = value
        return value

    def journal(self, message):
        contact = CONTACT.search(message)
        if contact and contact[1] != self.last_contact:
            self.last_contact = contact[1]
            self.data["contact_seen"] = True
            self.touch()
            self.data["feedback"] = "hold"
        match = SAMPLE.search(message)
        if match and self.data["mode"] == "enroll":
            result, final, coverage, accepted, _size = map(int, match.groups())
            self.data.update(coverage=min(100, coverage), accepted=accepted,
                             aggregates=True, secure_result=result or final)
            # Accepted/coverage are actual samples, unlike fprintd progress
            # stages (one sample may advance several stages).
            return True
        return bool(contact)

    def event(self, event):
        kind = event.get("event")
        if kind == "touch":
            self.data["contact_seen"] = True
            self.touch()
            self.data["feedback"] = "hold"
        elif kind == "lift":
            if self.data["feedback"] == "hold":
                self.data["feedback"] = "place"
        elif kind == "ready":
            self.data.update(status="running", total_stages=event.get("stages", 18))
            # Start the inactivity interval once the device is ready, not
            # during a polkit password dialog or secure-device initialization.
            self.touch()
        elif kind == "candidate":
            self.data.update(candidate=event["finger"], index=event["index"],
                             count=event["count"], feedback="next" if event["index"] > 1 else "place")
        elif kind == "progress":
            result = event["result"]
            self.data["last_result"] = result
            if result == "enroll-stage-passed":
                if self.data["contact_seen"]:
                    self.data["stages"] += 1
                    self.data["feedback"] = "accepted"
            elif "retry" in result or "too-" in result or "not-centered" in result:
                self.data["retries"] += 1
                self.data["feedback"] = "retry"
        elif kind == "prints":
            self.data["prints"] = [f for f in FINGERS if f in event["prints"]]
        elif kind == "result":
            self.data.update(status=event["status"], error=event.get("error"),
                             matched_finger=event.get("finger"))
            if event["status"] == "completed":
                self.data["coverage"] = 100
        return self.data
