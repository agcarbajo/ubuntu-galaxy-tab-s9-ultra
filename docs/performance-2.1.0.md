# Boot and runtime performance, towards 2.1.0

The working notes for the performance round: what was measured, what changed,
and what is still a candidate. Every number here comes from the development
SM-X910 unless it says otherwise, and every claim that something is *faster*
has to be a measurement before and after, not an argument.

Method, so the numbers stay comparable:

```sh
systemd-analyze                      # kernel and userspace totals
systemd-analyze blame | head -20     # per-unit duration, parallel, not a sum
systemd-analyze critical-chain       # what actually held the targets up
systemd-analyze plot > boot.svg      # when units overlapped
```

Two traps this port has already fallen into, worth repeating: `blame` adds up
to far more than the boot, because units run in parallel, and a unit near the
top of `blame` costs nothing if nothing waits for it. The question is always
which unit a *target* was waiting for.

## Baseline, 2026-11-14, release 2.0.2

```
Startup finished in 3.357s (kernel) + 59.275s (userspace) = 1min 2.632s
graphical.target reached after 59.274s in userspace
```

| Unit | Duration | Holds up |
|---|---|---|
| `ubuntu-gts9u-sensors-resume` | 45.685s | `multi-user.target` (fixed below) |
| `plymouth-quit-wait` | 22.343s | the greeter; it *is* the wait for GDM |
| `ubuntu-gts9u-audio-session@1000` | 19.773s | `multi-user.target` |
| `NetworkManager-wait-online` | 18.132s | `network-online.target` (capped below) |
| `ubuntu-gts9u-pogo-firmware` | 14.613s | `multi-user.target` |
| `ubuntu-gts9u-desktop-user` | 8.876s | the camera relays and the audio session |
| `fstrim` | 6.923s | nothing on the path |
| `ubuntu-gts9u-panel-coldboot-recover` | 3.065s | — |

The login screen is not at 59 s: `plymouth-quit-wait` ended at 28.9 s, so that
is roughly when the greeter appeared. The rest of the minute is work that
continues behind it.

## Done in this round

- **`ubuntu-gts9u-sensors-resume` is no longer a oneshot.** It is ordered
  after the display manager precisely because nothing waits for its result,
  yet as a oneshot wanted by `multi-user.target` the target waited for its
  whole 45-attempt discovery loop. `Type=simple`, the loop runs behind the
  desktop, `RuntimeMaxSec=210` stops a wedged run.
- **`NetworkManager-wait-online` capped at ten seconds.** With Wi-Fi working
  it cost 18.1 s here; with Wi-Fi broken it costs its whole timeout on every
  boot, which is half of what #11 reports.

Measured on the tablet with both changes applied as temporary drop-ins, same
day, cold boot against cold boot:

| | Before | After |
|---|---|---|
| kernel | 3.694 s | 3.318 s |
| `graphical.target` | 63.806 s | **29.401 s** |
| userspace, "startup finished" | 63.809 s | 37.738 s |
| `power-profiles-daemon` and the CPU boost start | ~63 s | 32.6 s |
| GDM starts / greeter session opens | 19.3 s / 23.0 s | 18.8 s / 21.1 s |

So the desktop's services are all up half a minute sooner, the performance
profile and the CPU boost with them, and the login screen appears when it did
before -- it never waited for the sensor recovery. The recovery itself still
succeeds in the background: `SSC ready after attempt 1`, 15 s after it starts.
No ordering cycle was logged on either boot.

The same measurement corrected the second change. A ten-second cap made
`NetworkManager-wait-online` *fail* on this unit, whose Wi-Fi takes 15 to 18 s
to associate; it is twenty seconds now, and a timeout there is no longer a
failed unit.

## What the login screen waits for

`scripts/diagnostics/boot-timeline.sh` and `boot-blockers.sh` exist because
`blame` and `critical-chain` could not answer this. Monotonic seconds, kernel
included:

```
 6.96  basic.target
 7.00  dbus.service starts            up  9.14   (2.1 s)
 7.11  panel-coldboot-recover starts  up  9.95   (2.8 s; userspace frozen 7.17-9.00)
 9.55  NetworkManager starts          up 14.05   (4.5 s)
14.85  network.target
17.07  systemd-user-sessions starts   up 18.28
18.84  gdm starts                     up 21.04
```

GDM is ordered after `systemd-user-sessions`, which is ordered after
`network.target`, which waits for NetworkManager to be *up*. So the login
screen is held by the network daemon's start, and three things stretch it:

- **The panel recovery freezes userspace.** `ubuntu-gts9u-panel-coldboot-recover`
  runs a `pm_test` suspend cycle to wake the DDIC before GDM may start, and
  from 7.17 s to 9.00 s every process on the tablet is frozen. That is where
  dbus's 2.1 s start comes from. It is necessary; whether it has to be a full
  freeze, and whether it could run before the burst at 7.0 s rather than in
  the middle of it, is the question.
- **NetworkManager waits 2.4 s for hostnamed.** Its log is silent from 9.95 s
  to 12.31 s, and the next line is `hostname: using hostnamed`.
  `systemd-hostnamed` is bus-activated and did not start until 12.2 s. A
  static hostname in NetworkManager's configuration, or hostnamed started
  early, would take that out of the greeter's path.
- **2.2 s that nothing explains yet.** Every unit `systemd-user-sessions` is
  ordered after was up at 14.85 s and it did not begin until 17.07 s. No
  daemon-reload ran then (the one from `ubuntu-gts9u-desktop-user` is at
  21.2 s, 651 ms, right as the greeter session opens, which is its own small
  cost). A bootchart is the next measurement.

Seven units started at 7.0 s finish together around 14 s -- accounts-daemon
7.5 s, udisks2 7.6 s, snapd.seeded 6.9 s, logind 4.2 s -- which is what a
shared wait looks like rather than seven slow programs.

## Idle, measured at the greeter, 2026-11-14

Twenty seconds on the login screen, nobody touching the tablet, three minutes
after boot. Wakeups are voluntary context switches per second; the probe is
`scripts/diagnostics/idle-probe.sh`.

| Process | Wakeups/s | CPU |
|---|---|---|
| `gnome-shell --mode=gdm` | 130.5 | 7.8% |
| `dbus-daemon --system` | 22.6 | 0.8% |
| `ubuntu-gts9u-fingerprint-ui` | 20.1 | 0.7% |
| `iio-sensor-proxy` | — | 1.5% |
| `kworker ufs_clkscaling_0` | 12.8 | 0.1% |

The system bus carried 491 messages in those twenty seconds, and 234 of them
are one conversation repeated 39 times: the Shell's fingerprint overlay calls
`Pulse` on `io.github.agcarbajo.Gts9uFingerprintUI` twice a second, and for
each one the broker asks the bus who the caller is (`GetConnectionUnixUser`),
asks logind for the seat's active session and for all of that session's
properties, and resolves two names on the way (`GetNameOwner`, 78 times).

That heartbeat is the visible end of the real cost. The overlay runs a 50 ms
timer for as long as the extension is enabled -- `_startPanelPoll()` in
`enable()`, stopped only in `disable()` -- and every tick, twenty times a
second, inside the compositor's main loop, it synchronises the on-screen
keyboard, decides whether to pulse, reads the panel's `fod_mode` from sysfs,
and reads the fingerprint lease file with a *synchronous* `load_contents`.
`_uiAllowed` is true whenever the built-in panel exists and the session is
active, so this is not a lock-screen cost: it runs on the unlocked desktop
too, for the whole session. A compositor that wakes 130 times a second with
nothing on screen changing is where an idle tablet's battery goes, and a
synchronous file read on that loop is a frame that can arrive late.

What it is for is real: the kernel raises no event when the panel enters
fingerprint high-brightness mode, and the overlay has to cover the screen
within a frame or two of it. So the fix is not to remove the poll but to stop
paying for it when nothing can happen:

- poll at 20 Hz only while a fingerprint operation can be in flight -- the
  lease file exists, the panel is in HBM, a hide is pending, or shortly after
  any of those -- and otherwise let the directory monitor the overlay already
  has (`_startVisualMonitor`, on `/run/gts9u-fingerprint`) wake it the moment
  a lease appears;
- make the availability lease last longer than two seconds, or renew it on
  the events that can invalidate it (session change, keyboard covering the
  target) instead of every 500 ms;
- in the broker, keep the logind proxies instead of resolving them on every
  pulse, and replace its own 250 ms tick with a single timer armed for the
  moment the lease expires.

None of this is done yet, on purpose. This is the code that makes fingerprint
unlock work, its timings were measured on the panel, and a change here has to
be accepted with a finger on the reader, on the lock screen and in a polkit
prompt, before and after. The expected gain is the Shell back near idle; the
measurement that proves it is this same table.

## Candidates, not yet done

Boot:

1. **`ubuntu-gts9u-audio-session@1000`, 19.8 s.** `Type=oneshot` with a 150 s
   timeout, after the user manager and the ADSP. Find out what it waits for
   and whether anything needs its completion before the desktop is usable.
2. **`ubuntu-gts9u-pogo-firmware` is not a candidate**, and it was nearly
   broken by treating it as one. On an ordinary boot it takes 50 ms
   (`controller already on V37`). The 14.6 s boot was a real reflash from V34,
   which is what the controller is on after a trip through Android, and
   `panel-coldboot-recover` is ordered after it on purpose: the writer holds
   the controller lock and must finish before userspace is frozen. So a boot
   that follows Android pays about 14 s before the login screen, by design.
   Making this unit `Type=simple`, as was done for the sensor recovery, would
   have let the freeze start in the middle of a flash.
3. **`ubuntu-gts9u-desktop-user`, 8.9 s.** The camera relays and the audio
   session are ordered after it, so this one is genuinely on the path; what
   takes nine seconds inside it is the question.
4. **The ordering cycle.** `sensors-resume` was `After=display-manager.service`
   *and* `WantedBy=multi-user.target`; systemd breaks such cycles by dropping
   an edge, silently. Check the journal for what it dropped and whether any
   other unit in this package does the same.
5. **`fstrim` at boot**, 6.9 s, on a UFS that does not need it then.

Runtime, where the measurement comes first:

6. What is actually running on an idle desktop, and what wakes the CPU:
   `powertop --time=60`, `systemd-cgtop -b -n 10`, `turbostat` if it works
   here, and the port's own services under `systemd-cgls`.
7. The hardware daemon, the sensor bridge and the Companion hardware service
   each hold a one-second timer; an idle tablet should not be sampling
   anything at 1 Hz. Galaxy Companion 1.0.1 already removed a Bluetooth idle
   source that re-armed itself forever -- that class of bug is worth hunting
   for deliberately rather than waiting for it to show up as battery drain.
8. Thermals and clocks under a sustained load, against the Android baseline
   the port already recorded for the Galaxy frequencies.
9. Memory: zram is on; measure what it buys and what the desktop actually
   uses after a fresh login.

Nothing in this list is a change yet. Each one needs the same treatment as the
two above: measure, find what waits for what, change one thing, measure again.
