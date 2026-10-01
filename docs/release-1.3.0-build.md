# Release 1.3.0 build and update readiness

## Inputs

Initial candidate runtime source: main commit `517d41b0086ecf50c6bb336940b93e5f5ebdca8d`.
The release uses a fresh kernel source/output tree at the pinned Linux rc3
commit `a13c140cc289c0b7b3770bce5b3ad42ab35074aa`, with matching signed modules,
and a fresh Ubuntu Noble desktop root filesystem. Heavy work runs in WSL
Ubuntu on the Linux filesystem under `/root/ubuntu-gts9u-release130`.
Unchanged cached userspace packages are reused only after verifying their
recorded build inputs. The compositor and fingerprint packages are rebuilt.

The compiled SM5714 battery driver is the pre-phone-experiment source,
SHA-256 `cb3d538098862861b91a9632191540cabe10a39e13802d6f94d91aa7f2139098`.
The owner confirmed USB/HDMI hub recovery after restoring the original matched
kernel on the development tablet. Neither experimental OTG current policy nor
stock discharge initialization is included in this release.

Tab Companion is 1.5.4. The other release assets are unchanged:

- `Dualboot-v1.1.0.apk`: `264ade366cc850b7609d061e1a4a5bd2d6c0cee254044277cf8ee11b35b1cb55`
- `gts9u-split.zip`: `ef60183e1db8eb2f854f29c046be858b6eeb9f271e95faf7eae31bfad822f9ff`

The full ZIP retains the TWRP installer and root filesystem image for clean
installations. Its separate update payload does not run that installer or
replace the user's root filesystem when updating an existing installation.

## Future updates

Release 1.3.0 remains a format-1 bridge readable by the published 1.2 updater.
The installed updater supports protocol 2, discovers Ubuntu versioned assets,
reads the running distribution identity, and supports same-suite kernel updates.
User accounts, home directories and local settings are preserved by the package
update path, including APT conffile handling. The README launcher now fetches
update_core, update_bundle and update_policy from one immutable revision;
the real backend import is covered by its regression test.

Distribution changes require an authenticated release-provided backend,
explicit preserve-data policy and full-system-root recovery contract. The
backend is verified and retained in a root-owned immutable directory before
execution; the lock is released only for the backend handoff. An old updater
cannot silently use the same-suite APT mechanism for a different Ubuntu suite.

This prepares the app for a separately validated Ubuntu 26.04 build. It does
not claim an implemented or physically tested Noble-to-26.04 migration engine.
The corresponding future release must supply and validate that backend and
recovery implementation before enabling a distribution upgrade.

## Verification

Passed before image construction:

- 18 update readiness cases.
- 39 system-update cases, including real APT/dpkg conffile preservation,
  rollback, corruption, suite refusal and protocol/ZIP contracts.
- 10 release rootfs privacy cases.
- 6 legacy launcher cases, including importing the complete real backend.
- 7 device build-information cases, run on WSL Ubuntu-24.04 with GI/Pango.
- S Pen efficiency, proximity suppression and pairing repair-state checks.
- Actual Companion package/resource/schema/Desktop/AppStream validation.

Final artifact validation passed:

- ZIP: 1,406,562,255 bytes, SHA-256
  `057c4537ebb8996efa901331d749d950aaa968724eee7d3da70b5400936c065d`.
- The actual 1.2.0 bundle reader accepts the format-1 Noble update.
- The ZIP contains the TWRP installer and clean rootfs image; all 21 local
  package payloads match the exact versions installed in the image.
- APT dependency checks and dpkg audit are clean; no personal accounts remain.
- All 129 module files inspected across the rootfs and update overlay have
  matching release metadata and signing key. The corresponding DER certificate
  is embedded in the shipped kernel. modinfo was isolated from the WSL host's
  builtin-module metadata to inspect the actual ARM modules.
- The appended DTB retains the verified baseline hash.
- Device 2.79 explicitly includes ext4 repair tools in offline initramfs builds.
  The final initramfs is 8,273,061 bytes, within the 8,314,880-byte budget;
  e2fsck, all 72 ELF dependency closures and splash assets pass validation.
- The completed ext4 image passes the builder's filesystem check. Boot bundle
  and update payload validators pass.

The build manifest and machine-readable audit are retained with local artifacts.
Initial publication (subsequently hidden):
https://github.com/agcarbajo/ubuntu-galaxy-tab-s9-ultra/releases/tag/v1.3.0
The final ZIP has not been physically installed on the development tablet.

## 2026-10-01: audio correction and replacement candidate

The September 30 candidate was returned to draft after the owner reproduced
Dummy Output. It must not be republished unchanged. Device 2.81 replaces the
single early refresh with bounded, outcome-checked recovery. It passed the
captured failure, nine behavioral regressions, two physical reboot checks and
owner-confirmed speaker playback and camera capture. See audio-startup.md.
The replacement candidate will reuse the verified kernel and clean Noble rootfs,
install its matching Device 2.81 package and regenerate the complete image,
boot bundle and update ZIP. The replacement manifest records its source revision
and hashes. Its artifact verification is pending; it remains unpublished.
