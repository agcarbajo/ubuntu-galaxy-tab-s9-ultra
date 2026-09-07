#!/usr/bin/python3
"""Managed local inference engines for the Galaxy Tab S9 Ultra."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import urllib.request
import dbus

BIONIC = Path('/opt/gts9u-npu-bionic')
NPU_ROOT = Path('/opt/gts9u-npu-llama')
NATIVE_ROOT = Path('/opt/gts9u-npu-vulkan')
SERVICE = 'gts9u-npu.service'
CLIENT_LIMIT = 40
USERS_LOCK = '/run/lock/gts9u-npu-users.lock'
COUNT_LOCK = '/run/lock/gts9u-npu-client-count'


def inhibit_sleep():
    bus = dbus.SystemBus()
    manager = bus.get_object('org.freedesktop.login1', '/org/freedesktop/login1')
    return manager.Inhibit('sleep', 'Galaxy Tab NPU client', 'NPU inference is active',
                           'block', dbus_interface='org.freedesktop.login1.Manager').take()


def acquire_npu_session():
    """Reserve one client slot without restarting CDSP inside this boot."""
    counter = open(COUNT_LOCK, 'r+')
    fcntl.flock(counter, fcntl.LOCK_EX)
    users = open(USERS_LOCK, 'r+')
    try:
        counter.seek(0)
        text = counter.read().strip()
        count = int(text) if text.isdigit() else 0
        active = subprocess.run(['systemctl', 'is-active', '--quiet', SERVICE]).returncode == 0
        if active and count >= CLIENT_LIMIT:
            raise RuntimeError(
                'La sesión NPU alcanzó su límite seguro de clientes en este arranque; '
                'reinicia Ubuntu antes de cargar otro modelo')
        if not active:
            fcntl.flock(users, fcntl.LOCK_EX)
            subprocess.run(['systemctl', 'start', SERVICE], check=True, timeout=120)
            count = 0
            fcntl.flock(users, fcntl.LOCK_SH)
        else:
            fcntl.flock(users, fcntl.LOCK_SH)
            subprocess.run(['systemctl', 'start', SERVICE], check=True, timeout=120)
        deadline = time.monotonic() + 30
        while not Path('/run/gts9u-npu/power-ready').exists():
            if (subprocess.run(['systemctl', 'is-active', '--quiet', SERVICE]).returncode
                    or time.monotonic() >= deadline):
                raise RuntimeError('La NPU no terminó de recuperar FastRPC tras la suspensión')
            time.sleep(.1)
        counter.seek(0)
        counter.truncate()
        counter.write(f'{count + 1}\n')
        counter.flush()
        return users
    except Exception:
        users.close()
        raise
    finally:
        fcntl.flock(counter, fcntl.LOCK_UN)
        counter.close()


def wait_for_server(process, url, log_path, timeout=180):
    for _ in range(timeout * 2):
        if process.poll() is not None:
            raise RuntimeError('El motor terminó durante la carga. Consulta ' + str(log_path))
        try:
            with urllib.request.urlopen(url + '/health', timeout=1) as reply:
                if reply.status == 200:
                    return
        except OSError:
            pass
        time.sleep(.5)
    raise RuntimeError('El motor agotó el tiempo de arranque. Consulta ' + str(log_path))


def stop_process(process):
    if process is None or process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=10)


def run_chat(args, model, engine, log_path):
    uses_npu = engine == 'npu'
    root = NPU_ROOT if uses_npu else NATIVE_ROOT
    binary = root / 'bin/llama-server'
    if not binary.is_file():
        raise RuntimeError(f'No está instalado el motor {engine}: {binary}')
    url = f'http://127.0.0.1:{args.port}'
    batch = 32 if args.mmproj else 128
    cmd = [str(binary), '-m', str(model), '-c', str(args.context), '-b', str(batch), '-ub', str(batch),
           '-np', '1', '-t', str(args.threads), '--host', '127.0.0.1', '--port', str(args.port),
           '--jinja', '--chat-template-kwargs', '{"enable_thinking":false}', '--log-verbosity', '4']
    if args.mmproj:
        cmd += ['--mmproj', str(args.mmproj.resolve(strict=True))]
    if uses_npu:
        cmd += ['--device', 'HTP0', '-ngl', str(args.npu_layers)]
    elif engine == 'gpu':
        cmd += ['--device', 'Vulkan0', '-ngl', '999', '--no-repack']
    else:
        cmd += ['-ngl', '0']

    env = dict(os.environ)
    if uses_npu:
        env.update(LD_LIBRARY_PATH=f'{root}/lib:{BIONIC}/lib',
                   LD_PRELOAD=f'{BIONIC}/lib/liblog.so:{BIONIC}/lib/libm.so',
                   ADSP_LIBRARY_PATH=f'{root}/dsp;{BIONIC}/dsp',
                   DSP_LIBRARY_PATH=f'{root}/dsp;{BIONIC}/dsp')
        env.pop('GTS9U_WAIT_DEVICE', None)
        env.pop('GGML_HEXAGON_OPFILTER', None)
        env['GGML_HEXAGON_PROFILE'] = '0'
        env.pop('GGML_HEXAGON_IOVA_WINDOW', None)
        if args.memory_window:
            env['GGML_HEXAGON_IOVA_WINDOW'] = str(args.memory_window_mib)
        launcher = [str(BIONIC / 'bin/linker64')]
    else:
        env['LD_LIBRARY_PATH'] = f'{root}/lib:' + env.get('LD_LIBRARY_PATH', '')
        launcher = []

    lock_file = None
    inhibitor = None
    process = None
    try:
        if uses_npu:
            lock_file = acquire_npu_session()
            inhibitor = inhibit_sleep()
        with log_path.open('w') as log:
            process = subprocess.Popen(launcher + cmd, env=env, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            wait_for_server(process, url, log_path)
            log_text = log_path.read_text(errors='replace')
            layers = re.findall(r'offloaded (\d+)/(\d+) layers', log_text)
            loaded, total = map(int, layers[-1]) if layers else (0, 0)
            if uses_npu and (not layers or loaded != min(args.npu_layers, total) or loaded == 0):
                raise RuntimeError('No se confirmó el reparto solicitado de capas en Hexagon')
            if engine == 'gpu' and loaded == 0:
                raise RuntimeError('No se confirmó la carga del modelo en Vulkan')
            if engine == 'npu':
                label = 'NPU + CPU' if loaded < total else 'NPU'
                if args.memory_window:
                    label += ' por bloques'
                accelerator = 'Hexagon HTP0'
            elif engine == 'gpu':
                label, accelerator = 'GPU + CPU', 'Vulkan · Adreno 740'
            else:
                label, accelerator = 'CPU', 'Kryo · 8 núcleos'
            ready = {'event': 'ready', 'url': url, 'engine': engine, 'label': label,
                     'accelerator': accelerator, 'layers': loaded, 'total_layers': total,
                     'model': str(model), 'mmproj': str(args.mmproj) if args.mmproj else None}
            print('READY ' + json.dumps(ready, ensure_ascii=False), flush=True)
            print(f'Chat {label} listo: {url}' +
                  (f' ({loaded}/{total} capas aceleradas)' if total else ''), flush=True)
            if args.open_browser:
                subprocess.Popen(['xdg-open', url], stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
            return process.wait()
    finally:
        stop_process(process)
        if inhibitor is not None:
            os.close(inhibitor)
        if lock_file is not None:
            fcntl.flock(lock_file, fcntl.LOCK_UN)
            lock_file.close()


def run_speech(args, log_path):
    root = Path('/opt/gts9u-npu-whisper')
    audio = args.audio.resolve(strict=True)
    env = dict(os.environ, LD_LIBRARY_PATH=f'{root}/lib:{BIONIC}/lib',
               LD_PRELOAD=f'{BIONIC}/lib/liblog.so:{BIONIC}/lib/libm.so',
               ADSP_LIBRARY_PATH=f'{root}/dsp;{BIONIC}/dsp',
               DSP_LIBRARY_PATH=f'{root}/dsp;{BIONIC}/dsp')
    command = [str(BIONIC / 'bin/linker64'), str(root / 'bin/whisper-cli'),
               '-m', str(root / 'models/ggml-tiny.bin'), '-f', str(audio), '-l', 'auto', '-t', '4']
    process = None
    inhibitor = None
    lock = acquire_npu_session()
    with lock, log_path.open('w') as log:
        try:
            inhibitor = inhibit_sleep()
            process = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT,
                                       start_new_session=True)
            result = process.wait(timeout=300)
            if result:
                raise RuntimeError('Error de transcripción. Consulta ' + str(log_path))
            output = log_path.read_text(errors='replace')
            if 'using HTP0 backend' not in output:
                raise RuntimeError('La transcripción no utilizó Hexagon')
            segments = re.findall(r'^\[\d\d:.*?\]\s*(.+)$', output, re.M)
            print(json.dumps({'backend': 'Hexagon HTP0', 'text': ' '.join(segments),
                              'log': str(log_path)}, ensure_ascii=False))
        finally:
            stop_process(process)
            if inhibitor is not None:
                os.close(inhibitor)
            fcntl.flock(lock, fcntl.LOCK_UN)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    chat = sub.add_parser('chat')
    chat.add_argument('--open-browser', action='store_true')
    chat.add_argument('--model', type=Path)
    chat.add_argument('--mmproj', type=Path, help='Optional multimodal projector GGUF')
    chat.add_argument('--context', type=int, default=4096)
    chat.add_argument('--port', type=int, default=18080)
    chat.add_argument('--engine', choices=['auto', 'npu', 'gpu', 'cpu'], default='auto')
    chat.add_argument('--npu-layers', type=int, default=999)
    chat.add_argument('--memory-window', action='store_true')
    chat.add_argument('--memory-window-mib', type=int, default=2800)
    chat.add_argument('--threads', type=int, default=6)
    speech = sub.add_parser('transcribe')
    speech.add_argument('audio', type=Path)
    args = parser.parse_args()
    reports = Path.home() / '.local/state/gts9u-ai'
    reports.mkdir(parents=True, exist_ok=True)
    log_path = reports / f'{args.command}-{time.time_ns()}.log'
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    if args.command == 'transcribe':
        run_speech(args, log_path)
        return
    model = (args.model or NPU_ROOT / 'models/Qwen3-1.7B-Q8_0.gguf').resolve(strict=True)
    with model.open('rb') as source:
        if source.read(4) != b'GGUF':
            parser.error('--model must be a GGUF file')
    if not 256 <= args.context <= 32768 or not 1024 <= args.port <= 65535:
        parser.error('context or port outside the supported range')
    if not 1 <= args.npu_layers <= 999 or not 1024 <= args.memory_window_mib <= 2800:
        parser.error('NPU layers/window outside the supported range')
    engines = ['npu', 'gpu'] if args.engine == 'auto' else [args.engine]
    last_error = None
    for engine in engines:
        try:
            result = run_chat(args, model, engine, log_path)
            if result:
                raise RuntimeError(f'El motor {engine} terminó con código {result}')
            return
        except RuntimeError as exc:
            last_error = exc
            if args.engine != 'auto' or engine == engines[-1]:
                raise
            print(f'El modelo no pudo arrancar en NPU ({exc}); probando GPU…', flush=True)
    raise last_error


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
