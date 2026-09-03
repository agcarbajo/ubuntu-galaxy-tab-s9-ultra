# Multiple-fingerprint latency: investigation only

2026-09-03. No libfprint, firmware, secure-owner, PAM or GNOME authentication
changes accompany this report. The currently working matcher stays unchanged.

## What the current code does

Each enrollment calls `fpi_print_generate_user_id()` and persists its independent
identity, secure slot and encrypted template in an `(suay)` envelope. The TA
authenticates that identity alongside the ciphertext; replacing it arbitrarily
does not turn two templates into a valid gallery.

`el721.c:initialize_identify()` imports one envelope using
`el721_qtee_identify_init()`. The wire request contains one 256-byte identity
field, a template-data area smaller than `0x226000` bytes and optional metadata.
On an explicit secure NO_MATCH followed by a successful IdentifyFinal, the
driver imports the next entry and performs another secure capture/match. It can
continue while contact is held (45 ms scheduling yield), but it is not matching
one captured image against all entries in one TA transaction. Neither userspace
image matching nor template decryption is implemented or proposed here.

Consequently the first enrolled candidate can be fast while a later one pays
for the preceding imports, captures and non-matches. Wrong fingers must exhaust
the gallery. Prior two-finger device logs show candidate 1/2 rejected and 2/2
matched in successive seconds. That illustrates the effect, not a controlled
latency benchmark. Ten-finger hardware timing has not been measured.

Relevant code: `packaging/libfprint/el721.c` (build_gallery,
initialize_identify, handle_identify_do), `el721-gallery.h`, `el721-print-wire.h`
and `el721-qtee.c` (IdentifyInit wire layout).

## Possible alternatives, not implemented

1. **A real TA gallery under a shared enrollment identity.** Investigate the
   stock gallery serialization/loading path, so one secure capture can match
   several enrolled slots. The observed stock protocol exposes four slot IDs;
   sharing an identity alone does not establish that ten templates fit or are
   supported by one transaction. The format, aggregate buffer limits and
   enrollment/update semantics must be verified first. Existing independently
   encrypted prints cannot simply be concatenated or relabelled; re-enrollment
   or a TA-supported migration might be required.
2. **Secure reuse of a capture across independent candidates.** This would need
   an actual supported TA operation. It must not export sensor images, weaken
   identity checks or infer a match from a score/slot. Such an operation has not
   been demonstrated in the current implementation.
3. **Try frequently used fingers first.** This could reduce average latency
   while keeping the current encrypted format, but would not improve the
   all-rejected worst case and would need predictable per-user state handling.

One UI's faster user experience is consistent with a native gallery path,
but this investigation does not establish its exact implementation. A future
change should start with stock-protocol evidence and a separate test plan,
preserving password fallback and existing templates.

## Separate Companion UI limitation

Installed Ubuntu fprintd 1.94.3 has no `VerifyFingerMatched` D-Bus signal (checked
by live introspection). A terminal `VerifyStatus("verify-match", true)` for
`VerifyStart("any")` does not identify which anatomical finger matched.
Companion 1.2.0 therefore scans explicitly named prints in sequence to report
the name truthfully. It may require lifting/reapplying between candidates and
can take longer than GNOME's normal held-contact gallery flow. This only affects
the app's "Which finger is this?" action, not login or screen unlock.

Newer [fprintd API documentation](https://fprint.freedesktop.org/fprintd-dev/Device.html)
includes `VerifyFingerMatched`. A separately reviewed compatible backport or
upgrade could let the app obtain the matched name from a normal "any" scan;
that would remove this UI-specific overhead, not the driver's independent
gallery-import cost. No daemon update/backport was performed.
