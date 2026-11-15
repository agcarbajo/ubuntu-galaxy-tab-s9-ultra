#!/usr/bin/python3
"""Sample the first seconds of userspace: the system four times a second,
every process once a second.

It answers the two questions `systemd-analyze` cannot: is the boot waiting
for the CPU, the disk, or neither -- and which process is doing the reading.
Run it from a unit with DefaultDependencies=no wanted by sysinit.target
(see pid1-ftrace.sh for the shape), for one boot, and remove it afterwards.
Everything goes to /run/gts9u-boot-sample:

  samples   uptime | sda: reads sectors_read ms_reading writes
            sectors_written in_flight io_ticks | the cpu line of /proc/stat
            | running blocked | PSI totals in us: io some, io full, cpu some
  procio    second pid comm read_bytes      (processes past 4 MB; a process's
            figure includes the children it has reaped, so PID 1's is the sum
            of every service that has already exited)
  proccpu   second pid comm utime+stime_ticks last_cpu
"""
import os
import time

OUT = '/run/gts9u-boot-sample'
os.makedirs(OUT, exist_ok=True)
samples = open(OUT + '/samples', 'w', buffering=1)
procio = open(OUT + '/procio', 'w', buffering=1)
proccpu = open(OUT + '/proccpu', 'w', buffering=1)


def uptime():
    with open('/proc/uptime') as f:
        return float(f.read().split()[0])


def system():
    d = ''
    with open('/proc/diskstats') as f:
        for line in f:
            p = line.split()
            if p[2] == 'sda':
                d = ' '.join((p[3], p[5], p[6], p[7], p[9], p[11], p[12]))
                break
    c = run = blk = ''
    with open('/proc/stat') as f:
        for line in f:
            p = line.split()
            if p[0] == 'cpu':
                c = ' '.join(p[1:8])
            elif p[0] == 'procs_running':
                run = p[1]
            elif p[0] == 'procs_blocked':
                blk = p[1]
    psi = []
    try:
        with open('/proc/pressure/io') as f:
            for line in f:
                psi.append(line.split()[-1].split('=')[1])
        with open('/proc/pressure/cpu') as f:
            psi.append(f.readline().split()[-1].split('=')[1])
    except OSError:
        pass
    return d, c, run, blk, ' '.join(psi)


def processes(sec):
    for pid in os.listdir('/proc'):
        if not pid.isdigit():
            continue
        try:
            with open('/proc/%s/stat' % pid) as f:
                stat = f.read()
            close = stat.rindex(')')
            comm = stat[stat.index('(') + 1:close]
            rest = stat[close + 2:].split()
            ticks = int(rest[11]) + int(rest[12])       # utime + stime
            cpu = rest[36]                              # processor last run on
            if ticks >= 5:
                proccpu.write('%d %s %s %d %s\n' % (sec, pid, comm.replace(' ', '_'), ticks, cpu))
            with open('/proc/%s/io' % pid) as f:
                for line in f:
                    if line.startswith('read_bytes:'):
                        rb = int(line.split()[1])
                        if rb > 4000000:
                            procio.write('%d %s %s %d\n' % (sec, pid, comm.replace(' ', '_'), rb))
                        break
        except (OSError, ValueError, IndexError):
            continue


end = time.monotonic() + 75
last = -1
while time.monotonic() < end:
    up = uptime()
    d, c, run, blk, psi = system()
    samples.write('%.2f | %s | %s | %s %s | %s\n' % (up, d, c, run, blk, psi))
    sec = int(up)
    if sec != last and sec <= 40:
        last = sec
        processes(sec)
    time.sleep(0.25)
