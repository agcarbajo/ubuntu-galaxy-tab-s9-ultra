# SPDX-License-Identifier: MIT
"""Release discovery and bounded ZIP validation. No privileged operations."""
import hashlib
import json
import re
import stat
import subprocess
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

REPOSITORY = "agcarbajo/ubuntu-galaxy-tab-s9-ultra"
API = "https://api.github.com/repos/" + REPOSITORY + "/releases"
IDENTITY = Path("/usr/lib/gts9u-release.json")
MANIFEST = "UPDATE/manifest.json"
PARTITIONS = {"boot": 100663296, "init_boot": 8388608,
              "vendor_boot": 100663296, "dtbo": 16777216}
MAX_PAYLOAD = 16 * 1024**3
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+_~-]{0,100}\Z")
PACKAGE = re.compile(r"[a-z0-9][a-z0-9+.-]*(?::arm64)?\Z")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024**2), b""):
            h.update(block)
    return h.hexdigest()


def current():
    try:
        value = json.loads(IDENTITY.read_text())
        return value if value.get("device") == "gts9uwifi" else {}
    except (OSError, ValueError):
        return {}


def request(url):
    if urllib.parse.urlsplit(url).scheme != "https":
        raise ValueError("Only HTTPS downloads are supported")
    response = urllib.request.urlopen(urllib.request.Request(url, headers={
        "User-Agent": "TabCompanion-Updater/1", "Accept": "application/vnd.github+json",
    }), timeout=60)
    if urllib.parse.urlsplit(response.url).scheme != "https":
        response.close()
        raise ValueError("Refusing an insecure redirect")
    return response


def release(tag=None):
    url = API + ("/tags/" + urllib.parse.quote(tag, safe="") if tag else "/latest")
    with request(url) as stream:
        data = json.loads(stream.read(2 * 1024**2 + 1))
    if data.get("draft") or data.get("prerelease"):
        raise ValueError("This is not a published stable release")
    assets = [a for a in data.get("assets", []) if re.fullmatch(
        r"ubuntu-24\.04-sm-x910-v[^/]+\.zip", a.get("name", ""))]
    if len(assets) != 1:
        raise ValueError("The release must contain exactly one SM-X910 installation ZIP")
    asset = assets[0]
    expected_url = "https://github.com/" + REPOSITORY + "/releases/download/"
    if not asset.get("browser_download_url", "").startswith(expected_url):
        raise ValueError("Unexpected release asset URL")
    digest = asset.get("digest", "") or ""
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("GitHub has no SHA-256 digest for this ZIP; use a trusted local ZIP")
    if not 0 < asset.get("size", 0) <= MAX_PAYLOAD:
        raise ValueError("Invalid release ZIP size")
    return {"tag": data["tag_name"], "name": asset["name"],
            "url": asset["browser_download_url"], "size": asset["size"],
            "sha256": digest[7:], "notes": data.get("body", ""),
            # New releases publish the bootstrap alongside the update-enabled
            # ZIP. This is a discovery gate; inspect() still verifies the ZIP.
            "supports_updates": any(a.get("name") == "gts9u-update.pyz"
                                    for a in data.get("assets", []))}


def release_state(info):
    if not info.get("supports_updates", False):
        return "unsupported"
    installed = current()
    if not installed.get("version"):
        return "unknown"
    if info["tag"] == installed.get("tag"):
        return "current"
    candidate = info["tag"].removeprefix("v")
    result = subprocess.run(["dpkg", "--compare-versions", candidate, "gt", installed["version"]],
                            capture_output=True)
    return "newer" if result.returncode == 0 else "older"


def download(info, path, progress=lambda *_: None):
    received = 0
    with request(info["url"]) as source, open(path, "xb") as dest:
        while True:
            chunk = source.read(4 * 1024**2)
            if not chunk:
                break
            received += len(chunk)
            if received > info["size"]:
                raise ValueError("Download exceeds the published size")
            dest.write(chunk)
            progress(received, info["size"])
    if received != info["size"] or sha256(path) != info["sha256"]:
        raise ValueError("The downloaded ZIP does not match GitHub's digest")


def inspect(path):
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        names = [i.filename for i in entries]
        if len(entries) > 50000 or len(names) != len(set(names)):
            raise ValueError("Duplicate or excessive ZIP entries")
        if MANIFEST not in names:
            raise ValueError("This ZIP predates safe updates. Its TWRP installer would erase data. Choose a newer build.")
        if archive.getinfo(MANIFEST).file_size > 1024**2:
            raise ValueError("Oversized update manifest")
        manifest = json.loads(archive.read(MANIFEST))
        if (manifest.get("format") != 1 or manifest.get("device") != "gts9uwifi"
                or manifest.get("architecture") != "arm64" or manifest.get("suite") != "noble"):
            raise ValueError("Unsupported update format, device or Ubuntu release")
        for field in ("version", "tag", "kernel_release"):
            if not isinstance(manifest.get(field), str) or not TOKEN.fullmatch(manifest[field]):
                raise ValueError("Invalid " + field)
        files = manifest.get("files")
        if not isinstance(files, dict) or not 5 <= len(files) <= 4096:
            raise ValueError("Invalid payload list")
        total = 0
        packages = 0
        for name, metadata in files.items():
            if name not in {p + ".img" for p in PARTITIONS}:
                if not re.fullmatch(r"UPDATE/debs/[A-Za-z0-9][A-Za-z0-9.+_~%-]*\.deb", name):
                    raise ValueError("Unsafe payload path: " + name)
                packages += 1
            info = archive.getinfo(name)
            if stat.S_IFMT(info.external_attr >> 16) not in (0, stat.S_IFREG):
                raise ValueError("Payload entries must be regular files")
            if (not isinstance(metadata, dict) or metadata.get("size") != info.file_size
                    or not re.fullmatch(r"[a-f0-9]{64}", str(metadata.get("sha256", "")))):
                raise ValueError("Invalid payload metadata: " + name)
            total += info.file_size
        if total > MAX_PAYLOAD or not packages:
            raise ValueError("Invalid payload size")
        for part, size in PARTITIONS.items():
            if files.get(part + ".img", {}).get("size") != size:
                raise ValueError("Missing or truncated " + part)
        requested = manifest.get("apt_packages", [])
        if not isinstance(requested, list) or len(requested) > 3000 or any(
                not isinstance(p, str) or not PACKAGE.fullmatch(p) for p in requested):
            raise ValueError("Invalid package requirements")
        return manifest


def extract(path, destination):
    manifest = inspect(path)
    with zipfile.ZipFile(path) as archive:
        for name, meta in manifest["files"].items():
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(name) as src, target.open("xb") as dst:
                h = hashlib.sha256()
                for chunk in iter(lambda: src.read(4 * 1024**2), b""):
                    h.update(chunk)
                    dst.write(chunk)
            if h.hexdigest() != meta["sha256"]:
                raise ValueError("Payload checksum mismatch: " + name)
    return manifest
