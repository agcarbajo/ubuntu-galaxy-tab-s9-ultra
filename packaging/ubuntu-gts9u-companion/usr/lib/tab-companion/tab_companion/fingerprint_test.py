# SPDX-License-Identifier: MIT
"""Bounded, user-started fingerprint enrolment diagnostics."""

import json
import os
import re
import signal
import time
from datetime import datetime, timezone

from gi.repository import Gio, GLib


SAMPLE_RE = re.compile(
    r"EL721 sample result=(\d+) final=(\d+) coverage=(\d+) "
    r"accepted=(\d+) template=(\d+)"
)


class FingerprintTest:
    """Run fprintd-enroll while exposing safe aggregate diagnostics.

    The encrypted template remains opaque to this process.  A fully completed
    run is a normal right-index enrolment; a timeout or Escape disconnects the
    client and makes fprintd cancel and clean up the partial transaction.
    """

    def __init__(self, updated, finished):
        self._updated = updated
        self._finished = finished
        self.process = None
        self.journal = None
        self._process_stream = None
        self._journal_stream = None
        self._tick_id = 0
        self._kill_id = 0
        self._drain_id = 0
        self._duration = 0
        self._started = 0.0
        self._stop_reason = None
        self._finished_once = False
        self._session_log = None
        self._latest_log = None
        self.state = {}

    @property
    def running(self):
        return self.process is not None and not self._finished_once

    def start(self, duration):
        if self.running:
            return False
        self._duration = max(30, min(int(duration), 600))
        self._started = time.monotonic()
        self._stop_reason = None
        self._finished_once = False
        self.state = {
            "status": "starting",
            "duration": self._duration,
            "remaining": self._duration,
            "coverage": 0,
            "accepted": 0,
            "retries": 0,
            "stage": 0,
            "result": None,
        }
        self._open_logs()
        self._record("session", "start")

        flags = Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE
        try:
            self.journal = Gio.Subprocess.new(
                [
                    "journalctl",
                    "--follow",
                    "--lines=0",
                    "--unit=fprintd.service",
                    "--output=cat",
                ],
                flags,
            )
            self._journal_stream = Gio.DataInputStream.new(self.journal.get_stdout_pipe())
            self._read_next(self._journal_stream, "journal")
            self.process = Gio.Subprocess.new(
                [
                    "stdbuf",
                    "-oL",
                    "-eL",
                    "fprintd-enroll",
                    "-f",
                    "right-index-finger",
                    GLib.get_user_name(),
                ],
                flags,
            )
        except GLib.Error as error:
            self._record("error", str(error))
            self._finish("failed", str(error))
            return False

        self._process_stream = Gio.DataInputStream.new(self.process.get_stdout_pipe())
        self._read_next(self._process_stream, "client")
        self.process.wait_async(None, self._process_waited)
        self._tick_id = GLib.timeout_add_seconds(1, self._tick)
        self.state["status"] = "running"
        self._emit()
        return True

    def stop(self, reason="cancelled"):
        if not self.running or self._stop_reason is not None:
            return
        self._stop_reason = reason
        self.state["status"] = "stopping"
        self._record("session", reason)
        self._emit()
        try:
            self.process.send_signal(signal.SIGINT)
        except GLib.Error:
            self.process.force_exit()
        self._kill_id = GLib.timeout_add_seconds(2, self._force_exit)

    def _tick(self):
        if not self.running:
            return GLib.SOURCE_REMOVE
        elapsed = int(time.monotonic() - self._started)
        self.state["remaining"] = max(0, self._duration - elapsed)
        self._emit()
        if elapsed >= self._duration:
            self.stop("timeout")
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def _force_exit(self):
        self._kill_id = 0
        if self.running:
            self.process.force_exit()
        return GLib.SOURCE_REMOVE

    def _read_next(self, stream, source):
        stream.read_line_async(
            GLib.PRIORITY_DEFAULT,
            None,
            self._line_read,
            source,
        )

    def _line_read(self, stream, result, source):
        try:
            line, _length = stream.read_line_finish_utf8(result)
        except GLib.Error as error:
            if self.running:
                self._record("error", f"{source}: {error}")
            return
        if line is None:
            return
        line = line.strip()
        if line:
            self._consume(source, line)
        if self.running or source == "journal":
            self._read_next(stream, source)

    def _consume(self, source, line):
        self._record(source, line)
        match = SAMPLE_RE.search(line)
        if source == "client" or match or "EL721" in line:
            self.state["last_message"] = line
        if match:
            result, final, coverage, accepted, template = map(int, match.groups())
            self.state.update(
                result=result or final,
                coverage=coverage,
                accepted=accepted,
                template_bytes=template,
            )
        elif "enroll-stage-passed" in line:
            self.state["stage"] = min(17, self.state["stage"] + 1)
        elif "enroll-retry" in line:
            self.state["retries"] += 1
        elif "enroll-completed" in line:
            self.state["status"] = "completed"
        elif "enroll-unknown-error" in line or "failed to" in line.lower():
            self.state["status"] = "failed"
        self._emit()

    def _process_waited(self, process, result):
        try:
            process.wait_finish(result)
        except GLib.Error as error:
            self._record("error", str(error))
        if self._stop_reason:
            status = self._stop_reason
        elif process.get_if_exited() and process.get_exit_status() == 0:
            status = "completed"
        else:
            status = "failed"
        # fprintd can exit just before journalctl delivers the driver's final
        # aggregate sample.  Leave the journal reader alive briefly so even a
        # failed or cancelled run retains its last secure result in JSONL.
        if self._kill_id:
            GLib.source_remove(self._kill_id)
            self._kill_id = 0
        self.state["status"] = status
        self._emit()
        self._drain_id = GLib.timeout_add(750, self._finish_after_drain, status)

    def _finish_after_drain(self, status):
        self._drain_id = 0
        self._finish(status)
        return GLib.SOURCE_REMOVE

    def _finish(self, status, detail=None):
        if self._finished_once:
            return
        self._finished_once = True
        if self._tick_id:
            GLib.source_remove(self._tick_id)
            self._tick_id = 0
        if self._kill_id:
            GLib.source_remove(self._kill_id)
            self._kill_id = 0
        if self._drain_id:
            GLib.source_remove(self._drain_id)
            self._drain_id = 0
        if self.journal is not None:
            self.journal.force_exit()
            self.journal = None
        self.state["status"] = status
        self.state["remaining"] = max(
            0, self._duration - int(time.monotonic() - self._started)
        )
        self._record("session", detail or status)
        self._emit()
        self._close_logs()
        self.process = None
        self._finished(dict(self.state))

    def _emit(self):
        self._updated(dict(self.state))

    def _open_logs(self):
        root = os.path.join(
            GLib.get_user_state_dir(), "tab-companion", "fingerprint-tests"
        )
        os.makedirs(root, mode=0o700, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.log_path = os.path.join(root, f"{stamp}.jsonl")
        latest = os.path.join(root, "latest.jsonl")
        self._session_log = open(self.log_path, "w", encoding="utf-8")
        self._latest_log = open(latest, "w", encoding="utf-8")

    def _record(self, kind, message):
        if self._session_log is None:
            return
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "elapsed": round(max(0.0, time.monotonic() - self._started), 3),
            "kind": kind,
            "message": message,
            "state": dict(self.state),
        }
        line = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
        for stream in (self._session_log, self._latest_log):
            stream.write(line)
            stream.flush()

    def _close_logs(self):
        for stream in (self._session_log, self._latest_log):
            if stream is not None:
                stream.close()
        self._session_log = None
        self._latest_log = None
