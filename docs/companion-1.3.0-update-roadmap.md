# Port 1.3.0: Tab Companion update readiness

## Integration and authorised tablet deployment, 2026-09-28

After the initial review below, the owner authorised saving the other agent's
completed work on main, pushing it and integrating it before installing the
app. Commit `356170d` preserves that work; main merge `ee34312` retains the
remote README update too. Merge `fbdaade` integrates main into this branch.
The S Pen reconnect/status sources from Companion 1.4.6 were compared against
the live tablet before integration and matched exactly. The integrated app
keeps those fixes and the new updater/notification functions. Main's port
VERSION is now 1.3.0; this does not publish a full release or change the live
port identity, which remains 1.2.0.

The rebuilt `artifacts/ubuntu-gts9u-companion_1.5.0_all.deb` supersedes the
earlier artifact below. Its SHA-256 is
`a1d7ecd34277bd65fb5fe5a86d75e2f0b3341e8973b869b37a5bdf9238a3d576`.
The same 71 unit tests and two GTK scripts passed again, along with the
S Pen reconnect/status and Companion efficiency/hover regressions and package
validation. The merged fingerprint build scripts passed shell syntax checks;
this app deployment does not validate or deploy new kernel/fingerprint builds
or the untested Resolute migration/recovery engine.

The owner supplied the current address and username. SSH matched a previously
saved host key; the remote model identified SM-X910, Ubuntu 24.04.5 arm64,
Companion 1.4.6, fprintd gts9u2, writable UFS root, 39% battery, 257 GiB free,
no offline-update marker, complete updater state and clean package audit.
The transferred package matched the full hash. APT simulation and installation
selected only Companion: one upgrade, no additions/removals, with removals and
unauthenticated archive packages disallowed. No partition, GDM restart or
reboot was performed. APT's sandbox notice resulted from the private temporary
directory; it was not an integrity or dependency failure.

The previous installed package files, dpkg status and package control scripts
are retained root-only at
`/var/lib/tab-companion-update/package-backups/1.4.6-before-1.5.0-20260928/`.
The `installed-files.tar.gz` hash is
`a7c0e1ff3dde61385e9bc879437706da45549655d9c21d0dd8056168f146c7bd`.
This is package recovery evidence, not a full Ubuntu migration backup; do not
restore the saved entire dpkg status over unrelated later package changes.

Post-install version is 1.5.0; `apt-get check` and `dpkg --audit` are clean.
`dpkg -V` reports only the shared generated `gschemas.compiled`, also present
before installation. Pairing and user hardware services are active and their
installed sources still match 1.4.6. The weekly timer is enabled/active; the
preference remains false. The new UI was launched in Updates through a
transient user service and is active without Python errors in its journal.
Owner-visible toggle, notification/badge, and real update acceptance remain
pending. The installation does not fabricate an available release to force a
notification.

## Baseline reviewed on 2026-09-28

The isolated branch `feature/companion-future-updates-1.3.0` starts at
`0116bcc`, including the packaged ath12k isolation on every suspend cycle.
The primary checkout has concurrent, uncommitted keyboard/Caps LED work and
documentation. Those files and the Gunyah worktrees were only read, never
modified or included in this branch's commits. The later EF-DX920 trial and
rollback evidence must reach the final release through its owner's reviewed
commits; source experiments must not be copied from shared build directories.

Recent port changes relevant to the next release:

| Component | Evidence / implication for updates |
| --- | --- |
| ath12k suspend | Three consecutive owner-confirmed recoveries with the per-cycle unbind/rebind hook; long-term MHI reliability still open. Ship the hook through the device package on both suites. |
| Cover keyboard | The latest normal-event Caps LED timing trial passed the owner's tested cases; the earlier standalone I2C worker caused lost input and was rolled back. Preserve the verified source once committed; never revive the worker. |
| Audio | Stereo routing is reapplied after ALSA restoration. Balanced listening and Cirrus protection remain separate unresolved checks. Preserve UCM and service ordering. |
| Fingerprint | The presentation gate and its paired libfprint/device packages remain required; optical transition acceptance is still open. Never update one half alone. |
| S Pen | Companion 1.4.2's proximity guard and 1.4.1's pairing CPU fix remain in the new package. |
| Gunyah | Existing committed baseline retained; concurrent VM research is not merged or modified. A new kernel must rebuild all opted-in custom modules. |

Port release versions and application package versions are separate. The
prospective **port 1.3.0** carries **Tab Companion 1.5.0**; the application
version is higher than the already deployed 1.4.2 package.

## Changes implemented in Companion 1.5.0

- Discover `ubuntu-YY.MM-sm-x910-v*.zip`, including future Ubuntu release names.
  Retain repository URL, published SHA-256, bounded-size and stable-release
  checks. Never invoke the TWRP installer or extract its fresh `rootfs.img`.
- Keep format 1 for the 1.3.0 bridge release so installed 1.2.0 updaters can
  consume it. Frozen offline/bootstrap runners now also include the policy
  module; changing the installed application cannot change an active runner.
- Add format 2 for explicitly described same-suite port/kernel updates:
  `minimum_updater_protocol`, `minimum_port_version`, `source_suites`, target
  `suite`, `update_kind` and `data_policy=preserve`. Require port 1.3.0 for new
  format 2 build inputs. Recheck the installed suite/version before staging and
  again offline. Reject local ZIP downgrades as well as online downgrades.
- Identify the installed Ubuntu codename from `os-release`, rather than
  permanently hardcoding `VERSION_ID=24.04`. Format 1 remains Noble-only;
  format 2 same-suite updates work on another Ubuntu suite once the system has
  reached it through an approved migration.
- Expose `gts9u-update --capabilities` without root privileges. Unsupported
  protocols and distribution migrations through the old APT path are rejected
  before APT or boot writes.
- Support a future distribution-specific backend carried in the official ZIP.
  This is the extension point that lets an installed 1.3.0 hand off to a later
  tested migration implementation, without requiring another bridge release.
- Add an opt-in weekly check, persistent per-user cache, a bottom-bar attention
  dot and a desktop notification with an action opening Updates. No automatic
  download, authentication, preparation or installation.

### Weekly scheduling and privacy

The new GSettings key `weekly-update-checks` defaults to false and survives
package updates. A user timer wakes daily and five minutes after user-manager
startup; it only checks the local preference and timestamp. Successful network
checks are separated by at least seven days. Daily wake-ups allow retry after
offline failure and avoid a manual Tuesday check delaying a Monday-calendar
check for almost two weeks. Failed requests retain the last known update and
do not consume the seven-day interval. The timer is enabled globally for user
accounts but is inert while their preference is off; it never runs as root.

The helper uses D-Bus activation of the app's `check-updates` action and exits.
Opening a window during a background check therefore cannot leave the app
under a oneshot service's timeout or prevent later timer dispatches. Requests
are bounded by the network timeout and concurrent checks in one app are
coalesced. The app checks the preference again before delivering a result.

The cache is in the user's XDG cache directory, file mode 0600; it contains
public release metadata, successful-check time and the last notified release
tag/digest. The same asset does not notify repeatedly. A replacement asset or
new release can notify again. A known-current installation clears the dot;
unknown installed versions do not produce a false "newer" notification.
GNOME's own notification settings and Do Not Disturb still apply. D-Bus
activation, desktop notification metadata and libadwaita's supported
`needs-attention` property are used, without inspecting widget internals.

## Ubuntu release migration is still an explicit release gate

**This commit prepares delivery of a future migration engine; it does not
implement the Noble-to-Resolute migration itself.**
Reading a future release filename, or accepting metadata, cannot establish that
APT can migrate its userspace or that recovery can restore it. The backend
therefore reports `distribution_migration: false`, with
`release_backend_handoff: true`. It refuses a cross-suite update disguised as
`port` or `kernel`, and never applies a distribution transaction using the
current same-suite APT runner. Port 1.3.0 can deliver a later official engine
through the handoff below. Do not advertise a particular 26.04 package as
usable until that engine and its recovery path pass the following release
checks. The bridge's handoff is tested with interception, not with a real
migration or physical recovery.

### Official release backend handoff

A format 2 distribution manifest must name `UPDATE/updater.pyz`, declare
`backend_strategy=official-release-backend-v1`, `backend_entry_protocol=1`,
`recovery=full-system-root-v1`, `data_policy=preserve`, and require port 1.3.0
or newer. Its source-suite/version requirements are checked before handoff.
`make-twrp-zip.py` includes this bounded regular zip application in the hashed
payload when explicitly requested by the metadata. The ordinary format 1/2
package path cannot carry or execute it.

The installed updater requires the full ZIP's tag, size and SHA-256 to match
the exact official stable GitHub release. Even a user-selected local ZIP must
match that published release; a checksum written inside an arbitrary local ZIP
is insufficient, and offline/unpublished crossgrades are refused. This uses
the same publisher trust as privileged maintainer scripts in official Debian
packages. Contract metadata is not proof of safe code or physical validation:
maintainers must review and test the backend before publishing its digest.

The updater additionally verifies the inner backend hash, retains immutable
copies of the ZIP and backend in root-only
`/var/lib/tab-companion-update/handoff/<transaction-id>/`, then replaces its
process with `/usr/bin/python3 updater.pyz --zip retained-release.zip`, carrying
the progress option if enabled. The boot lock is released by CLOEXEC so the
new engine can acquire its own. A digest marker blocks recursive handoff to a
backend that still does not implement the migration. No APT, installed app or
boot-image write precedes this dispatch. Retained inputs remain available after
failure; the future engine must retire them only after its recovery inputs and
frozen runner no longer depend on them.

Entry protocol 1 requires the new engine to accept `--zip` and
`--progress-json`, return the existing JSON progress/status contract, acquire
the boot lock, revalidate the model, source ZIP/suite/version and power, prepare
authenticated dependencies and a full-system recovery path before marking the
transaction ready, and freeze its own offline runner. It must not invoke the
TWRP installer, format partitions or replace home/accounts/identities with the
fresh image. A future release can implement that engine and ship it with its
update, while Companion 1.5.0's UI remains installed until normal package
installation upgrades it.

Before publishing a distribution upgrade, implement the reviewed migration
strategy with full-root recovery in its official backend. Future distribution
releases need:

1. A tested Noble-to-Resolute dependency/source transition with the exact custom
   packages and explicitly reviewed removals. Check Canonical's live upgrade
   enablement index again; a prior `Supported: 0` observation is time-specific.
2. Authenticated, pinned, completely downloaded dependencies and a frozen
   offline plan. Fingerprint libfprint/TOD/fprintd/PAM, libcamera/SPA/relay,
   libssc/protobuf/proxy and device packages must move together. Preserve
   accounts, UID/GID, home data, dconf, NetworkManager, SSH identities and prints.
3. A recoverable complete old system root, package database and APT sources.
   The current boot/modules/`etc` backup cannot undo a partially replaced
   `/usr` or dpkg database. Ext4/UFS here has no A/B slot. Restore must run from
   a known-good independent environment, with tested storage/space checks.
4. GNOME 50 private-API regression testing and Mutter 18 bridge validation;
   WirePlumber 0.5 SPA-JSON rules, Python 3.14/protobuf imports, systemd 259,
   sudo/coreutils transitions, mount-path assumptions and third-party sources.
5. The stable kernel chosen at release time, all port patches and modules from
   one fresh build, matching certificate/config/symbol CRCs, validated Android
   v4 boot images, pinned ABL-compatible DTB and saved Ubuntu boot set.
6. Simulated interrupted migration and recovery, followed by physical boot,
   UFS resume, display/GPU, radios, audio, cameras, fingerprint, sensors,
   S Pen/keyboard, charging and NPU tests. Kernel compilation is insufficient.

The previous detailed userspace/package work remains documented in
[the 26.04 assessment](upgrade-26.04-assessment.md). No rootfs, kernel, ZIP or
tablet change is part of this Companion task.

## Focused verification

Run Linux tests in a source copy on the WSL filesystem. The GTK tests need a
compiled schema, `GSETTINGS_BACKEND=memory`, Xvfb and a private session bus:

- `scripts/test-update-readiness.py`: weekly timing, deduplication, bridge and
  suite requirements, metadata rejection, local downgrade and cache permissions.
  It also verifies official digest gating, retained input permissions, fixed
  handoff arguments, inner checksum and recursive handoff rejection; `exec` is
  intercepted and no bundled program is executed.
- `scripts/test-system-update.py`: existing bounded payload, boot/module recovery,
  conffile preservation, frozen runner, ZIP agreement and rejection of a
  distribution transaction before backups or package installation.
- `scripts/test-update-notifications-ui.py`: a fake desktop notification server
  receives a real GNotification; verify opt-in, no duplicate network request,
  deduplication, D-Bus timer action, badge and notification action.
- `scripts/test-system-update-ui.py`, `scripts/test-companion-translations.py`,
  `scripts/test-release-suite-guard.py` and `scripts/test-update-launcher.py`.
- Build `ubuntu-gts9u-companion_1.5.0_all.deb`, inspect units/D-Bus service/schema,
  validate desktop metadata and simulate package installation.

Device acceptance still needs the real GNOME session: toggle persistence after
reboot, timer dispatch with the app closed, visible dot/notification, clicking
the notification, desktop notification permissions and an actual same-suite
port update with saved data/settings. No tablet write is authorised here.

### Results on 2026-09-28

- 71 unit tests passed: readiness 18, system update 39, release-suite guard 2,
  launcher 5 and translations 7 (including the GTK translation case).
- Both GTK scripts passed under Xvfb with a private D-Bus session. The
  notification test uses a fake notification server receiving the real Gio
  call; the release backend's `exec` is intercepted. Neither test migrates an
  operating system, writes real boot devices or proves hardware compatibility.
- The package builder passed Python/schema/resource, desktop and AppStream
  validation. The built `artifacts/ubuntu-gts9u-companion_1.5.0_all.deb` has
  SHA-256 `e68e26d813a1ab4dcc5ebd53fd1f86a5d912f96e69a7e5d61e4141aeeb8d759e`.
- Read-only arm64 APT simulation against the prepared Resolute root succeeded:
  three additions, zero removals. Simulation against the old Noble buildroot
  is blocked by its absent custom `fprintd (>= 1.94.3-1+gts9u1)`. That dependency
  predates this change and has not been weakened. This is not a successful
  Noble package installation test; use a complete current port baseline for
  device acceptance.
- No tablet connection, installation, reboot or flash was performed. No full
  port 1.3.0 ZIP or Ubuntu 26.04 migration ZIP was produced by this task.
