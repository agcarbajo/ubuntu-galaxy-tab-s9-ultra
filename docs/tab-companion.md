# Tab Companion

`Tab Companion` is the native settings application for the S Pen and for
compatible Samsung keyboard covers. `ubuntu-gts9u-companion` installs it; it
appears in GNOME's menu, and the user service applies the mappings even while
the window is closed.

## Architecture

- The GTK4/libadwaita window uses only GSettings and D-Bus.
- `tab-companion-hardware.service` detects the capabilities present and
  publishes `io.github.agcarbajo.TabCompanion.Hardware`.
- `tab-companion-spen-pairing.service` reproduces the pairing the dock starts
  when the pen goes in, authorises only a SPEN carrying both Samsung UUIDs, and
  exposes the privileged control that connects or disconnects its remote
  features.
- Only the backend touches sysfs, evdev and `uinput`.
- The backend grabs the attached cover and relays its events through
  `Tab Companion virtual keyboard`. Under "Keep the default action" it lets
  through the keys the firmware already delivers correctly, and applies the
  port's base utility to the special keys that have no native function in
  GNOME.

## Fingerprint settings (1.2.1)

The **Fingerprint** tab replaces Info. Version/kernel details live in the
header's About window. The settings page lists the current user's system
fingerprints, offers the ten anatomical finger names, adds only unused names,
and deletes one selected print after explicit confirmation. It uses the same
fprintd D-Bus API and encrypted storage as Ubuntu Settings, GDM and the lock
screen. No separate biometric store, privileged helper or PAM policy is added.
An inline link opens `gnome-control-center system users`.

Enrollment shows secure aggregate coverage, actual accepted samples, estimated
remaining placements and quality guidance. The EL721 currently usually needs
17 accepted placements. This is an estimate, not fprintd's 18 processing stages:
one placement can advance multiple stages. If the journal is unavailable, the
UI explicitly labels native processing stages rather than inventing a count.

There is no duration selector or fixed session limit. An enrollment or scan
cancels after **60 seconds without a new contact**. Device finger-present edges
(and matching fprintd-PID EL721 contact records) renew that interval, including
poor-quality contacts. Progress messages do not renew it. There is no countdown
or inactivity explanation in the UI. Escape, Cancel, window close
and screen lock also stop the operation. Blocking D-Bus calls are isolated in a
worker process, with a bounded termination fallback.

Claims exist only during an explicit operation, never while browsing the list.
Stop/Release and closing the private worker bus connection free the reader on
success, failure and cancellation. Adding rechecks the list after Claim, so a
concurrent addition in Ubuntu cannot silently be replaced. Lists refresh after
operations and on returning to the tab/window. Sharing is automatic: there is
no synchronization option and no per-print availability subtitle.
Close GNOME's own fingerprint dialog before starting a Companion operation:
GNOME 46 keeps its claim while that dialog is open.

**Test fingerprints:** one `VerifyStart("any")` operation searches the same
gallery as GNOME login, continuing across entries while the finger stays down.
The saved list stays visible and the matched row gains a green tint, accent
edge and checkmark. The result says only "Fingerprint recognized", without
additional prose. The highlight survives list refreshes and clears on the next
operation. An error is not a non-match.

Noble's original fprintd lacks the matched-name signal. The dependency
`fprintd 1.94.3-1+gts9u1` adds [claim-private matched-name reporting](../packaging/fprintd/README.md)
from the actual libfprint `FpPrint`, before terminal `VerifyStatus`. The app
requires both signals and fails safely if the name is missing/not enrolled.
No identity is inferred from secure slot numbers or journal output. PAM,
policy, libfprint recognition and encrypted storage are unchanged.

Logs remain in `~/.local/state/tab-companion/fingerprint-tests/`, including
`latest.jsonl` and timestamped files (0600). They contain UI events, finger
labels and whitelisted aggregate counters, never templates, images, secure
identities or credentials. List refreshes do not overwrite the last operation.
Cancelled and failed runs are retained. A collapsed Diagnostics section keeps
the main page focused on settings.

Validation: 34 private-bus/state tests cover a single any-scan with a named
match, missing/invalid match metadata, rejection, enrollment, duplicate
protection, single-print deletion, cancellation, renewable inactivity and
release. The daemon's virtual-device suites pass 152 tests (4 skipped),
including actual matched names, ordering, claim-private delivery, cancellation
and rejection. Tablet checks passed for scan arming, visible saved rows,
disabled destructive controls, cancellation, a 60-second no-contact timeout
(62.2 seconds including cleanup), and normal/narrow-window rendering. The
highlight/result presentation was exercised with synthetic UI state only;
neither saved print nor libfprint/PAM changed during deployment or these tests.
The user validated enrollment/testing in 1.2.0 and subsequently confirmed that
the single-touch testing redesign in 1.2.1 works correctly. Version 1.2.2 only
changes the Ubuntu Settings shortcut wording. On 2026-09-03 the owner accepted
the complete fingerprint feature for merging into main. These physical
confirmations, not synthetic presentation tests, establish the working status.

## S Pen

The page shows the orientation and state graphically, with a bar holding the
last real percentage known. The dock only reports discrete charge states; the
percentage comes from the Battery Level characteristic of the Samsung BLE
profile and is kept while the pen sleeps. No value is ever estimated.

BlueZ's `Connected` state is not enough on its own: a connection can be
recorded as live while every one of its GATT operations fails. Tab Companion
accepts the percentage only after `ReadValue` answers on the current
connection, and enables gestures or the pointer only after a valid GATT
operation. On three consecutive failures with the pen docked it discards that
one bond, reopens the dock's pairing and rebuilds it automatically. If BlueZ
does not even answer the removal, it restarts the Bluetooth service alone
before trying again.

Pairing does not use the classic Bluetooth dialog. When the pen goes in, the
Wacom command `0xea` opens the advertisement and the S Pen itself starts the
request. The service accepts it only when the physical docking, the SPEN name
and the FD6C/FEF5 UUIDs all agree. The result is stored as bonded and trusted,
with no PIN and no interaction, as in One UI.

If BlueZ keeps a bond the pen no longer recognises, two bounded failed
connection attempts with the S Pen physically docked trigger a recovery limited
to that device: the stale bond is dropped and the dock flow repeats. The
service also waits for the adapter during boot.

"Enable remote features" separates BLE from EMR writing completely. Turning it
off makes the root service cancel any pairing under way, disconnect the S Pen
without deleting its bond, and stop trying to connect or pair. The app then
only shows whether it is docked; writing and the two behaviour options keep
working. The preference is also stored under `/var/lib` so it is honoured
before anyone logs in. Turning it back on may need the pen to be docked: the
dock is the only reliable way to wake it and make it advertise again.

Bluetooth's own state is a separate condition from that preference. When the
adapter is switched off the backend disconnects the remote features, releases
any held pointer click, and the app hides Battery, Air actions and Pointer as
if they were disabled. The switch is left off and locked next to a notice to
turn Bluetooth on, but `spen-remote-enabled` is not modified. BlueZ's `Powered`
signal is handled directly: when the adapter comes back, the interface and the
service immediately recover the stored value. If it was off it stays off; if it
was on it comes back on.

"Ignore finger touches while hovering" shares Wacom proximity with the Goodix
controller. The moment `BTN_TOOL_PEN` arrives, the touchscreen releases its
active contacts and publishes no fingers until the pen leaves range. "Disable
the digitizer while docked" keeps the dock, charging and BLE alive but discards
the EMR coordinate packets. The physical IRQ is not disabled, because it also
carries the orientation and charge replies; this separation is what fixes the
stale orientation when the S Pen is reinserted the other way round. AVDD power
is shared with the panel, so this is not a full electrical shutdown.

Single, double and long presses use `BTN_STYLUS`. The six air movements use
Button State from the FD6C service and are classified as up, down, left, right,
clockwise or anticlockwise. Movement cancels the long press so that one stroke
does not fire two actions.

Gestures and pointer are alternative modes. The second follows the concept of
[PenMouseS](https://github.com/jojczak/PenMouseS) but reuses none of its gesture
classifier's increments. It moves the S Pen from `DEFAULT` (`0x10`) to
`SENSOR_ON` (`0x04`), enables the Raw Sensor Data characteristic only then, and
receives accelerometer and gyroscope at about 24 Hz. Physical calibration
identifies gyro X as the lengthwise roll, which is discarded. The
accelerometer's gravity vector rotates gyro Y/Z into screen coordinates: its
projection onto gravity gives the horizontal axis and the perpendicular gives
the vertical. That compensates for any axial roll of the pen; a dead zone
removes the bias at rest. The result becomes a native relative mouse through
`uinput`, with no overlay and no accessibility service. In Pointer mode the
digitizer's `BTN_STYLUS` becomes `BTN_LEFT`: press and release produces a
click, while holding it keeps the left button down through the movement, so
windows and other items can be dragged. If the reader disappears or the mode
changes, it forces the release so no click is left stuck. The app exposes
sensitivity, smoothing and acceleration. The direction of both axes is
calibrated physically, and the horizontal one gets an extra 1.6× gain to cover
the screen's aspect ratio. Going back to gestures stops the raw channel and
restores `0x10`, so the power-hungry sensor is not left running. Even with
pointer mode still selected, docking the pen also stops the raw channel and
uses `0x10`, so the brief charging connection can complete pairing and the
battery read. Undocking returns to `SENSOR_ON` with no intervention.

### The dock panel

Putting the pen away raises a small panel from the physical edge the pen went
into, showing the pen lying parallel to that edge with its battery percentage
and a charging bolt underneath. It follows the display's transform, so the edge
it emerges from is correct in all four rotations, and it waits for a real
orientation before showing itself rather than guessing one. It is on by default
and can be turned off under the S Pen behaviour options.

## Dual boot

The Dualboot page lists the systems whose boot sets are saved on the root
filesystem, says which one is running, and switches to the other. Switching
needs authorisation, which polkit asks for with the user's password; a toggle
in that page can install a rule that stops it asking every time. There is also
a quick settings toggle. See [dual-boot.md](dual-boot.md).

## Haptics and the on-screen keyboard

The stock firmware describes a COINDC motor enabled through TLMM GPIO18. The
mainline DTS registers it with `gpio-vibrator`, which publishes an `FF_RUMBLE`
evdev device. The hardware service is the only thing that opens that node, and
it offers the `Vibrate` D-Bus method.

GNOME Shell 46 offers no generic haptics preference for its on-screen keyboard.
The bundled extension watches only touch presses on `keyboard-key` actors and
asks the backend for a pulse. Since the GPIO is on/off only, Light/Medium/Strong
adjust the duration (24/42/66 ms), not the electrical amplitude. The Haptics
page can turn it off, and its test button plays the selected level with exactly
the same pulse a key produces.

Notification haptics are independent of the Shell extension. The session service
watches the standard `Notify` calls, groups duplicates and bursts shorter than
300 ms, and asks for a 60 ms pulse. Its switch is on by default. This route
works in the current session even while GNOME Shell holds old JavaScript in
memory until the next login.

## Pointer mode credits

The air-pointer concept is inspired by
[PenMouse S](https://github.com/jojczak/PenMouseS), created by Jakub J
(`@jojczak`) and published under GPL-3.0. Tab Companion carries no code from
the Android application: it independently implements the Samsung BLE protocol
reading, the orientation compensation, and the native Linux mouse through
`uinput`. The credit and the link also appear in "About".

## Keyboard covers

With no known cover, the section shows only a welcome and the "Compatible
keyboards" button. Connecting one for the first time stores its model and
commercial name. If it is disconnected later, its mappings stay editable and an
X forgets it and returns to the initial state.

The X910's official table and Samsung's product pages identify these five
models:

| Model | Commercial name |
|---|---|
| EF-DX900 | Galaxy Tab S8 Ultra Book Cover Keyboard |
| EF-DX910 | Galaxy Tab S9 Ultra Book Cover Keyboard Slim |
| EF-DX915 | Galaxy Tab S9 Ultra Book Cover Keyboard |
| EF-DX920 | Galaxy Tab S10 Ultra / S9 Ultra Book Cover Keyboard Slim (AI Key) |
| EF-DX925 | Galaxy Tab S10 Ultra / S9 Ultra Book Cover Keyboard (AI Key) |

The kernel tells the revisions apart by the protocol identifier and the VERSION
reply. The EF-DX920 is the only one available and physically validated;
enumeration and special keys for the other four are in place, but their
keyboards and touchpads still need a real test.

There is no "Learn" mode: the measured codes are part of the factory values.
"Reset values" restores actions, targets and physical codes in one go. On the
EF-DX920 they are Galaxy AI 760, DeX 701, Finder 710, Fn+Finder/Settings 709,
and Fn+F1–F11 757/758/759/705/254/172/224/225/113/114/115. Fn+F12 is not
listed: firmware V37 emits no event for it, so there is nothing reliable to
remap.

"Keep the default action" is not a stored mapping. For keys with no native
function, the backend applies the port's base utility: Galaxy AI opens Tab
Companion; Finder opens search; Settings opens Settings; Fn+F1/F2/F3 open
Files, the browser and a terminal; Fn+F4 opens applications; Fn+F5 opens the
overview; and DeX maximises or restores the current window. Fn+F6–F11 are
relayed unchanged and keep their native events.

Choosing another action replaces that behaviour only while the mapping is
stored. Returning to "Keep the default action", or using "Reset values",
removes the customisation and brings the base utility back.

## The action picker

Each row has a single button with an icon and a name. It opens a full,
non-recycled list, which avoids the touch bug the old dropdowns had after being
scrolled. "Open an application" shows every visible application with its icon,
name, desktop ID and a search box. "Run a command" opens a text field; the
command runs in the user's session and must not contain passwords or secrets.

"Simulate a key" opens a graphical keyboard with alphanumerics, F1–F12,
navigation and modifiers. A key can be tapped, or pressed on any physical
keyboard; Ctrl, Shift, Alt, AltGr and Super allow combinations. "Toggle the
flashlight" uses `gts9u-flashlight toggle` and is available for any key or
gesture.

Two entries are not actions on hardware. "Do nothing" is the default for S Pen
gestures and leaves the event unhandled. "Keep the default action" exists only
for keyboard keys, where there is a base utility worth falling back to.

## Historical fingerprint diagnostics (1.1.5, replaced by 1.2.0)

In the former Info page, version 1.1.5 offered **Verify saved fingerprint** (default) and
**Enroll / replace fingerprint**. Both are user-started, time-bounded and stop
with Escape. Enrollment targets the right-index slot and replaces that print
only on completion. Verification uses the saved print without enrolling or
deleting it. Test the enrolled finger, then start a separate verification using
a different finger. A non-match is a distinct result, not a generic test error;
quality retries, timeout and reader errors do not prove correct rejection.

Each run records its mode and safe aggregate results under
`~/.local/state/tab-companion/fingerprint-tests/`, including failure/cancellation.
Timestamped JSONL files are retained; `latest.jsonl` tracks the most recent run.
No template contents are logged. Legacy EL721 prints created before gts9u41
lack a saved identity and must be enrolled again before verification.

The package rebuilds the target Python's bytecode caches on upgrade. This is
necessary because normalized source timestamps and same-size edits otherwise
allow stale caches from older releases to survive. Build-host caches are not
shipped. The 1.1.5 Info widgets and Spanish match/non-match labels were exercised
on the tablet without starting a capture; physical verification remains pending.

## Languages

The interface, the pickers, the states, the model list and "About" are
available in English, Spanish, French, German, Italian and Portuguese. The
session's language is used, falling back to English.

## Validation and limits

Version 0.9.0 was built with strict schema, desktop and AppStream validation.
On the tablet the backend, the `uinput` devices, the D-Bus API, the graphical
keyboard, a `Ctrl+Alt+T` combination, the flashlight, the DX920, BLE at 100 %,
sysfs permissions and IRQ transitions were all checked. The owner physically
validated finger rejection during hover, and the digitizer being disabled and
re-enabled as the S Pen is docked and removed.

One validation reboot stopped before Tab Companion started, in the
`pm_test=platform` cycle the port uses to recover the panel after a cold boot.
The next boot completed the cycle and every check. If the tablet freezes during
boot again, that panel recovery is the first thing to look at; no relationship
with the Wacom/Goodix policies was observed.

Still pending: feeling the motor physically, calibrating the pointer with real
use, testing EF-DX900/910/915/925 and verifying their touchpads. BLE recovery
and the intermediate 90 %/80 % readings have already been validated on
hardware.

Bluetooth addresses, MACs, SSIDs and credentials must never be documented.

## Quick diagnosis

```sh
systemctl --user status tab-companion-hardware.service
systemctl status tab-companion-spen-pairing.service
gnome-extensions info tab-companion-haptics@agcarbajo
gdbus introspect --session \
  --dest io.github.agcarbajo.TabCompanion.Hardware \
  --object-path /io/github/agcarbajo/TabCompanion/Hardware \
  --only-properties
```

The main states are `PenState`, `PenBattery`, `KeyboardPresent`,
`KeyboardModel`, `RemappingAvailable`, `GestureAvailable` and
`HapticsAvailable`.

## Auto-rotation and virtual devices

The companion publishes `uinput` devices, and that interacts with how GNOME
decides whether the machine is a tablet. The real condition, read from the
shell's own code, is `MetaMonitorManager.get_panel_orientation_managed()`: when
it is false the auto-rotate button disappears **and** the screen stops
following the accelerometer.

Three things in the companion affected it, and all three are fixed:

1. **`SW_LID` on the virtual keyboard.** It was declared but never emitted.
   Declaring it was enough for UPower to publish `LidIsPresent=true` on a
   machine with no lid. The Book Cover's real lid is reported by the pogo
   controller, which only exists with the cover attached.
2. **The `BTN_MOUSE` range on the virtual keyboard.** The keyboard declared
   every code from `1` to `KEY_MAX`, and inside that lies the range udev walks
   — `0x110` to `0x11F` — to decide whether something has mouse buttons. It was
   tagged `ID_INPUT_MOUSE` and orientation stopped being managed. Now only that
   range is left out: the rest of the `BTN_*` codes remain available for the
   user's mappings, which do use them.
3. **The S Pen pointer was created at startup.** It existed always, even with
   pointer mode off, so the tablet had a permanent phantom mouse and never
   rotated. It is now created when pointer mode is entered and destroyed on the
   way out, in step with `_sync_remote_control`, with `spen-remote-mode`
   changes, and with the pen connecting. If the button was held when it is
   destroyed, it is released first so no click is left hanging.

One limit remains, and it is **not a bug in the port**: while pointer mode is
active there is a real pointer, and GNOME does not manage orientation with a
mouse present. Masking the classification was tried and is not enough: a udev
rule that clears `ID_INPUT_MOUSE` does stop the tagging, but
`PanelOrientationManaged` stays `false` because mutter looks at the device's
actual capability. Having both at once would mean injecting the movement
through mutter's remote-desktop interface instead of publishing a `uinput`
device.

## Remote-state synchronisation

The pairing service keeps its own copy of the remote-features flag in
`/var/lib/tab-companion/spen-remote-enabled`, and **everything** it does is
conditioned on it. The hardware service only sent it on change, so if the
pairing service restarted — or started in a different order, or was sent a
`false` while Bluetooth was down — its copy went stale and nothing corrected
it. With the flag at `0` it does not pair, does not connect and does not react
to the dock: the S Pen is completely dead with no log explaining why.

The hardware service now watches `NameOwnerChanged` on the pairing service's
bus name and resends the state every time that service appears.

A separate bug is on record and still unfixed: the pairing service **does not
survive a `bluetoothd` restart**. Its bus reference goes invalid, it raises
`ServiceUnknown`, and it stays alive doing nothing while burning CPU.
