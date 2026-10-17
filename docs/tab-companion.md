# Tab Companion → Galaxy Companion

Tab Companion, this port's native GNOME settings application, became
**Galaxy Companion** on 2026-10-17 and moved to its own repository:
<https://github.com/agcarbajo/galaxy-companion>. Device profiles let the same
application serve the Galaxy Tab S9 Ultra, the Galaxy S9+ and devices without
a profile; the S Pen, keyboard cover, haptics, fingerprint, dual boot, status
LED, charge limit and system update pages are documented there
(`docs/galaxy-companion.md`, `docs/device-profiles.md`, `docs/dual-boot.md`).

In this port:

- the application ships as the `galaxy-companion` package, built from the
  `external/galaxy-companion` submodule by `scripts/build-companion-package.sh`;
- `ubuntu-gts9u-companion` is a transitional package that depends on it
  (`packaging/ubuntu-gts9u-companion/`);
- the system updater is Galaxy Companion's; this port provides the device
  profile (`gts9uwifi`), the update payload, the legacy bootstrap built from the
  same modules and, for Ubuntu release upgrades, the release-specific migration
  backend. See [system updates](system-updates.md);
- updater state moved from `/var/lib/tab-companion-update` to
  `/var/lib/galaxy-companion-update`; `~/.local/state/tab-companion` became
  `~/.local/state/galaxy-companion`.

The history of the application while it lived here is in this file's git
history and in the [porting log](porting-log.md).
