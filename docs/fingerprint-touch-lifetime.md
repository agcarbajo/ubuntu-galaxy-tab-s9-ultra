# Consume the fingerprint contact through finger-up

The owner reported that touching the optical reader subsequently clicks the
content underneath it. The Goodix FOD code has a matching contact-lifetime
bug: `fod_enable_store(false)` clears `fod_suppressed_slots`, and the touch
filter exits immediately when FOD is disabled. If authentication finishes
while the finger is still down, subsequent coordinate MOVE/RELEASE packets
can therefore enter the ordinary input stream. An overlay which disappears
on authentication completion cannot reliably own this physical contact.

`retain-goodix-fod-contact-until-release.patch` fixes that lifetime:

- Disabling FOD preserves the already suppressed contact slots.
- MOVE packets for those contacts remain suppressed, even outside the reader.
- Their physical coordinate RELEASE is consumed and clears only that slot.
- Other fingers and subsequent ordinary taps continue normally.
- A fresh PRESS clears a stale slot if firmware omitted its earlier RELEASE.
- Closing FOD still resets its public state to idle; a later suppressed
  RELEASE does not publish an event to a closed FOD session.

Suspend clears retained slots with input IRQs disabled, even when the reader
has already been turned off. The patch does not add a global
touch grab, modify GNOME input picking, or alter fingerprint authentication.
The build script applies it to both clean and existing patched kernel trees.

## Validation and deployment status, 2026-09-08

Run `python3 scripts/test-goodix-fod-contact.py`. It extracts the production
functions from the existing FOD patch, applies the follow-up patch with zero
fuzz, and compiles the original and corrected C functions using `-Wall
-Werror`. The original reproduces the held-contact loss; the corrected code
passes tests of disable-while-held, movement outside the region, other fingers,
physical release, subsequent taps, missing-release slot reuse, FOD notification
semantics, repeated disable, hardware mode-write failure, and suspend with
the reader enabled or disabled. This is a
userspace driver-logic harness, not a full kernel build or a physical test.

**Not installed on the tablet yet.** The running build #7 has
`CONFIG_TOUCHSCREEN_GOODIX_BERLIN_CORE=y`, so this fix requires a new kernel
boot image. Its matching Galaxy/Gunyah runtime9 source/object tree and signing
material were not found on the tablet; previous records place the build on
PC-ARTURO. Do not rebuild from an unrelated baseline or replace the working
module/signature set just to apply this change.

Continue using an isolated copy of the validated build tree. Preserve its
config, signing certificate, Gunyah/fingerprint ABI and early Galaxy OPP
overlay. Validate and back up the candidate before changing boot, notify the
owner before rebooting, and physically test fingerprint authentication over a
clickable control: hold through success, move, release, then make a new tap.
Only the new tap should reach the underlying UI. Test another simultaneous
finger and ordinary touches outside the active reader too. Refresh the saved
Ubuntu boot image only after the new boot has passed validation.
