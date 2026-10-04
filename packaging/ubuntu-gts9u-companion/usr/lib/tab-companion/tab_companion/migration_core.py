"""Release-specific inactive-root migration; the existing system is retained."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import subprocess
import sys
import zipfile

from . import update_bundle as bundle
from . import update_core as core
from . import update_policy as policy
from . import migration_plan as plans

STORE_NAME = ".gts9u-root"
BASE_MOUNT = Path("/.gts9u-base")
SLOT_ID = re.compile(r"[a-f0-9]{32}\Z")
EXCLUDES = (STORE_NAME, "home", "dev", "proc", "sys", "run", "tmp", "mnt", "media",
            "swapfile", "var/lib/tab-companion-update", "etc/system-update", "system-update")
BOOT_ORDER = ("init_boot", "boot", "vendor_boot", "dtbo")


def status(state, **extra):
    core.set_status(state, **extra)
    os.chmod(core.STATE / "status.json", 0o644)


def atomic_text(path, value):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    fd = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def system_bytes(source):
    command = ["du", "-sx", "--block-size=1"]
    command.extend("--exclude=" + str(source / name) for name in EXCLUDES)
    return int(core.run(command + [str(source)], True).split()[0])


def create_slot(source, identifier=None):
    identifier = identifier or secrets.token_hex(16)
    if not SLOT_ID.fullmatch(identifier):
        raise ValueError("Invalid root-slot identifier")
    store = source / STORE_NAME
    core.owned_directory(store)
    os.chmod(store, 0o700)
    slots = store / "slots"
    core.owned_directory(slots)
    slot = slots / identifier
    slot.mkdir(mode=0o700)
    return slot


def clone_system(source, slot):
    if slot.parent.parent != source / STORE_NAME or slot.is_symlink():
        raise ValueError("The new root must be an owned slot on the existing filesystem")
    root = slot / "root"
    root.mkdir()
    command = ["rsync", "-aHAXS", "--numeric-ids", "--one-file-system"]
    command.extend("--exclude=/" + name + "/***" for name in EXCLUDES)
    command.extend("--exclude=/" + name for name in EXCLUDES)
    core.run(command + [str(source) + "/", str(root) + "/"])
    for name in ("home", "dev", "proc", "sys", "run", "tmp", "mnt", "media", ".gts9u-base"):
        (root / name).mkdir(exist_ok=True)
    os.chmod(root / ".gts9u-base", 0o700)
    os.chmod(root / "tmp", 0o1777)
    return root


def installed_versions(root):
    result = core.run(["dpkg-query", "--admindir=" + str(root / "var/lib/dpkg"),
                       "-W", "-f", "${binary:Package}\t${Version}\t${db:Status-Status}\n"], True)
    installed = {}
    for line in result.splitlines():
        name, version, state = line.split("\t")
        if state == "installed":
            installed[plans.package_name(name)] = version
        elif state not in ("not-installed", "config-files"):
            raise ValueError("Repair the package database before migrating")
    return installed


class AptRuntime:
    def __init__(self, transaction):
        self.transaction = transaction
        self.runtime = transaction / "resolver"
        self.config = transaction / "apt.conf"

    def extract(self, program):
        with zipfile.ZipFile(program) as archive:
            prefix = "resources/apt/"
            entries = json.loads(archive.read(prefix + "files.json"))
            if not isinstance(entries, dict) or not 3 <= len(entries) <= 128:
                raise ValueError("Invalid frozen resolver inventory")
            self.runtime.mkdir()
            total = 0
            for name, digest in entries.items():
                if not re.fullmatch(r"(?:bin/|lib/|methods-bin/)?[A-Za-z0-9_.+-]+", name):
                    raise ValueError("Unsafe resolver path")
                info = archive.getinfo(prefix + name)
                total += info.file_size
                if total > 128 * 1024**2 or stat.S_IFMT(info.external_attr >> 16) not in (0, stat.S_IFREG):
                    raise ValueError("Invalid resolver payload")
                data = archive.read(info)
                if hashlib.sha256(data).hexdigest() != digest:
                    raise ValueError("Frozen resolver checksum mismatch")
                target = self.runtime / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                target.chmod(0o755)
        methods = self.runtime / "methods"
        methods.mkdir()
        for binary in (self.runtime / "methods-bin").iterdir():
            wrapper = methods / binary.name
            wrapper.write_text("#!/bin/sh\nexec " + str(self.runtime / "lib/ld-linux-aarch64.so.1") +
                " --library-path " + str(self.runtime / "lib") + " " + str(binary) + ' "$@"\n')
            wrapper.chmod(0o755)

    def configure(self, source_root):
        transaction = self.transaction
        for name in ("lists/partial", "archives/partial", "log", "preferences.d"):
            (transaction / name).mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_root / "var/lib/dpkg/status", transaction / "source-status")
        original_preferences = source_root / "etc/apt/preferences.d/no-distro-kernel"
        if not original_preferences.is_file():
            raise ValueError("The port's archive-kernel protection is missing")
        shutil.copyfile(original_preferences, transaction / "preferences.d/no-distro-kernel")
        (transaction / "ubuntu.sources").write_text(
            "Types: deb\nURIs: https://ports.ubuntu.com/ubuntu-ports\n"
            "Suites: resolute resolute-updates resolute-backports\n"
            "Components: main restricted universe multiverse\n"
            "Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n\n"
            "Types: deb\nURIs: https://ports.ubuntu.com/ubuntu-ports\n"
            "Suites: resolute-security\nComponents: main restricted universe multiverse\n"
            "Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n")
        values = {
            "Dir::Etc::main": "/dev/null", "Dir::Etc::parts": "-",
            "Dir::Etc::sourcelist": str(transaction / "ubuntu.sources"), "Dir::Etc::sourceparts": "-",
            "Dir::Etc::preferences": "/dev/null", "Dir::Etc::preferencesparts": str(transaction / "preferences.d"),
            "Dir::State::status": str(transaction / "source-status"),
            "Dir::State::lists": str(transaction / "lists"),
            "Dir::State::extended_states": str(transaction / "extended-states"),
            "Dir::Cache::archives": str(transaction / "archives"),
            "Dir::Cache::pkgcache": str(transaction / "pkgcache.bin"),
            "Dir::Cache::srcpkgcache": str(transaction / "srcpkgcache.bin"), "Dir::Log": str(transaction / "log"),
            "Dir::Bin::methods": str(self.runtime / "methods"), "APT::Architecture": "arm64",
            "APT::Install-Recommends": "false", "APT::Install-Suggests": "false",
            "APT::Get::AllowUnauthenticated": "false", "Acquire::AllowInsecureRepositories": "false",
            "Acquire::AllowDowngradeToInsecureRepositories": "false", "APT::Solver": "internal",
            "APT::Output-Version": "2", "Acquire::Languages": "none", "Dpkg::Use-Pty": "false",
        }
        self.config.write_text("\n".join(key + ' "' + value + '";' for key, value in values.items()) + "\n")

    def command(self, arguments):
        return [str(self.runtime / "lib/ld-linux-aarch64.so.1"), "--library-path", str(self.runtime / "lib"),
                str(self.runtime / "bin/apt-get"), *arguments]

    def run(self, arguments, capture=True):
        result = subprocess.run(self.command(arguments), check=True, text=True,
            stdout=subprocess.PIPE if capture else None,
            env={**os.environ, "APT_CONFIG": str(self.config), "LC_ALL": "C",
                 "DEBIAN_FRONTEND": "noninteractive"})
        return result.stdout if capture else ""

    def local_repository(self, manifest):
        transaction = self.transaction
        repository = transaction / "UPDATE/debs"
        metapackage = transaction / "migration-metapackage"
        (metapackage / "DEBIAN").mkdir(parents=True)
        required = sorted({plans.package_name(name) for name in manifest["apt_packages"]} |
            {"ubuntu-gts9u-device", "ubuntu-gts9u-companion", "ubuntu-gts9u-hardware",
             "gnome-shell-ubuntu-extensions", "gir1.2-mutter-18"})
        (metapackage / "DEBIAN/control").write_text(
            "Package: ubuntu-gts9u-migration\nVersion: " + manifest["version"] +
            "\nArchitecture: all\nMaintainer: Ubuntu gts9uwifi port contributors <noreply@example.invalid>\n"
            "Depends: " + ", ".join(required) +
            "\nDescription: Required package set for the Resolute port migration\n")
        core.run(["dpkg-deb", "--root-owner-group", "--build", str(metapackage),
                  str(repository / "ubuntu-gts9u-migration_all.deb")], True)
        core.cache_local_packages(transaction, {"files": {
            file.relative_to(transaction).as_posix(): {} for file in repository.glob("*.deb")}})
        index = []
        for file in sorted(repository.glob("*.deb")):
            control = core.run(["dpkg-deb", "-f", str(file)], True)
            index.append(control + "\nFilename: " + file.name + "\nSize: " + str(file.stat().st_size) +
                         "\nSHA256: " + bundle.sha256(file) + "\n\n")
        packages = repository / "Packages"
        packages.write_text("".join(index))
        release = repository / "Release"
        release.write_text("Origin: GTS9U\nLabel: Verified migration payload\nSuite: resolute\n"
            "Codename: resolute\nArchitectures: arm64 all\nSHA256:\n " + bundle.sha256(packages) +
            " " + str(packages.stat().st_size) + " Packages\n")
        key_directory = transaction / "repository-signing"
        key_directory.mkdir(mode=0o700)
        core.run(["gpg", "--homedir", str(key_directory), "--batch", "--pinentry-mode", "loopback",
                  "--passphrase", "", "--quick-generate-key", "Port migration package plan",
                  "rsa3072", "sign", "0"], True)
        keyring = transaction / "repository-keyring.gpg"
        core.run(["gpg", "--homedir", str(key_directory), "--batch", "--output", str(keyring), "--export"], True)
        core.run(["gpg", "--homedir", str(key_directory), "--batch", "--pinentry-mode", "loopback",
                  "--passphrase", "", "--output", str(repository / "InRelease"),
                  "--clearsign", str(release)], True)
        sources = transaction / "migration.sources"
        sources.write_text((transaction / "ubuntu.sources").read_text() +
            "\nTypes: deb\nURIs: file:" + str(repository) + "\nSuites: ./\nSigned-By: " + str(keyring) + "\n")
        self.config.write_text(self.config.read_text().replace(str(transaction / "ubuntu.sources"), str(sources)))
        with (transaction / "source-status").open("a") as stream:
            stream.write("\nPackage: ubuntu-gts9u-migration\nStatus: install ok installed\n"
                         "Architecture: all\nVersion: 0\nDescription: Resolver-only migration requirements\n\n")

    def selection(self, arguments, installed=None):
        text = self.run(["--print-uris", "--download-only", "-V", "-y", *arguments])
        return plans.parse_selection(text, installed)

    def resolve(self, manifest, installed):
        self.local_repository(manifest)
        self.run(["update"], capture=False)
        plan = self.selection(["dist-upgrade"], {**installed, "ubuntu-gts9u-migration": "0"})
        arguments = ["install", *[name + "=" + version for name, version in plan["install"].items()],
                     *[name + "-" for name in plan["remove"]]]
        if self.selection(arguments) != plan:
            raise ValueError("Pinning the migration changed its dependency selection")
        self.run(["-y", "--download-only", *arguments], capture=False)
        return plan


def verify_archives(transaction, plan):
    available = {}
    for file in (transaction / "archives").glob("*.deb"):
        fields = core.run(["dpkg-deb", "-f", str(file), "Package", "Version", "Architecture"], True)
        values = dict(line.split(": ", 1) for line in fields.splitlines())
        if values["Architecture"] not in ("arm64", "all"):
            raise ValueError("Foreign-architecture migration dependency")
        available[(values["Package"], values["Version"])] = bundle.sha256(file)
    for name, version in plan["install"].items():
        if (name, version) not in available:
            raise ValueError("A frozen migration dependency has not been downloaded: " + name + "=" + version)
    return {file.name: bundle.sha256(file) for file in (transaction / "archives").glob("*.deb")}


def configure_target_sources(root, transaction):
    directory = root / "etc/apt/sources.list.d"
    if directory.exists():
        for file in directory.iterdir():
            if file.suffix in (".sources", ".list"):
                file.rename(file.with_name(file.name + ".pre-resolute"))
    old = root / "etc/apt/sources.list"
    if old.exists():
        old.rename(old.with_name("sources.list.pre-resolute"))
    directory.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(transaction / "ubuntu.sources", directory / "ubuntu.sources")


def apply_packages(root, transaction, plan, runtime):
    configure_target_sources(root, transaction)
    inside = root / transaction.relative_to("/")
    inside.mkdir(parents=True)
    mounts = []
    policy_file = root / "usr/sbin/policy-rc.d"
    previous = policy_file.read_bytes() if policy_file.exists() else None
    try:
        for source, destination in ((Path("/dev"), root / "dev"), (Path("/proc"), root / "proc"),
                                    (Path("/sys"), root / "sys"), (transaction, inside)):
            core.run(["mount", "--bind", str(source), str(destination)])
            mounts.append(destination)
        policy_file.write_text("#!/bin/sh\nexit 101\n")
        policy_file.chmod(0o755)
        arguments = ["-y", "--no-download", "-o", "Dir::State::status=/var/lib/dpkg/status",
                     "-o", "Dpkg::Options::=--force-confold", "-o", "Dpkg::Options::=--force-confdef",
                     "install", *[name + "=" + version for name, version in plan["install"].items()],
                     *[name + "-" for name in plan["remove"]]]
        selection = core.run(["chroot", str(root), "env", "APT_CONFIG=" + str(runtime.config),
                              *runtime.command(["--print-uris", "--download-only", "-V", "-y", *arguments[2:]])], True)
        actual = plans.parse_selection(selection)
        if actual != plan:
            raise ValueError("The offline resolver changed the frozen migration plan")
        core.run(["chroot", str(root), "env", "APT_CONFIG=" + str(runtime.config),
                  *runtime.command(arguments)], offline=True)
        core.run(["chroot", str(root), "apt-get", "-o", "Debug::NoLocking=true", "check"], True, offline=True)
        if core.run(["chroot", str(root), "dpkg", "--audit"], True):
            raise ValueError("The migrated package database is inconsistent")
    finally:
        if previous is None:
            policy_file.unlink(missing_ok=True)
        else:
            policy_file.write_bytes(previous)
        for destination in reversed(mounts):
            core.run(["umount", str(destination)])


def saved_boot_set(root, transaction, manifest):
    saved = root / "var/lib/gts9u-boot-sets/ubuntu"
    saved.mkdir(parents=True, exist_ok=True)
    for part in bundle.PARTITIONS:
        shutil.copyfile(transaction / (part + ".img"), saved / (part + ".img"))
    (saved / "name.txt").write_text("Ubuntu " + manifest["tag"] + "\n")


def commit_slot(source, slot, transaction, manifest, devices):
    backup = slot / "backup"
    backup.mkdir()
    hashes = []
    for part, expected in bundle.PARTITIONS.items():
        target = backup / (part + ".img")
        shutil.copyfile(devices[part], target)
        if target.stat().st_size != expected:
            raise ValueError("Truncated boot recovery image")
        digest = bundle.sha256(target)
        if digest != bundle.sha256(devices[part]):
            raise ValueError("Boot changed during recovery backup")
        hashes.append(digest + "  " + target.name + "\n")
    (backup / "SHA256SUMS").write_text("".join(hashes))
    store = source / STORE_NAME
    atomic_text(slot / "ready", manifest["kernel_release"] + "\n")
    os.sync()
    atomic_text(store / "pending", slot.name + "\n")
    try:
        for part in BOOT_ORDER:
            core.copy_partition(transaction / (part + ".img"), devices[part], bundle.PARTITIONS[part])
        atomic_text(store / "selected", slot.name + "\n")
    except Exception:
        for part, expected in bundle.PARTITIONS.items():
            core.copy_partition(backup / (part + ".img"), devices[part], expected)
        selected = store / "selected"
        if selected.exists() and selected.read_text().strip() == slot.name:
            selected.unlink()
        (store / "pending").unlink()
        os.sync()
        raise


def apply_offline():
    try:
        apply_transaction()
    except Exception as error:
        status("failed", error=str(error))
        core.unmark()
        if (Path("/") / STORE_NAME / "pending").exists():
            core.run(["systemctl", "--no-block", "start", "emergency.target"])
        else:
            core.run(["systemctl", "--no-block", "reboot"])
        raise


def apply_transaction():
    if not core.marker_owned():
        return
    if subprocess.run(["systemctl", "is-active", "--quiet", "graphical.target"]).returncode == 0:
        raise ValueError("Migration must run outside the graphical session")
    transaction = core.TRANSACTION
    manifest = json.loads((transaction / "plan.json").read_text())
    core.device_check()
    core.power_check()
    if policy.ubuntu_suite() != "noble" or BASE_MOUNT.exists():
        raise ValueError("This migration requires the original Noble root")
    if bundle.sha256("/var/lib/dpkg/status") != (transaction / "dpkg.sha256").read_text():
        raise ValueError("Packages changed after preparation; prepare the migration again")
    for name, entry in manifest["files"].items():
        if bundle.sha256(transaction / name) != entry["sha256"]:
            raise ValueError("Migration payload changed after preparation")
    for name, digest in json.loads((transaction / "archives.json").read_text()).items():
        if bundle.sha256(transaction / "archives" / name) != digest:
            raise ValueError("Migration dependency changed after preparation")
    plan = json.loads((transaction / "packages.json").read_text())
    slot = Path((transaction / "slot").read_text())
    if slot.parent.parent != Path("/") / STORE_NAME or not SLOT_ID.fullmatch(slot.name):
        raise ValueError("Unsafe migration root slot")
    status("applying", version=manifest["version"], tag=manifest["tag"])
    try:
        core.emit("Cloning the existing system while retaining its original root and shared home…")
        root = clone_system(Path("/"), slot)
        core.emit("Applying the frozen Resolute package plan to the inactive system…")
        apply_packages(root, transaction, plan, AptRuntime(transaction))
        plans.restore_compatibility_files(Path("/"), root)
        plans.check_preservation(Path("/"), root)
        if policy.ubuntu_suite(root / "etc/os-release") != "resolute":
            raise ValueError("The new system did not reach Ubuntu 26.04")
        saved_boot_set(root, transaction, manifest)
        core.write_json(root / bundle.IDENTITY.relative_to("/"), {key: manifest[key] for key in
            ("device", "version", "tag", "kernel_release")})
        target_state = root / core.STATE.relative_to("/")
        target_state.mkdir(parents=True, exist_ok=True)
        core.write_json(target_state / "status.json", {"state": "complete", "version": manifest["version"],
            "tag": manifest["tag"], "recovery": "original-root-retained"})
        core.emit("Writing verified boot images and selecting the prepared system…")
        commit_slot(Path("/"), slot, transaction, manifest, core.partitions())
        status("complete", version=manifest["version"], tag=manifest["tag"], recovery="original-root-retained")
    except Exception as error:
        status("failed", error=str(error))
        core.unmark()
        raise
    core.unmark()
    core.run(["systemctl", "--no-block", "reboot"])


def install_runner(program):
    frozen = core.TRANSACTION / "migration.pyz"
    shutil.copyfile(program, frozen)
    unit = Path("/etc/systemd/system") / core.UNIT
    unit.write_text("[Unit]\nDescription=Stage the Resolute root-slot migration\nDefaultDependencies=no\n"
        "Requires=sysinit.target\nAfter=sysinit.target\nBefore=system-update.target\nConflicts=shutdown.target\n"
        "[Service]\nType=oneshot\nExecStart=/usr/bin/python3 " + str(frozen) +
        " --apply-offline\nTimeoutStartSec=infinity\nStandardOutput=journal+console\nStandardError=journal+console\n")
    wants = unit.parent / "system-update.target.wants"
    wants.mkdir(exist_ok=True)
    link = wants / core.UNIT
    if not link.exists():
        link.symlink_to("../" + core.UNIT)
    core.run(["systemctl", "daemon-reload"])


def adopt_handoff(archive):
    transaction = core.TRANSACTION
    if not transaction.exists():
        transaction.mkdir(mode=0o700)
        return
    if (os.environ.get("GTS9U_UPDATER_HANDOFF") != bundle.sha256(archive)
            or archive.is_relative_to(transaction)
            or {file.name for file in transaction.iterdir()} != {"release.zip"}
            or core.status().get("state") != "preparing"):
        raise ValueError("Cancel the previous staging transaction before preparing migration")
    os.rename(transaction, archive.parent / "bridge-staging")
    transaction.mkdir(mode=0o700)


def prepare_same_suite(archive, manifest):
    adopt_handoff(archive)
    transaction = core.TRANSACTION
    try:
        bundle.extract(archive, transaction)
        plan = {**manifest, "update_kind": "port", "source_suites": ["resolute"]}
        policy.check_installed(plan)
        core.validate_packages(transaction, plan)
        core.write_json(transaction / "plan.json", plan)
        core.cache_local_packages(transaction, plan)
        core.run(["apt-get", "update"])
        core.run(core.apt_args(transaction, download=True))
        core.run(["apt-get", "check"])
        core.write_json(transaction / "archives.json", {
            file.name: bundle.sha256(file) for file in (transaction / "archives").glob("*.deb")})
        (transaction / "dpkg.sha256").write_text(bundle.sha256("/var/lib/dpkg/status"))
        core.install_runner()
        core.MARKER.symlink_to(transaction)
        os.sync()
        status("ready", version=manifest["version"], tag=manifest["tag"])
        core.progress("ready", 1, 1)
    except Exception as error:
        core.unmark()
        status("failed", error=str(error))
        raise


def prepare(archive, program):
    core.device_check()
    core.power_check()
    manifest = bundle.inspect(archive)
    policy.check_installed(manifest, allow_handoff=True)
    if not core.verified_handoff(archive, manifest, program):
        info = bundle.release(manifest["tag"])
        if info["sha256"] != bundle.sha256(archive) or info["size"] != archive.stat().st_size:
            raise ValueError("The migration requires an authenticated release or explicitly confirmed local ZIP")
    if policy.ubuntu_suite() == "resolute":
        return prepare_same_suite(archive, manifest)
    if policy.ubuntu_suite() != "noble" or BASE_MOUNT.exists():
        raise ValueError("The distribution migration requires the original Noble root")
    if core.marker_owned() or core.status()["state"] in ("ready", "applying"):
        raise ValueError("Another update is pending")
    if core.run(["dpkg", "--audit"], True):
        raise ValueError("Repair the package database before migrating")
    if core.run(["stat", "-fc", "%T", "/sys/fs/cgroup"], True) != "cgroup2fs":
        raise ValueError("Ubuntu 26.04 requires cgroups v2")
    required_bytes = system_bytes(Path("/"))
    if shutil.disk_usage("/").free < required_bytes + 24 * 1024**3:
        raise ValueError("Not enough free space to retain the old root and prepare the new system")
    adopt_handoff(archive)
    transaction = core.TRANSACTION
    status("preparing", version=manifest["version"], tag=manifest["tag"])
    try:
        bundle.extract(archive, transaction)
        core.validate_packages(transaction, manifest)
        core.write_json(transaction / "plan.json", manifest)
        runtime = AptRuntime(transaction)
        runtime.extract(program)
        runtime.configure(Path("/"))
        core.cache_local_packages(transaction, manifest)
        installed = installed_versions(Path("/"))
        core.emit("Resolving authenticated Resolute dependencies with the release's isolated package manager…")
        runtime.run(["update"], capture=False)
        package_plan = runtime.resolve(manifest, installed)
        core.write_json(transaction / "packages.json", package_plan)
        core.write_json(transaction / "archives.json", verify_archives(transaction, package_plan))
        (transaction / "dpkg.sha256").write_text(bundle.sha256("/var/lib/dpkg/status"))
        slot = create_slot(Path("/"))
        (transaction / "slot").write_text(str(slot))
        install_runner(program)
        core.MARKER.symlink_to(transaction)
        os.sync()
        status("ready", version=manifest["version"], tag=manifest["tag"])
        core.progress("ready", 1, 1)
        core.emit("Migration prepared. The original system root will be retained; restart through Tab Companion.")
    except Exception as error:
        core.unmark()
        status("failed", error=str(error))
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--zip", type=Path)
    group.add_argument("--apply-offline", action="store_true")
    group.add_argument("--probe", type=Path)
    parser.add_argument("--progress-json", action="store_true")
    args = parser.parse_args(argv)
    core.PROGRESS_JSON = args.progress_json
    if args.probe:
        manifest = bundle.inspect(args.probe)
        with zipfile.ZipFile(args.probe) as archive:
            for name, entry in manifest["files"].items():
                digest = hashlib.sha256()
                with archive.open(name) as stream:
                    for block in iter(lambda: stream.read(4 * 1024**2), b""):
                        digest.update(block)
                if digest.hexdigest() != entry["sha256"]:
                    raise ValueError("Candidate payload checksum mismatch")
        print(json.dumps({"device": manifest["device"], "suite": manifest["suite"],
            "version": manifest["version"], "kernel_release": manifest["kernel_release"],
            "payload_verified": True, "installed": False}))
        return
    if os.geteuid() != 0:
        parser.error("Run through Tab Companion with authentication")
    core.owned_directory(core.STATE)
    with core.boot_lock() as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.apply_offline:
            apply_offline()
        else:
            prepare(args.zip.resolve(strict=True), Path(sys.argv[0]).resolve(strict=True))


if __name__ == "__main__":
    main()
