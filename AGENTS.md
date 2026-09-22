# Agent instructions

## Project scope

This repository builds Ubuntu 24.04 arm64 with GNOME 46 on Wayland for the
Samsung Galaxy Tab S9 Ultra Wi-Fi (`SM-X910`, `gts9uwifi`). It is not Ubuntu
Touch despite any parent-directory name.

Keep changes within the existing architecture:

- `kernel/`: kernel configuration, DTS, drivers and patches.
- `packaging/`: Debian packages, services, helpers and system integration.
- `scripts/`: reproducible build, deployment and test tooling.
- `docs/`: current status, engineering conclusions and validation evidence.
- `work/` and `artifacts/`: generated or temporary data, never the definitive
  source of a fix.

Do not modify the postmarketOS reference port. Do not update the base kernel,
distribution or another foundational component incidentally while fixing an
unrelated issue.

## Required reading

Before changing code, read:

1. `README.md`
2. `docs/development-notes.md`
3. `docs/hardware-status.md`
4. `docs/ubuntu-userspace.md`
5. `docs/boot-strategy.md`
6. `docs/system-updates.md`
7. the documentation for the affected component
8. relevant recent and historical entries in `docs/porting-log.md`

Newer evidence supersedes older hypotheses. Check the current code before
reusing a historical conclusion or diagnostic image.

Run `git status` before editing. Preserve all existing tracked and untracked
work. Do not clean, reset, switch over changes, commit or push unless explicitly
requested.

## Engineering method

For each issue:

1. Record the baseline.
2. Reproduce one concrete failure.
3. Capture only the logs and measurements needed to follow the complete path.
4. Identify the cause before modifying code.
5. Add a regression test when possible.
6. Apply the smallest generic fix at the responsible layer.
7. Repeat the original reproduction exactly.
8. Check related regressions and persistence.

Always distinguish:

- measured or observed facts;
- hypotheses;
- simulated results;
- owner-confirmed physical behavior;
- tests still pending.

Compilation, enumeration, driver binding and package installation are not
physical validation.

## Build environment

Heavy builds must run on a Linux filesystem in WSL, from a path without spaces.
Verify the actual distribution, source tree, object tree, configuration,
compiler and signing certificate before reusing them.

Do not pass complex Bash through PowerShell or Git Bash command strings. Put
complex logic in a script with LF line endings and execute that script in WSL.

Use repository build scripts and inspect their inputs first. Never assume a
library or build dependency is available. Patched userspace packages must be
built from the exact pinned Ubuntu source and receive a Debian version newer
than the archive package they replace.

## Kernel and boot invariants

The device uses Android boot header v4:

- `boot`: kernel;
- `init_boot`: initramfs;
- `vendor_boot`: DTB, cmdline and vendor ramdisk;
- `dtbo`: project-specific fallback mechanism.

Preserve these invariants:

- `APPEND_DTB_TO_KERNEL=1`;
- `DISABLE_RUNTIME_DTBO=1`;
- legacy-LZ4 initramfs within the `init_boot` size budget;
- DTS changes require updating `vendor_boot`, not only the appended DTB;
- kernel and signed modules must come from the same build.

Equal `uname -r` or vermagic does not prove two builds have compatible modules.
Before deployment, compare configuration, signing certificate and exported
symbol CRCs. Keep a known-good boot image and matching module set.

Never modify `vbmeta`, `super`, recovery, PIT, EFS, persist, modem or calibration
partitions as part of an ordinary fix.

## Packaging and updates

A live-tablet change is diagnostic only until represented in this repository.
Every fix must reach both:

- clean installations;
- updates of existing installations.

Package services, helpers, patches and configuration explicitly. Increment
package versions when package contents change and update paired dependencies
when components must move together. A rootfs-only customization hook is not an
update path.

Local packages selected into `out/local-debs` are copied into the update
payload. Verify that the rootfs installed the exact same package versions. Run
an APT simulation and reject removals or unauthenticated packages.

Do not hardcode account names, UIDs, IP addresses, home directories or local
build paths in shipped code.

## Tablet access

Use current SSH details supplied for the session. Verify the server host key
before sending credentials. Identify the tablet by host key, hostname and
hardware model, not IP alone; DHCP can change after every reboot.

Do not store passwords, private keys, biometric data or personal information in
code, documentation, test output or shared logs. If SSH disappears after a
reboot, rediscover the address and verify the same host key before diagnosing a
boot failure.

A temporary suspend inhibitor is acceptable for a bounded long test. Remove it
when finished. Do not disable suspend permanently to hide a failure.

## Safe deployment

Obtain explicit authorization before any operation that:

- writes a partition;
- restarts GDM or closes the graphical session;
- reboots the tablet.

Before writing:

1. Verify device model, running OS and SSH identity.
2. Verify battery, free space, writable root and no pending update.
3. Resolve partitions through `/dev/disk/by-partlabel/`; never hardcode `sdX`.
4. Check source hash, destination size, boot header, appended DTB and AVB footer.
5. Save a root-only, hash-verified backup.
6. Write only the required partition with synchronous completion.
7. Read the destination back and compare its complete hash.
8. Update Ubuntu's saved Dualboot image when Ubuntu boot changes.
9. Leave Android's saved boot set untouched.

If any step fails, do not reboot. Preserve logs and backups, restore when safe,
and report the failure.

## Test and verification policy

Read every test before running it. Hardware diagnostics may change power,
display or peripheral state. Do not run all `test-*` scripts indiscriminately.

Choose checks appropriate to the change:

### Static checks

```sh
git diff --check
bash -n <changed-shell-scripts>
python3 -m py_compile <changed-python-files>
```

### Focused regressions

Run the focused tests documented for the affected component. Component-specific
commands, fixtures and physical acceptance matrices belong in that component's
documentation rather than this file. Tests requiring Linux APIs or native source
trees must run in WSL against the exact documented inputs, not Windows Python.

### Build and package checks

- Build the real changed kernel or userspace package.
- Inspect package name, version, architecture and dependencies.
- Check package hashes after transfer to the tablet.
- Simulate APT installation and require zero removals.
- For kernel builds, verify unchanged config, certificate, release and exported
  symbol CRCs unless an ABI change is intentional and fully packaged.
- Verify the build pipeline actually consumes every modified patch or file.

### Physical checks

After deployment, verify as applicable:

- boot and saved Dualboot hashes;
- root mounted read/write;
- relevant services active;
- package versions and package-manager consistency;
- exact original hardware reproduction;
- behavior after reboot;
- owner-visible output, not only logs.

## Documentation and completion

Update current status and durable conclusions, and append chronological evidence
to `docs/porting-log.md`. Record:

- root cause;
- source and package changes;
- versions and artifact hashes;
- tests run and results;
- physical observations;
- skipped or blocked checks;
- backup and recovery location.

Do not mark a component complete while physical validation or required hardware
is still missing.
