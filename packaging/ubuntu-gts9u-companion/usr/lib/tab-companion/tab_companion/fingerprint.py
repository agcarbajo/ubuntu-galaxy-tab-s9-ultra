# SPDX-License-Identifier: MIT
"""Nonblocking fprintd worker lifecycle, inactivity deadline and private logs."""
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone

from gi.repository import Gio, GLib

from .fingerprint_state import FINGERS, FingerprintState


class FingerprintManager:
    def __init__(self, updated, finished):
        self.updated, self.finished = updated, finished
        self.process = None
        self.journal = None
        self.generation = 0
        self.tick_id = self.kill_id = self.drain_id = 0
        self.logs = []
        self.state = None

    @property
    def running(self):
        return self.process is not None

    def start(self, mode, finger=None):
        if self.running:
            return False
        if mode not in ("list", "scan", "enroll", "delete") or (mode in ("enroll", "delete") and finger not in FINGERS):
            raise ValueError("Invalid fingerprint operation")
        self.generation += 1
        token = self.generation
        self.state = FingerprintState(mode, finger)
        self.started = time.monotonic()
        self.stop_reason = None
        self.result_seen = False
        self.daemon_pid = None
        self.exit_code = None
        self.client_eof = False
        self.log_path = None
        try:
            if mode != "list":
                self.open_logs()
                self.record("start", dict(mode=mode, finger=finger))
                self.journal = Gio.Subprocess.new(
                    ["journalctl", "--follow", "--lines=0", "--unit=fprintd.service", "--output=json"],
                    Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE)
                self.read(Gio.DataInputStream.new(self.journal.get_stdout_pipe()), "journal", token)
            launcher = Gio.SubprocessLauncher.new(Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE)
            launcher.setenv("PYTHONPATH", os.path.dirname(os.path.dirname(os.path.abspath(__file__))), True)
            self.process = launcher.spawnv(
                [sys.executable, "-m", "tab_companion.fingerprint_worker", mode] + ([finger] if finger else []),
            )
            self.read(Gio.DataInputStream.new(self.process.get_stdout_pipe()), "client", token)
            self.process.wait_async(None, self.waited, token)
            self.tick_id = GLib.timeout_add(250, self.tick)
            self.emit()
            return True
        except (GLib.Error, OSError) as error:
            self.record("error", {"error": type(error).__name__})
            self.finish("failed", "Internal")
            return False

    def read(self, stream, source, token):
        stream.read_line_async(GLib.PRIORITY_DEFAULT, None, self.line_read, (source, token))

    def line_read(self, stream, result, context):
        source, token = context
        try:
            line, _length = stream.read_line_finish_utf8(result)
        except GLib.Error:
            line = None
        if token != self.generation:
            return
        if line is None:
            if source == "client":
                self.client_eof = True
            return
        try:
            event = json.loads(line)
            if not isinstance(event, dict):
                raise ValueError()
            if source == "client":
                if event.get("event") == "claimed":
                    self.daemon_pid = str(event["pid"])
                if event.get("event") == "result":
                    self.result_seen = True
                self.state.event(event)
                self.record("client", event)
                self.emit()
            elif self.daemon_pid and event.get("_PID") == self.daemon_pid:
                message = event.get("MESSAGE", "")
                if isinstance(message, str) and self.state.journal(message):
                    # Whitelist aggregate counters, not raw daemon output or
                    # another application's logs. No images/identity/ciphertext.
                    self.record("sample", {k: self.state.data[k] for k in
                                ("accepted", "coverage", "secure_result") if k in self.state.data})
                    self.emit()
        except (ValueError, KeyError, TypeError):
            pass
        if self.running or source == "journal":
            self.read(stream, source, token)

    def tick(self):
        if not self.running:
            self.tick_id = 0
            return GLib.SOURCE_REMOVE
        if self.state.data["status"] == "running" and not self.stop_reason:
            if self.state.remaining() == 0:
                self.stop("timeout")
            self.emit()
        elif time.monotonic() - self.started > 90 and self.state.data["status"] == "starting":
            self.stop("timeout")
        return GLib.SOURCE_CONTINUE

    def stop(self, reason="cancelled"):
        if not self.running or self.stop_reason:
            return
        self.stop_reason = reason
        self.state.data["status"] = "stopping"
        self.record("stop", {"reason": reason})
        self.emit()
        try:
            self.process.send_signal(signal.SIGTERM)
        except GLib.Error:
            self.process.force_exit()
        self.kill_id = GLib.timeout_add_seconds(3, self.force_exit)

    def force_exit(self):
        self.kill_id = 0
        if self.process:
            self.process.force_exit()
        return GLib.SOURCE_REMOVE

    def waited(self, process, result, token):
        process.wait_finish(result)
        if token != self.generation:
            return
        self.exit_code = process.get_exit_status() if process.get_if_exited() else -1
        if self.kill_id:
            GLib.source_remove(self.kill_id)
            self.kill_id = 0
        self.drain_id = GLib.timeout_add(750, self.drained)

    def drained(self):
        self.drain_id = 0
        status = self.state.data["status"] if self.result_seen and self.exit_code == 0 else "failed"
        # Cancellation never fabricates success. A print may have committed
        # just before cancellation; the subsequent list refresh is authoritative.
        self.finish(self.stop_reason or status, self.state.data.get("error"))
        return GLib.SOURCE_REMOVE

    def finish(self, status, error=None):
        for attr in ("tick_id", "kill_id", "drain_id"):
            source = getattr(self, attr)
            if source:
                GLib.source_remove(source)
                setattr(self, attr, 0)
        if self.journal:
            self.journal.force_exit()
            self.journal = None
        self.process = None
        self.generation += 1  # reject late journal callbacks from this run
        self.state.data.update(status=status, error=error)
        self.record("finished", {"status": status, "error": error})
        self.emit()
        for stream in self.logs:
            stream.close()
        self.logs = []
        self.finished(dict(self.state.data))

    def emit(self):
        self.updated(dict(self.state.data))

    def open_logs(self):
        root = os.path.join(GLib.get_user_state_dir(), "tab-companion", "fingerprint-tests")
        os.makedirs(root, mode=0o700, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        self.log_path = os.path.join(root, stamp + ".jsonl")
        for path in (self.log_path, os.path.join(root, "latest.jsonl")):
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
            os.fchmod(fd, 0o600)
            self.logs.append(os.fdopen(fd, "w", encoding="utf-8"))

    def record(self, kind, event):
        line = json.dumps(dict(timestamp=datetime.now(timezone.utc).isoformat(),
                               elapsed=round(time.monotonic() - self.started, 3),
                               kind=kind, event=event, state=self.state.data), ensure_ascii=False) + "\n"
        for stream in self.logs:
            stream.write(line)
            stream.flush()
