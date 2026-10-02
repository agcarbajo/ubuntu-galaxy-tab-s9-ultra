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
The replacement candidate reuses the verified kernel and clean Noble rootfs,
installs its matching Device 2.83 package and regenerates the complete image,
boot bundle and update ZIP. The replacement manifest records its source revision
and hashes. Its artifact verification passed as recorded below; publication is
recorded in the final section.

The replacement candidate also includes Device 2.83's camera enumeration rule,
preventing the port's own V4L2 compatibility outputs from appearing as duplicate
PipeWire camera inputs. The native cameras and direct V4L2 relay remain available;
see audio-startup.md for the graph, relay and Lua scope checks.

### Final replacement artifact (2026-10-01)

Replacement runtime revision: 68b1963b6cdeed50989174498550881c7bee6371.
The completed candidate includes Device 2.83 in both the clean rootfs and update
payload; package SHA-256 c4261d742628d5c3b37ed9c309fc238a67ee89942b4be3c620e1f7b3f17c2794.
The live-tablet package differs only in the IRQ/TUN modules for its matched
baseline kernel, retaining its installed signing set. All native helpers and
remaining payload/control files are identical. Recovery and
camera configuration source bytes match the release image and update package.
The actual ext4 image was inspected for both helpers, the audio unit and the
camera rules, and each matched the committed source. Filesystem checking,
boot/update validators, the actual 1.2 reader, 129 module signature/release checks,
all 21 installed package versions, APT/dpkg and fresh-account checks pass.
The final initramfs is 8,273,103 bytes with 72 complete ELF dependency closures.

Corrected ZIP: 1,406,825,122 bytes, SHA-256
49ea916f5229529a537ef6e7dddcc6a130d913a0cfbbc4b8b6121dc501214dcf.
Clean ext4 image SHA-256:
f8f4b247de6630221137493ed443dc5265d7339e81dc4a615a6506b2e13fd4c6.
Local shipping assets and audit/manifest are in artifacts/release-v1.3.0-corrected.
The APK and partition split ZIP remain byte-identical to the previous release.

The owner confirmed audio and camera operation and the disappearance of duplicate
choices on the updated development installation. The full corrected ZIP itself
has not been physically installed. The withdrawn initial candidate was replaced
before publication, as recorded below.

### Corrected release published (2026-10-01)

Following explicit owner authorization, replaced the draft's old ZIP with the
corrected full artifact and updated its notes. Moved v1.3.0 from the original
517d41b runtime revision to 68b1963b6cdeed50989174498550881c7bee6371.
GitHub's uploaded sizes and SHA-256 digests matched all three local shipping
artifacts before publication. Published v1.3.0 as the latest stable release and
verified the public release API reports exactly the corrected ZIP, unchanged
Dualboot-v1.1.0.apk and unchanged gts9u-split.zip with matching digests.

Public release:
https://github.com/agcarbajo/ubuntu-galaxy-tab-s9-ultra/releases/tag/v1.3.0
The artifact source tag stays on the runtime revision; subsequent documentation
commits do not change the shipped code. No additional tablet operation occurred.

## 2026-10-02: restart-trigger replacement candidate

Runtime revision b6500f2dd18c18d659e05faa7cdca872ab2386ec packages Companion
1.5.5 to protect its offline trigger from PackageKit cancellation. Device 2.83,
the kernel and DTB are unchanged. The full build completed with clean ext4,
TWRP/boot and update payload validation. The audited image contains the exact
committed update_core/update_page plus the unchanged audio helpers and camera
configuration. All 21 selected local packages match the installed rootfs and ZIP
payload, and the published 1.2 reader accepts the format-1 update. All 129 module
signature/release checks, shipped kernel certificate and fresh-account/APT/dpkg
checks pass.

Candidate ZIP: 1,406,677,123 bytes, SHA-256
12fc1b5496a8de583c9f81973fab2b49723bfea0c5cc6fc90471ab06b21edd6a.
Rootfs image: 4,769,972,224 bytes, SHA-256
49c27af523d4d5790ab9d83c4cba429e6c672bbf23a379917cc8f93d2a427351.
Initramfs: 8,273,036 bytes; all 72 ELF dependency closures and budget pass.
Companion package SHA-256:
148342807bf46705485450902f4077ff121a7a5daec5411cdef3ae430cafc315.
The Windows ZIP copy matches the Linux artifact digest. Earlier artifacts remain
preserved; physical offline acceptance and GitHub replacement are pending.

## 2026-10-02: corrected package ownership candidate

Runtime source: 82264fcf8dd2a2bcfb3065421c73793084acccf7. The trigger-only
candidate above failed physical offline installation because its hardware
package duplicated Device's signed TUN module. The installer restored the
original boot images; pending packages were configured and the baseline
modules restored before retrying. That candidate was never uploaded.

Regenerated the update payload with hardware package 1.3.0-1 and the generic
non-directory ownership collision gate. Reused the verified clean ext4 image
49c27af523d4d5790ab9d83c4cba429e6c672bbf23a379917cc8f93d2a427351 and matching
boot bundle from the Companion 1.5.5 build: their source inputs did not change.
The exact repository payload and TWRP ZIP builders were used. Bundle validation
must receive UBUNTU_WORKDIR for this build; a first invocation without it read
the unrelated default bundle and was discarded. Validation with the actual
build inputs passes, as does complete payload hashing.

Final candidate: 1,406,414,137 bytes; SHA-256
2364644bff1fb0e5e8371a5833d2b31fbd2bbfe86958d9f0d56b6f057cf6640d.
The 787 tracked source input hashes, manifest and audit are retained beside
artifacts/release-v1.3.0-updatefix-final. All 21 selected local package versions
match the clean rootfs and ZIP. All 129 signed module/release checks, actual
shipped kernel certificate, 1.2 reader, fresh-account and APT/dpkg checks pass.
No overlapping package file remains. The 44 focused updater, launcher and
future-readiness cases pass, including real dpkg co-installation of the two
module packages. Windows copy and unchanged APK/split digests are verified.
Physical retry and republication remain pending at this point.

The exact final ZIP was transferred and verified on the tablet. Preparation
completed with authenticated dependency downloads and a clean APT audit.
PackageKit Offline.Cancel again left the ready trigger intact. At 74% charging,
all staged payload bytes and retained baseline boot backups passed verification.
The explicitly authorized offline retry completed and returned in 211 seconds:
boot ID 147dfb1b-7eea-4af7-88a0-fd5d0e3529b4, state complete, Companion 1.5.5,
Device 2.83 and hardware 1.3.0-1. All four boot partitions and Ubuntu's saved
set match the final payload. Android's saved set and seven recorded private
identity/account/network/fingerprint files match their original hashes.
APT/dpkg are clean and root is writable. GDM, NetworkManager, ADSP, pd-mapper,
S Pen pairing and the audio-session helper are active. The helper recovered
an incomplete initial graph and exposed the native HiFi sink; PipeWire has
four native camera sources and fprintd exposes its device. IRQ/TUN signing keys
match the shipped 4E7E2D2DAD2473CB62E428FF13BEC8366ADDA0EB kernel certificate.
Physical owner hardware confirmation and release republication follow separately.
The exact clean-install image remains in the ZIP; a fresh TWRP installation of
this replacement was not physically performed. Backups remain root-only under
/var/lib/tab-companion-update/transaction/backup, with earlier completed backups
archived under /var/lib/tab-companion-update/backups. Private diagnostic copies
remain under /var/lib/gts9u-diagnostics/update-marker-20261002.
