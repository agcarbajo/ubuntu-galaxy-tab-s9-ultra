#!/usr/bin/env python3
"""Own one boot-long CDSP session and its temporary power vote."""
import fcntl
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

ROOT = Path('/opt/gts9u-npu-session')
RUNTIME = Path('/opt/gts9u-npu-bionic')
NATIVE = Path('/opt/gts9u-npu')
STATE = Path('/run/gts9u-npu')
STOP_STAMP = STATE / 'cdsp-stopped-monotonic'
# Downstream CDSP teardown reports completion before every firmware/GLINK state
# is reusable. Ordinary clients share one boot-long session, so this interval
# applies only after an explicit service stop.
RESTART_SETTLE_SECONDS = 60.0
stopping = False


def stop_requested(_sig, _frame):
    global stopping
    stopping = True


def notify(message):
    address = os.environ.get('NOTIFY_SOCKET')
    if address:
        if address.startswith('@'):
            address = '\0' + address[1:]
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.sendto(message.encode(), address)


def find_cdsp():
    return [p for p in Path('/sys/class/remoteproc').glob('remoteproc*')
            if (p / 'name').read_text().strip() == 'cdsp']


def main():
    if os.geteuid() != 0:
        raise RuntimeError('The experimental NPU session requires root')
    STATE.mkdir(mode=0o700, exist_ok=True)
    lock = (STATE / 'lock').open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, stop_requested)
    ready = STATE / 'power-ready'
    power_stop = STATE / 'power-stop'
    ready.unlink(missing_ok=True)
    power_stop.unlink(missing_ok=True)
    loaded = []
    children = []
    logs = []
    started = False
    cdsp = None

    # RuntimeDirectoryPreserve keeps this marker across service invocations but
    # not across a reboot. CLOCK_BOOTTIME includes suspend and is independent of
    # wall-clock changes.
    try:
        elapsed = time.clock_gettime(time.CLOCK_BOOTTIME) - float(STOP_STAMP.read_text().strip())
    except (FileNotFoundError, ValueError):
        elapsed = RESTART_SETTLE_SECONDS
    if 0 <= elapsed < RESTART_SETTLE_SECONDS:
        time.sleep(RESTART_SETTLE_SECONDS - elapsed)

    def load(name, transient=True):
        if Path('/sys/module', name).exists():
            if transient:
                raise RuntimeError(f'{name} is already loaded outside this session')
            return
        subprocess.run(['insmod', str(ROOT / 'modules' / (name + '.ko'))], check=True)
        if transient:
            loaded.append(name)

    def spawn(name, argv, env):
        log = (STATE / (name + '.log')).open('w')
        logs.append(log)
        child = subprocess.Popen(argv, env=env, stdout=log, stderr=subprocess.STDOUT)
        children.append(child)
        return child

    try:
        load('gts9u_cdsp', transient=False)
        candidates = find_cdsp()
        if len(candidates) != 1:
            raise RuntimeError('Expected exactly one CDSP device')
        cdsp = candidates[0] / 'state'
        if cdsp.read_text().strip() != 'offline':
            raise RuntimeError('CDSP is already active outside this session')
        load('system_heap', transient=False)
        load('gts9u_cdsp_intents_probe')
        load('gts9u_fastrpc_prepared')
        env = os.environ.copy()
        for key in ('LD_PRELOAD', 'LD_LIBRARY_PATH', 'GTS9U_WAIT_DEVICE'):
            env.pop(key, None)
        pipeline = spawn('bootstrap', [str(ROOT / 'bin/npu-bootstrap-traffic')], env)
        native_env = dict(env, LD_LIBRARY_PATH=str(NATIVE / 'lib'),
                          ADSP_LIBRARY_PATH=str(NATIVE / 'dsp'), DSP_LIBRARY_PATH=str(NATIVE / 'dsp'))
        daemon = spawn('daemon', [str(NATIVE / 'bin/cdsprpcd')], native_env)
        qnn_env = dict(env, LD_LIBRARY_PATH=str(RUNTIME / 'lib'),
                       ADSP_LIBRARY_PATH=str(RUNTIME / 'dsp'), DSP_LIBRARY_PATH=str(RUNTIME / 'dsp'),
                       GTS9U_NPU_READY=str(ready), GTS9U_NPU_STOP=str(power_stop))
        keeper = spawn('power', [str(RUNTIME / 'bin/linker64'), str(ROOT / 'bin/npu-power-keeper')], qnn_env)
        time.sleep(1)
        if stopping:
            return
        started = True
        cdsp.write_text('start\n')
        deadline = time.monotonic() + 10
        while not ready.exists():
            if stopping:
                return
            if keeper.poll() is not None or daemon.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError('CDSP power bootstrap failed; inspect /run/gts9u-npu/*.log')
            time.sleep(.05)
        pipeline.kill()
        pipeline.wait(timeout=5)
        # Validate initialization, real execution and teardown before readiness.
        check = spawn('selftest', [str(RUNTIME / 'bin/linker64'),
                                  str(RUNTIME / 'bin/probe-npu-htp'), '100'], qnn_env)
        try:
            result = check.wait(timeout=15)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError('HTP startup self-test timed out') from exc
        evidence = (STATE / 'selftest.log').read_text()
        if result or 'PASS HTP MatMul+Relu runs=100 ' not in evidence:
            raise RuntimeError('HTP startup self-test failed')
        print('NPU ready: startup self-test passed, 100 HTP executions.', flush=True)
        notify('READY=1\nSTATUS=HTP verified; temporary CDSP power workaround active')
        while not stopping:
            if keeper.poll() is not None or daemon.poll() is not None:
                raise RuntimeError('NPU power owner or FastRPC daemon exited')
            time.sleep(.2)
    finally:
        notify('STOPPING=1\nSTATUS=Stopping CDSP before releasing the power owner')
        # Explicit service stops still perform an orderly remoteproc shutdown.
        # Normal system suspend does not stop this unit: tearing CDSP down just
        # before PSCI poisons AOSS wake state until the next full OS boot.
        if started and cdsp.read_text().strip() != 'offline':
            cdsp.write_text('stop\n')
        for child in children:
            if child.poll() is None:
                child.kill()
        for child in children:
            child.wait(timeout=15)
        for log in logs:
            log.close()
        for name in reversed(loaded):
            subprocess.run(['rmmod', name], check=True)
        ready.unlink(missing_ok=True)
        power_stop.unlink(missing_ok=True)
        if started:
            STOP_STAMP.write_text(f'{time.clock_gettime(time.CLOCK_BOOTTIME)}\n')
        print('NPU stopped; transient modules released.', flush=True)


if __name__ == '__main__':
    if sys.argv[1:] == ['--help']:
        print('usage: run-npu-session.py\n\nManaged system service; start it with systemctl start gts9u-npu.service.')
        raise SystemExit(0)
    if sys.argv[1:]:
        print('run-npu-session.py: no arguments are accepted', file=sys.stderr)
        raise SystemExit(2)
    main()
