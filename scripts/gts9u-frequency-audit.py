#!/usr/bin/env python3
"""Read frequency/idle/thermal state; optionally exercise every CPU, without tuning.

No sysfs writes, governor changes, firmware access or permanent worker processes.
CPU observations are cpufreq policy readings, not independent clock metrology.
"""
import argparse
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import platform
import time

CPU = Path('/sys/devices/system/cpu')
THERMAL = Path('/sys/class/thermal')
EXPECTED = {'policy0': 2016000, 'policy3': 2803200, 'policy7': 3360000}


def read(path):
    try:
        return path.read_text().strip()
    except OSError:
        return None


def integer(path):
    value = read(path)
    return int(value) if value and value.lstrip('-').isdigit() else None


def temperatures():
    return {read(p / 'type'): integer(p / 'temp')
            for p in sorted(THERMAL.glob('thermal_zone*'))}


def snapshot():
    policies = {}
    for p in sorted((CPU / 'cpufreq').glob('policy*')):
        fields = {f: read(p / f) for f in (
            'related_cpus', 'affected_cpus', 'scaling_driver', 'scaling_governor',
            'scaling_available_frequencies', 'scaling_boost_frequencies', 'boost')}
        fields.update({f: integer(p / f) for f in (
            'cpuinfo_min_freq', 'cpuinfo_max_freq', 'scaling_min_freq',
            'scaling_max_freq', 'scaling_cur_freq', 'cpuinfo_cur_freq')})
        expected = EXPECTED.get(p.name)
        available = {int(f) for key in ('scaling_available_frequencies',
                                      'scaling_boost_frequencies')
                     for f in (fields[key] or '').split()}
        fields['expected_max_khz'] = expected
        fields['expected_opp_registered'] = expected in available
        fields['expected_max_allowed'] = (fields['scaling_max_freq'] or 0) >= (expected or 0)
        fields['idle'] = {
            cpu: {s.name: {f: read(s / f) for f in ('name', 'usage', 'time', 'disable')}
                  for s in sorted((CPU / f'cpu{cpu}' / 'cpuidle').glob('state*'))}
            for cpu in (fields['related_cpus'] or '').split()}
        policies[p.name] = fields
    gpus = {}
    for p in sorted(Path('/sys/class/devfreq').glob('*gpu*')):
        gpus[p.name] = {f: read(p / f) for f in ('governor', 'available_frequencies',
                                                'min_freq', 'max_freq', 'cur_freq')}
        gpus[p.name]['expected_opp_registered'] = '719000000' in (
            gpus[p.name]['available_frequencies'] or '').split()
    return {'kernel': platform.release(), 'online': read(CPU / 'online'),
            'global_boost': read(CPU / 'cpufreq/boost'), 'cpu': policies, 'gpu': gpus,
            'temperatures_millicelsius': temperatures(),
            'energy_aware_scheduler': read(Path('/proc/sys/kernel/sched_energy_aware'))}


def worker(cpu, seconds, result, workload):
    os.sched_setaffinity(0, {cpu})
    data = b'gts9u-frequency-audit' * 4096
    start = time.monotonic()
    end = start + seconds
    burst_end = start + 0.012
    count = 0
    while time.monotonic() < end:
        hashlib.sha256(data).digest()
        count += 1
        if workload == 'burst' and time.monotonic() >= burst_end:
            time.sleep(0.003)
            burst_end = time.monotonic() + 0.012
    result.send({'cpu': cpu, 'bytes': count * len(data),
                 'seconds': time.monotonic() - start, 'workload': workload})
    result.close()


def exercise(cpus, seconds, limit, policies, workload='sha256'):
    initial = temperatures()
    valid = [v for v in initial.values() if v is not None]
    if not valid or max(valid) >= limit:
        raise RuntimeError('No temperature telemetry or device already at the test temperature limit')
    workers = []
    original_affinity = os.sched_getaffinity(0)
    monitor_cpus = original_affinity - set(cpus)
    peak = {p: {'requested_khz': 0, 'reported_khz': 0} for p in policies}
    max_temp = max(valid)
    try:
        # Keep sysfs/thermal sampling off the core being measured. Otherwise
        # the observer can fill its intentional idle gaps in burst workloads.
        if monitor_cpus:
            os.sched_setaffinity(0, {min(monitor_cpus)})
        for cpu in cpus:
            receiver, sender = mp.Pipe(duplex=False)
            proc = mp.Process(target=worker, args=(cpu, seconds, sender, workload))
            proc.start()
            sender.close()
            workers.append((proc, receiver))
        deadline = time.monotonic() + seconds + 3
        while any(p.is_alive() for p, _ in workers):
            values = [v for v in temperatures().values() if v is not None]
            if not values:
                raise RuntimeError('Exercise stopped: temperature telemetry unavailable')
            if max(values) >= limit:
                raise RuntimeError(f'Exercise stopped at {max(values) / 1000:.1f} C '
                                   f'(limit {limit / 1000:.1f} C); observed peaks: {peak}')
            if time.monotonic() > deadline:
                raise RuntimeError(f'Exercise timed out; observed peaks: {peak}')
            max_temp = max(max_temp, max(values))
            for name in peak:
                p = CPU / 'cpufreq' / name
                for field, filename in [('requested_khz', 'scaling_cur_freq'),
                                        ('reported_khz', 'cpuinfo_cur_freq')]:
                    peak[name][field] = max(peak[name][field], integer(p / filename) or 0)
            time.sleep(0.05)
        throughput = []
        for proc, receiver in workers:
            proc.join(timeout=1)
            if proc.exitcode != 0 or not receiver.poll(1):
                raise RuntimeError('CPU worker failed')
            throughput.append(receiver.recv())
        return {'cpus': cpus, 'peak': peak, 'throughput': throughput,
                'monitor_cpus': sorted(os.sched_getaffinity(0)),
                'max_temperature_millicelsius': max_temp}
    finally:
        for proc, receiver in workers:
            if proc.is_alive():
                proc.terminate()
            proc.join(timeout=2)
            if proc.is_alive():
                proc.kill()
                proc.join(timeout=2)
            receiver.close()
        os.sched_setaffinity(0, original_affinity)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exercise', action='store_true', help='bounded per-core and all-core load')
    parser.add_argument('--seconds', type=float, default=2.0, help='duration of each exercise (0.5-10)')
    parser.add_argument('--max-temp', type=float, default=75, help='stop temperature, Celsius (40-80)')
    parser.add_argument('--workload', choices=('sha256', 'burst'), default='sha256',
                        help='continuous SHA256, or 12 ms SHA256 bursts with 3 ms idle')
    parser.add_argument('--require-galaxy-max', action='store_true', help='fail on missing/capped maximum OPPs')
    parser.add_argument('--require-observed-max', action='store_true',
                        help='also require each core to report its maximum under its individual load')
    args = parser.parse_args()
    if not 0.5 <= args.seconds <= 10 or not 40 <= args.max_temp <= 80:
        parser.error('seconds must be 0.5-10 and max-temp 40-80')
    if args.require_observed_max and not args.exercise:
        parser.error('--require-observed-max requires --exercise')
    before = snapshot()
    result = {'before': before}
    if args.exercise:
        if set(before['cpu']) != set(EXPECTED) or before['online'] != '0-7':
            parser.error('exercise requires the expected eight-core SM8550 topology')
        if not set(range(8)) <= os.sched_getaffinity(0):
            parser.error('all eight CPUs must be available to this process')
        result['exercises'] = []
        try:
            for cpus in [[c] for c in range(8)] + [list(range(8))]:
                # Avoid accumulating heat from the preceding core's exercise.
                deadline = time.monotonic() + 30
                while any(v is not None and v >= 50000 for v in temperatures().values()):
                    if time.monotonic() >= deadline:
                        raise RuntimeError('Device did not cool below 50 C within 30 seconds')
                    time.sleep(0.5)
                result['exercises'].append(exercise(cpus, args.seconds,
                                                   args.max_temp * 1000, before['cpu'], args.workload))
        except RuntimeError as exc:
            result['error'] = str(exc)
        result['after'] = snapshot()
    print(json.dumps(result, indent=2, sort_keys=True))
    if result.get('error'):
        return 2
    if args.require_galaxy_max or args.require_observed_max:
        ok = set(before['cpu']) == set(EXPECTED) and before['online'] == '0-7'
        ok &= all(p['expected_opp_registered'] and p['expected_max_allowed']
                  for p in before['cpu'].values())
        ok &= bool(before['gpu']) and all(g['expected_opp_registered'] and
                                         int(g['max_freq'] or 0) >= 719000000
                                         for g in before['gpu'].values())
        if args.require_observed_max:
            for run in result['exercises']:
                # Sustained all-core thermal/current throttling is legitimate.
                # Require each core to reach its maximum during its own run.
                if len(run['cpus']) != 1:
                    continue
                for name, policy in before['cpu'].items():
                    if set(run['cpus']) & {int(c) for c in policy['related_cpus'].split()}:
                        ok &= run['peak'][name]['reported_khz'] >= EXPECTED[name]
        return 0 if ok else 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
