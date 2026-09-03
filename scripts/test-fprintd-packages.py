#!/usr/bin/env python3
"""Real .deb metadata/payload checks and isolated APT dependency regression.

The tiny synthetic status database tests this exact dependency edge, not all
rootfs dependencies. Deployment and rootfs builds must also run apt-get check
against their REAL installed database. No packages are installed by this test.
"""
import io
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
import unittest

if len(sys.argv) != 4:
    raise SystemExit("usage: test-fprintd-packages.py daemon.deb pam.deb original-pam.deb")
DAEMON, PAM, ORIGINAL = map(Path, sys.argv[1:])
sys.argv[1:] = []
ROOT = Path(__file__).resolve().parents[1]


def field(package, name):
    return subprocess.check_output(["dpkg-deb", "--field", str(package), name], text=True).strip()


def archive(package, option):
    raw = subprocess.check_output(["dpkg-deb", option, str(package)])
    with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
        return {m.name: (m.type, m.mode, m.uid, m.gid, m.linkname,
                         tar.extractfile(m).read() if m.isfile() else None)
                for m in tar}


class PackageTests(unittest.TestCase):
    def test_version_and_exact_dependency(self):
        subprocess.run(["bash", str(ROOT / "scripts/check-fprintd-package-pair.sh"),
                        str(DAEMON), str(PAM)], check=True)
        self.assertEqual(field(PAM, "Depends"), field(ORIGINAL, "Depends").replace(
            "fprintd (= 1.94.3-1)", "fprintd (= " + field(DAEMON, "Version") + ")"))

    def test_broken_pair_guard_rejects(self):
        result = subprocess.run(["bash", str(ROOT / "scripts/check-fprintd-package-pair.sh"),
                                 str(DAEMON), str(ORIGINAL)], capture_output=True)
        self.assertNotEqual(result.returncode, 0)

    def test_pam_payload_unchanged(self):
        # Includes module bytes, PAM profile, manpages, modes and symlinks.
        self.assertEqual(archive(PAM, "--fsys-tarfile"), archive(ORIGINAL, "--fsys-tarfile"))

    def test_maintainer_scripts_unchanged(self):
        old, new = archive(ORIGINAL, "--ctrl-tarfile"), archive(PAM, "--ctrl-tarfile")
        old.pop("./control")
        new.pop("./control")
        self.assertEqual(old, new)

    def apt_check(self, daemon_version, pam):
        # Stubs satisfy all unrelated library requirements, isolating the
        # strict libpam-fprintd -> fprintd edge that caused the regression.
        dependencies = field(DAEMON, "Depends") + ", " + field(pam, "Depends")
        names = {re.match(r"[a-z0-9][a-z0-9+.-]*", d.strip())[0]
                 for d in re.split(r"[,|]", dependencies)} - {"fprintd", "libpam-fprintd"}
        def stanza(name, version, depends=""):
            return (f"Package: {name}\nStatus: install ok installed\n"
                    f"Architecture: arm64\nVersion: {version}\n"
                    + (f"Depends: {depends}\n" if depends else "")
                    + "Description: Synthetic dependency test only\n\n")
        status = stanza("fprintd", daemon_version, field(DAEMON, "Depends"))
        status += stanza("libpam-fprintd", field(pam, "Version"), field(pam, "Depends"))
        status += "".join(stanza(name, "999:999") for name in sorted(names))
        with tempfile.TemporaryDirectory(prefix="fprintd-apt-test-") as temp:
            base = Path(temp)
            (base / "status").write_text(status)
            for directory in ("lists/partial", "cache/archives/partial", "log"):
                (base / directory).mkdir(parents=True)
            command = ["apt-get", "--simulate", "-o", "APT::Architecture=arm64",
                       "-o", "Debug::NoLocking=true",
                       "-o", "Dir::Etc::sourcelist=/dev/null",
                       "-o", "Dir::Etc::sourceparts=-",
                       "-o", f"Dir::State::status={base / 'status'}",
                       "-o", f"Dir::State::lists={base / 'lists'}",
                       "-o", f"Dir::Cache={base / 'cache'}",
                       "-o", f"Dir::Log={base / 'log'}", "check"]
            return subprocess.run(command, capture_output=True, text=True)

    def test_apt_original_pair(self):
        result = self.apt_check("1.94.3-1", ORIGINAL)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_apt_detects_original_regression(self):
        result = self.apt_check(field(DAEMON, "Version"), ORIGINAL)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("fprintd", result.stdout + result.stderr)

    def test_apt_accepts_corrected_pair(self):
        result = self.apt_check(field(DAEMON, "Version"), PAM)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_apt_rejects_future_mismatched_daemon(self):
        result = self.apt_check(field(DAEMON, "Version") + ".future", PAM)
        self.assertNotEqual(result.returncode, 0)


unittest.main()
