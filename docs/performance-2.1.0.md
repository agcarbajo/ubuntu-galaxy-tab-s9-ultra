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

Expected after both, to be confirmed on the next healthy boot: `multi-user.target`
lands near the next longest wanted unit, so roughly 20-25 s of userspace
instead of 59 s. The greeter may or may not move, depending on whether GDM was
itself waiting behind `multi-user.target`; `systemd-analyze critical-chain`
and a search for `Found ordering cycle` in the journal will say which.

## Candidates, not yet done

Boot:

1. **`ubuntu-gts9u-audio-session@1000`, 19.8 s.** `Type=oneshot` with a 150 s
   timeout, after the user manager and the ADSP. Find out what it waits for
   and whether anything needs its completion before the desktop is usable.
2. **`ubuntu-gts9u-pogo-firmware`, 14.6 s.** A firmware update for a keyboard
   cover that may not even be attached. It should cost nothing when no cover
   is present, and nothing waits for it when one is.
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
