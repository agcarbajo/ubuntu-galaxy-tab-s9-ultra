#!/bin/bash
# Record every system call PID 1 makes, and every time it is switched out,
# from the first moments of userspace until a given uptime, with ftrace.
# This is how the 134 ms close() of /dev/console was found: nothing else on
# the tablet could say what PID 1 was *inside* while the boot stood still.
#
# It costs next to nothing (the events are filtered to one pid in the kernel)
# and writes nothing to storage: the copy goes to /run.
#
# To use it for one boot, as root:
#
#   install -m0755 pid1-ftrace.sh /usr/local/lib/pid1-ftrace.sh
#   systemd-run is too late; make it a unit:
#
#     [Unit]
#     DefaultDependencies=no
#     [Service]
#     ExecStart=/usr/local/lib/pid1-ftrace.sh 24
#     [Install]
#     WantedBy=sysinit.target
#
#   enable it, reboot, read /run/pid1.ftrace, then remove both files.
#
# Lines look like
#   systemd-1 [004] ..... 8.933200: sys_enter: NR 57 (6f, 0, 0, ...)
#   systemd-1 [004] ..... 9.068030: sys_exit: NR 57 = 0
# and the numbers are arm64 system call numbers (57 close, 56 openat,
# 64 write, 66 writev, 22 epoll_pwait, 435 clone3).
set -u
until_uptime=${1:-24}
T=/sys/kernel/tracing
mountpoint -q $T || mount -t tracefs nodev $T
echo 0 > $T/tracing_on
echo > $T/trace
echo 24000 > $T/buffer_size_kb
echo mono > $T/trace_clock 2>/dev/null || true
echo 1 > $T/set_event_pid
echo 1 > $T/events/raw_syscalls/sys_enter/enable
echo 1 > $T/events/raw_syscalls/sys_exit/enable
echo 1 > $T/events/sched/sched_switch/enable
echo 1 > $T/tracing_on
while read -r up _ < /proc/uptime; [ "${up%.*}" -lt "$until_uptime" ]; do sleep 0.5; done
echo 0 > $T/tracing_on
cat $T/trace > /run/pid1.ftrace
echo 0 > $T/events/raw_syscalls/sys_enter/enable
echo 0 > $T/events/raw_syscalls/sys_exit/enable
echo 0 > $T/events/sched/sched_switch/enable
echo > $T/set_event_pid
echo > $T/trace
echo 1408 > $T/buffer_size_kb
echo 1 > $T/tracing_on
