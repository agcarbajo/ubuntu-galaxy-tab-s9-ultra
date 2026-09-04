# System updates

Tab Companion 1.3 adds an **Updates** page for the complete Ubuntu port, not
just the application. Release v1.1.0 is the first release with the update
payload. The v1.0.0 ZIP predates that format and cannot be installed through
this updater; existing v1.0.0 installations can upgrade using the command below.

## Updating

Open **Tab Companion → Updates**; it checks GitHub when opened. You can also
use **Check for updates** to refresh, then download and
prepare the update. Alternatively choose a local build ZIP. Authenticate when
asked and save your work before choosing **Restart and install**. The charger
is required only below 20% battery, both during preparation and installation. Preparation checks
storage and downloads any APT dependencies while the normal network is still
available. Installation runs outside the graphical session and restarts back
into Ubuntu when it finishes.

Companion 1.3.1 shows release notes, the download size and a visual progress
bar. Transfer percentage, speed and estimated time use measured bytes; stages
without a known total use an activity indicator. Download, verification,
package preparation and readiness are shown separately. Technical logs are
collapsed by default and expanded on preparation failure.

A prepared update can be cancelled before restarting. Switching to Android
is blocked while an update is pending. Ubuntu's saved boot set is refreshed
with the new images; Android's saved set is preserved.

Hold **Check for updates** for three seconds or Shift-click it to access
the hidden repair action. A confirmation appears only if the recorded build's exact GitHub tag
has a downloadable ZIP and a published SHA-256 digest. It reinstalls that
build's packages and boot images while retaining configuration; it is not a
factory reset. Installations without release metadata cannot infer their
version from the kernel or the app version, so repair stays unavailable until
their first update.

## Older installations without the Updates page

Release v1.1.0 includes `gts9u-update.pyz` alongside the ZIP. It is a standalone
Python updater using the same backend as the app; it needs no prior Companion
upgrade. From an existing Ubuntu installation:

```sh
d=$(mktemp -d) && curl -fL https://github.com/agcarbajo/ubuntu-galaxy-tab-s9-ultra/releases/latest/download/gts9u-update.pyz -o "$d/gts9u-update.pyz" && sudo python3 "$d/gts9u-update.pyz" --latest
```

Once preparation succeeds, save your work and run `systemctl reboot`.
For a private build, use `--zip /path/to/build.zip` instead of `--latest`.
The ZIP must have been built with the update payload introduced in v1.1.0.

After upgrading, the installed command is:

```sh
gts9u-update --check
sudo gts9u-update --latest
sudo gts9u-update --zip /path/to/build.zip
gts9u-update --status
sudo gts9u-update --cancel
```

`--repair` is the CLI equivalent of the hidden current-build action. Download
and staging errors are reported without starting the installation.

## Data and configuration

The updater never executes the TWRP installer, writes `rootfs.img`, formats
storage, or writes `userdata`, `linuxroot`, `super`, `recovery` or `vbmeta`.
It installs Debian packages through APT with removal and unauthenticated
packages disallowed. Port configuration files use Debian conffile handling:
modified settings are retained; new defaults can be left as `.dpkg-dist`.
Home directories, dconf settings, application data, accounts, fingerprints,
SSH identity, Wi-Fi connections and Android storage are not replaced by the
fresh image. Normal package migrations can add required services or groups.

All four boot images are validated before application, written only after the
packages succeed, and verified by reading the partitions back. The updater
backs up the original boot images, modules and `/etc` in its root-only
transaction directory before installation. This matters even when two builds
share a kernel release string but carry differently signed modules.

This is not an atomic A/B system upgrade: an interrupted boot-partition write
may require TWRP recovery, and failed package maintainer scripts can leave
partially updated userspace. Detected failures restore the old boot images
and modules when possible and retain diagnostic state and backups. A failure
to restore boot images requests emergency mode instead of an automatic reboot.
Do not advertise power-loss recovery as physically validated until it has
been tested on a recoverable device.

Inspect `gts9u-update --status` and
`journalctl -u gts9u-offline-update.service` after a failure. Backups remain in
`/var/lib/tab-companion-update/transaction/backup`; starting a later update or
cancelling moves completed backups into `/var/lib/tab-companion-update/backups`
instead of deleting them. They include private system configuration and stay
accessible only to root. A failed APT transaction needs package repair before
another update; the updater does not silently discard that failure.

## Building and publishing

`build-release.sh` now produces both the normal installation ZIP and
`gts9u-update.pyz`. Upload both, plus the generated manifest, to the matching
`v<RELEASE_VERSION>` GitHub release. Never replace an existing version's assets
with a different build. The app selects the latest non-prerelease GitHub
release, selects only the SM-X910 ZIP, and validates GitHub's SHA-256 digest.
For local ZIPs, internal hashes detect corruption, not an untrusted author:
local packages must come from a trusted build of this port.

The ZIP carries `UPDATE/manifest.json` and `UPDATE/debs/` in addition to the
existing installation assets. The payload includes:

- The exact `out/local-debs` package selection installed in the fresh rootfs,
  including Companion, device integration and patched userspace components.
- `ubuntu-gts9u-hardware`, containing matching kernel modules, firmware, boot
  filesystem files and port defaults, with `/etc` files declared as conffiles.
- The desired Ubuntu package list generated from the rootfs build inputs.
- The four boot-image hashes, device, Ubuntu suite, architecture, version and
  kernel release. `vbmeta` is deliberately outside the update contract.

Future features must ship through these packages or explicit package
migrations, not only through a fresh-image setup hook. Account creation,
locale selection, filesystem layout and other first-install-only hooks are
intentionally not replayed on existing users.

## Validation in this change

`python3 scripts/test-system-update.py -v` exercises ZIP validation,
checksums, path rejection, release selection, old-format rejection, offline
success and simulated failures, boot readback/restore, the ZIP builder/reader
contract, and actual dpkg preservation of modified and pre-existing conffiles
in temporary roots. No test opens a tablet block device for writing.

The GTK4/Adwaita page was instantiated and exercised on the physical tablet
from `/tmp`, including the hidden repair control and progress display. The
read-only device, boot-partition identity and charging preflights passed on
the physical tablet, including its separate S Pen battery.
The Companion Debian package builds successfully. A full physical system upgrade
and post-upgrade hardware regression remain release gates; they have not been
performed by the non-destructive UI and transaction tests.
