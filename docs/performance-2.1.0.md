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

- **The console is held open** (`ubuntu-gts9u-console-hold.service`), which
  is the change that moves the login screen: from 30 s to 16 s. Its own
  section, below, has the mechanism and the measurement.

The first two, measured on the tablet as temporary drop-ins, same day, cold
boot against cold boot:

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

## PID 1 keeps time like a metronome

Between 9.1 s and 12.7 s of that boot, systemd logs one completed job every
130 to 140 ms: 9.135, 9.264, 9.404, 9.550, 9.698, 9.817, 9.950 ... 11.955,
12.225, 12.375, 12.512, 12.655. Twenty-five jobs in three and a half seconds,
evenly spaced, while seven daemons that started at 7.0 s all wait for their
turn. With some 250 units to bring up, that pace *is* the boot; it is also
where the unexplained gaps come from -- a unit whose dependencies are met
still waits for PID 1 to reach it -- and why `polkit` and `hostnamed`, asked
for over the bus at about 10 s, are not even started until 12 s.

Three obvious causes were measured on the idle tablet with
`scripts/diagnostics/unit-start-probe.sh`, and none of them is it:

| | ms per transient unit | fixed CPU job |
|---|---|---|
| as it idles (`schedutil`) | 54-62 | 502 ms |
| expedited RCU | 43 | — |
| `performance` governor | 62 | 291 ms |

Expedited RCU buys about 30% on a unit start. The governor changes nothing
for a unit start, so PID 1 is not waiting for a core to speed up, although it
makes CPU-bound work 1.7 times faster.

That last number suggested starting the boot under `performance` and handing
over to the profile daemon afterwards. It was tried, with a unit that set the
governor before `sysinit.target`, and it does not pay: GDM started at 19.26 s
against 18.84 s without it. The boot is not waiting for the CPU. The unit was
removed and this is not a candidate any more.

An earlier version of this section also said that a cgroup takes 14 ms to
create and remove on this kernel, and called that the most promising lead.
That was wrong. The probe timed `mkdir` and `rmdir` as two spawned programs,
and the same pair on a tmpfs costs 9.6 ms: it was measuring process creation.
The kernel itself is not slow at this -- a system call costs 230 to 330 ns and
a fork and exec 0.9 ms -- and its configuration carries none of the debugging
options that would make it so.

None of that was the cause, and neither was the storage. The cause is in the
next section, and it was found by asking the kernel what PID 1 was doing
rather than by guessing what could be slow.

## The login screen was waiting for a serial port

A sampler started in the first moments of userspace showed the odd part
first: between 10 and 20 s of the boot the tablet is *idle*. Under one core
in use out of eight, the disk at rest, nothing blocked on I/O. A boot that
waits while the machine has nothing to do is waiting for a clock.

`ftrace` on PID 1 alone (`raw_syscalls` and `sched_switch` with
`set_event_pid`, from an early unit, which costs next to nothing) then gave
the whole answer in one boot:

```
 8.9332 s    0.05 ms  openat  (AT_FDCWD, "/dev/console", O_WRONLY|O_NOCTTY|O_CLOEXEC) = 111
 8.9332 s    0.00 ms  ioctl   (111, TCGETS2)
 8.9332 s    0.00 ms  ioctl   (111, TIOCGWINSZ)
 8.9332 s    0.01 ms  writev  (111, ..., 5) = 107
 8.9332 s  134.83 ms  close   (111)
```

(The trace records numbers; the flags and requests are decoded here, and
the device is named from them and from what the fix does.) That is systemd
printing one status line -- `[  OK  ] Started ...` -- and taking 135 ms to
close the console afterwards. It happens for every job: 91
such calls between 8.5 s and 21.5 s, **12.24 s in which PID 1 does nothing
else**, and nothing in the boot can move while PID 1 is inside a system call.
That is the metronome, and its period is the close.

Three things have to line up for it, and on this tablet they do:

- The kernel command line ends in `console=ttyMSM0,115200n8`, so
  `/dev/console` is the serial port.
- Plymouth, when its splash comes up (6.3 s), sends PID 1 `SIGRTMIN+20`:
  show status. That overrides `systemd.show_status=false`, which is on the
  command line and is why none of this was expected. It sends `SIGRTMIN+21`
  when it hands over to the greeter, which is where the metronome stops.
- Until the serial getty starts, at the very end of the boot, nobody keeps
  that port open. So each of PID 1's closes is the *last* close, the UART is
  shut down, and shutting this one down takes 134 ms. (Some of the following
  opens pay the same again to start it.)

With the getty running the same open, write and close take under a tenth of a
millisecond, which is also why none of the measurements made on the idle
tablet ever saw it.

The fix is the smallest thing that removes the third condition:
`ubuntu-gts9u-console-hold.service` keeps one descriptor on `/dev/console`
open from before Plymouth starts. It is a `sleep` with the device as its
standard input; it reads nothing, so the getty still gets its input. It has
no default dependencies and does not conflict with `shutdown.target`, because
the stop jobs print too, after the getty has gone.

Cold boot against cold boot on the development tablet, 2026-11-15:

| | as shipped | console held open | and the UFS ICE clock raised |
|---|---|---|---|
| GDM starts | 19.0 s | 11.2 s | 9.4 s |
| greeter session opens | 22.0 s | **12.2 s** | **9.6 s** |
| greeter shell registers its display (the login screen is there) | 30.1 s | **16.2 s** | **13.8 s** |
| PID 1 blocked in `close`/`open` of the console | 12.2 s | 0 | 0 |
| shutdown, from logind's announcement to the journal's last line | 11.5 - 31.5 s | 9.0 s | |

The first column is the stock boot; three more boots with nothing changed
but the storage clock landed in the same place (GDM starting at 18.0 to
19.7 s, the login screen at 28.7 to 31.0 s).
The middle column is the packaged unit, installed by hand, on the stock
storage clock: it is what the device package alone delivers. The third had
the experiment's holder and the ICE clock set by a module at 4.6 s.

The boot was healthy in both: Wi-Fi associated, the panel recovery ran, the
sensors came up. One line is new and harmless: `iio-sensor-proxy` is now
started before the sensor hub exists, exits, and is started again by the
port's own sensor recovery, as it always was; the sensors are up at 15 s
instead of 28 s.

It also settles what the storage fix is worth at boot, which the previous
round could not: nothing while PID 1 was the bottleneck (the login session
opened at 21.7 s with it and 22.0 s without), and about 2.5 s once it is not
-- the stretch from 8.4 to 12 s is then the disk at 100% and half the boot
stalled on it.

The unit start that takes 55 ms on an idle tablet is a different, smaller
thing and is still open. PID 1 makes about 4,750 system calls for one
transient unit, nearly all of them systemd walking every unit directory for
drop-ins one path component at a time. That is systemd's own cost, not this
port's.

## Storage: the UFS was running at a quarter of its speed

The tablet's storage is a UFS 4.0 part (`KLUGGARHHD-B0G1`) and the link comes
up in HS-G4 on two lanes, which is good for well over 1 GB/s. It delivered
about 300 MB/s, whatever was asked of it: 128 KiB, 1 MiB or 16 MiB requests,
one reader or eight, through the page cache or around it, with the
controller's clock scaling on or off. A ceiling that flat is not the flash.

John Stockdale had already found it on his SM-X710 and reported the same
figure for the Ultra in issue #13: the inline crypto engine sits in the path
of every UFS transfer, encrypted or not, and the bootloader leaves its core
clock on the 19.2 MHz crystal. Nothing in this kernel raises it.

`/sys/kernel/debug/clk/gcc_ufs_phy_ice_core_clk_src/clk_rate` on this tablet
read 19200000. The tablet's kernel accepts modules signed with its build
tree's key, so the claim could be tested without a flash: a module of thirty
lines (`scripts/diagnostics/ufs-ice-rate/`) asks the clock framework for
another rate on the running system. Measured on 2026-11-15, same boot, one
step after another, the root filesystem mounted throughout:

| ICE clock | read, 1 reader | read, 4 readers | 4 KiB random, median | write | 1.75 GB file, SHA-256 |
|---|---|---|---|---|---|
| 19.2 MHz, as booted | 275 MB/s | 307 MB/s | 115 µs | 296 MB/s | 5.9 s, correct |
| 100 MHz | 671 MB/s | 1210 MB/s | 102 µs | 1138 MB/s | 2.3 s, correct |
| 201.5 MHz | 705 MB/s | 1270 MB/s | 102 µs | 1565 MB/s | 2.4 s, correct |
| 403 MHz | 708 MB/s | 1269 MB/s | 100 µs | 1552 MB/s | 2.4 s, correct |

Reads are direct, 1 MiB at a time, from the root partition; the write is a
1 GiB file in 4 MiB pieces, synced; the last column reads the 2.0.4 ZIP with
a cold page cache and hashes it, which is both a figure and the check that a
faster clock still returns the right bytes. No I/O error was logged.

So: four times the sequential read, five times the write, and small random
reads unchanged, because those were never limited by the engine.

The three rates are the corners of Samsung's own clock table. Whether the top
one earns its place was measured separately, with deeper queues and another
region of the partition (rates compare within a table, not across the two):

| ICE clock | 1 reader | 4 | 8 | 16 |
|---|---|---|---|---|
| 100 MHz | 441 | 665 | 953 | 1226 MB/s |
| 201.5 MHz | 445 | 665 | 978 | 1329 MB/s |
| 403 MHz | 443 | 666 | 982 | 1324 MB/s |

403 MHz buys nothing on an HS-G4 link, and it is the one rate that needs the
CX rail at nominal, which nothing in this tree votes for; it holds today only
because the rail is left at its maximum. 201.5 MHz is therefore the top rate
in the fix. A build that brings the link up in HS-G5 would have to revisit it.

The fix is a kernel change and is **not in any build yet**. It is on the
local branch `perf/ufs-ice-clock`: a second built-in overlay,
`kernel/dts/gts9u-ufs-ice.dtso`, lists the clock with the UFS controller's
own and gives each UFS OPP a rate for it, 100 MHz at the lowest and 201.5 MHz
at the other two, so the controller's existing clock scaling carries it. Its
test passes against the pinned DTB. It needs a kernel build, a flash and a
boot before it can be called done. What it is worth at boot was measured with
the module instead, and is in the table of the previous section: nothing as
long as PID 1 was the bottleneck, about 2.5 s once the console no longer is.

`scripts/diagnostics/ufs-throughput.sh` repeats the measurement on any unit.

### Who reads at boot

The same sampler recorded what each process had read from storage, second by
second. The boot reads about 1 GB before 20 s, and one program accounts for
half of it: `galaxy-companion-boot-capture`, 518 MB in the ninth second.

It saves the running Linux's boot partitions as its dual-boot set, and to
know whether they changed it hashed them -- and every image of every saved
set, Linux's and Android's, at every boot. Only the partitions have to be
read. Galaxy Companion now keeps each saved image's hash with the identity of
the file it belonged to (device, inode, size, modification and change time)
and reads an image again only when it is no longer that file; a switch still
reads everything it writes or relies on. That is a change in the Companion
repository, covered by its dual-boot tests.

The second is not the port's: a Proton VPN unit on the development tablet
(`me.proton.vpn.split_tunneling.service`) fails and is restarted several
times during the boot, a Python start and 128 MB of reads each time.

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
6. **The UFS inline crypto engine clock**, above: measured, written, tested
   against the pinned DTB, waiting for a kernel build and a boot.
7. **`wireplumber` at the login screen: explained, not a fault.** The three
   instances are the owner's lingering user manager (12 s), the greeter's
   own (13 s), and one restart by `ubuntu-gts9u-audio-session@1000`, which
   finds the session built before the ADSP sound card existed and rebuilds
   it once (`HiFi card and output ready`, 2.2 s later). On the fast boot the
   restarted instance costs 0.35 s of CPU. The 5.5 CPU-seconds seen on the
   slow boot were not reproduced and are not worth chasing until they are.

8. What is actually running on an idle desktop, and what wakes the CPU:
   `powertop --time=60`, `systemd-cgtop -b -n 10`, `turbostat` if it works
   here, and the port's own services under `systemd-cgls`.
9. The hardware daemon, the sensor bridge and the Companion hardware service
   each hold a one-second timer; an idle tablet should not be sampling
   anything at 1 Hz. Galaxy Companion 1.0.1 already removed a Bluetooth idle
   source that re-armed itself forever -- that class of bug is worth hunting
   for deliberately rather than waiting for it to show up as battery drain.
10. Thermals and clocks under a sustained load, against the Android baseline
   the port already recorded for the Galaxy frequencies.
11. Memory: zram is on; measure what it buys and what the desktop actually
   uses after a fresh login.

Nothing in this list is a change yet. Each one needs the same treatment as the
two above: measure, find what waits for what, change one thing, measure again.
