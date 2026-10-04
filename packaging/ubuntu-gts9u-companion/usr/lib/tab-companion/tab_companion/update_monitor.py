# SPDX-License-Identifier: MIT
"""Per-user release cache and weekly scheduling policy; never prepares updates."""
import json
import os
import time
from pathlib import Path

from . import update_bundle as bundle

WEEK = 7 * 24 * 60 * 60


def cache_path():
    return Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "tab-companion/updates.json"


def load():
    try:
        path = cache_path()
        if path.stat().st_size > 2 * 1024**2:
            return {}
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def save(value):
    path = cache_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_suffix(".tmp")
    with temp.open("w") as stream:
        os.chmod(temp, 0o600)
        json.dump(value, stream)
    os.replace(temp, path)


def due(value, now=None):
    now = time.time() if now is None else now
    last = value.get("checked_at", 0)
    return not isinstance(last, (int, float)) or not 0 <= now - last < WEEK


def available(value):
    info = value.get("release")
    return bool(isinstance(info, dict) and isinstance(info.get("tag"), str)
                and bundle.TOKEN.fullmatch(info["tag"]) and bundle.release_state(info) == "newer")


def record(info, notify=False, now=None):
    """Failures do not clear the last known update or consume the weekly check."""
    value = load()
    value.update(release=info, checked_at=time.time() if now is None else now)
    key = info["tag"] + ":" + info.get("sha256", "")
    send = notify and available(value) and value.get("notified") != key
    if not available(value):
        value.pop("notified", None)
    save(value)
    return value, key if send else None


def notified(key):
    value = load()
    value["notified"] = key
    save(value)
