# SPDX-License-Identifier: MIT
"""Versioned update contract. No package, boot or filesystem operations."""
import re
import subprocess
from pathlib import Path

PROTOCOL = 2
CAPABILITIES = ("same-suite-packages", "matched-kernel-boot", "weekly-notifications", "official-release-backend-handoff")
CODENAME = re.compile(r"[a-z][a-z0-9]{1,31}\Z")


def ubuntu_suite(path=Path("/etc/os-release")):
    values = {}
    for line in path.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep:
            values[key] = value.strip('"\'')
    suite = values.get("UBUNTU_CODENAME") or values.get("VERSION_CODENAME")
    if values.get("ID") != "ubuntu" or not CODENAME.fullmatch(suite or ""):
        raise ValueError("Cannot identify the installed Ubuntu suite")
    return suite


def validate(manifest):
    """Parse future metadata without authorising a distribution migration."""
    if type(manifest.get("format")) is not int:
        raise ValueError("Invalid update format")
    if manifest.get("format") == 1:
        if manifest.get("suite") != "noble":
            raise ValueError("Format 1 only supports Noble")
        return
    if manifest.get("format") != PROTOCOL:
        raise ValueError("Update Tab Companion before installing this update format")
    required = manifest.get("minimum_updater_protocol")
    if type(required) is not int or not 1 <= required <= PROTOCOL:
        raise ValueError("Update Tab Companion before installing this update format")
    if not isinstance(manifest.get("suite"), str) or not CODENAME.fullmatch(manifest["suite"]):
        raise ValueError("Invalid target Ubuntu suite")
    sources = manifest.get("source_suites")
    if (not isinstance(sources, list) or not 1 <= len(sources) <= 16
            or any(not isinstance(s, str) or not CODENAME.fullmatch(s) for s in sources)):
        raise ValueError("Invalid source Ubuntu suites")
    if manifest.get("update_kind") not in ("port", "kernel", "distribution"):
        raise ValueError("Invalid update kind")
    if manifest.get("data_policy") != "preserve":
        raise ValueError("The update must preserve user data")
    minimum = manifest.get("minimum_port_version")
    if not isinstance(minimum, str) or not re.fullmatch(r"[0-9][A-Za-z0-9.+~]{0,100}", minimum):
        raise ValueError("Invalid minimum installed port version")
    if subprocess.run(["dpkg", "--compare-versions", minimum, "ge", "1.3.0"], capture_output=True).returncode != 0:
        raise ValueError("Format 2 updates require the port 1.3.0 bridge or later")
    if manifest["update_kind"] == "distribution":
        if (manifest.get("backend_strategy") != "official-release-backend-v1"
                or manifest.get("recovery") != "full-system-root-v1"
                or type(manifest.get("backend_entry_protocol")) is not int
                or manifest.get("backend_entry_protocol") != 1
                or manifest.get("backend_file") != "UPDATE/updater.pyz"):
            raise ValueError("This Ubuntu release upgrade requires a validated migration and full-system recovery backend")
        return
    if manifest["suite"] not in sources:
        raise ValueError("Same-suite updates must include their target suite")


def check_installed(manifest, suite=None, installed_version=None, allow_handoff=False):
    validate(manifest)
    suite = suite or ubuntu_suite()
    sources = manifest.get("source_suites", ["noble"])
    migration = manifest.get("update_kind") == "distribution"
    if migration and not allow_handoff:
        raise ValueError("A distribution upgrade must use its verified release backend with full-system recovery")
    if suite not in sources or (not migration and manifest["suite"] != suite):
        raise ValueError("This update does not support the installed Ubuntu suite")
    if installed_version is None:
        from .update_bundle import current
        installed_version = current().get("version")
    if installed_version and manifest.get("version") and subprocess.run(
            ["dpkg", "--compare-versions", manifest["version"], "lt", installed_version],
            capture_output=True).returncode == 0:
        raise ValueError("Downgrades are not supported; select the installed build or a newer one")
    if manifest.get("format") == PROTOCOL:
        if (not installed_version or subprocess.run(["dpkg", "--compare-versions", installed_version,
                "ge", manifest["minimum_port_version"]], capture_output=True).returncode != 0):
            raise ValueError("Install port " + manifest["minimum_port_version"] + " before this update")


def capabilities():
    return {"protocol": PROTOCOL, "capabilities": list(CAPABILITIES),
            "distribution_migration": False, "release_backend_handoff": True}
