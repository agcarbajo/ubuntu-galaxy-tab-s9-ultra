#!/usr/bin/env python3
"""Run supported ONNX models on the SM-X910 NPU."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import dbus

ROOT = Path('/opt/gts9u-npu-onnx')
BIONIC = Path('/opt/gts9u-npu-bionic')
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
    """Reserve one client slot and refresh CDSP before its 48-process limit."""
    counter = open(COUNT_LOCK, 'r+')
    fcntl.flock(counter, fcntl.LOCK_EX)
    users = open(USERS_LOCK, 'r+')
    try:
        counter.seek(0)
        text = counter.read().strip()
        count = int(text) if text.isdigit() else 0
        active = subprocess.run(['systemctl', 'is-active', '--quiet', SERVICE]).returncode == 0
        if not active or count >= CLIENT_LIMIT:
            fcntl.flock(users, fcntl.LOCK_EX)
            if active:
                subprocess.run(['systemctl', 'stop', SERVICE], check=True, timeout=45)
            subprocess.run(['systemctl', 'start', SERVICE], check=True, timeout=120)
            count = 0
            fcntl.flock(users, fcntl.LOCK_SH)
        else:
            fcntl.flock(users, fcntl.LOCK_SH)
            subprocess.run(['systemctl', 'start', SERVICE], check=True, timeout=120)
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


def execute(model, input_file, output_file, runs, report, timeout, dimensions=(), profile=True):
    env = dict(os.environ, LD_LIBRARY_PATH=f'{ROOT}/lib:{BIONIC}/lib',
               ADSP_LIBRARY_PATH=f'{ROOT}/dsp;{BIONIC}/dsp',
               DSP_LIBRARY_PATH=f'{ROOT}/dsp;{BIONIC}/dsp')
    env.pop('LD_PRELOAD', None)
    env.pop('GTS9U_WAIT_DEVICE', None)
    if not profile:
        env['GTS9U_ONNX_DISABLE_PROFILE'] = '1'
    lock = acquire_npu_session()
    try:
        try:
            inhibitor = inhibit_sleep()
            process = subprocess.Popen(
                [str(BIONIC / 'bin/linker64'), str(ROOT / 'bin/onnx-run'),
                 str(model), str(input_file), str(output_file), str(runs),
                 *dimensions],
                cwd=report, env=env, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True)
            try:
                output, _ = process.communicate(timeout=timeout)
            except (subprocess.TimeoutExpired, KeyboardInterrupt):
                process.kill()
                try:
                    output, _ = process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    # A stuck DSP call may only release its Linux file after a
                    # remoteproc stop. Recover before waiting indefinitely.
                    subprocess.run(['systemctl', 'stop', SERVICE], check=True, timeout=45)
                    output, _ = process.communicate(timeout=15)
                (report / 'runtime.log').write_text(output)
                raise RuntimeError('Model execution was interrupted or exceeded its deadline')
            result = subprocess.CompletedProcess(process.args, process.returncode, output)
            (report / 'runtime.log').write_text(result.stdout)
            if result.returncode or 'PASS ONNX HTP inference; CPU fallback disabled' not in result.stdout:
                raise RuntimeError('NPU model execution failed:\n' + result.stdout[-6000:])
            if profile:
                profiles = list(report.glob('ort-profile*.json'))
                if len(profiles) != 1:
                    raise RuntimeError('Expected one ONNX execution profile')
                nodes = [e for e in json.loads(profiles[0].read_text()) if e.get('cat') == 'Node']
                if not nodes or any(e.get('args', {}).get('provider') != 'QNN' for e in nodes):
                    raise RuntimeError('Execution profile does not exclusively use QNN')
            match = re.search(r'RUNS=(\d+) TOTAL_SECONDS=([\d.]+)', result.stdout)
            if not match:
                raise RuntimeError('Missing inference timing')
            counts = re.search(r'INPUTS=(\d+) OUTPUTS=(\d+)', result.stdout)
            return {'backend': 'QNN HTP', 'cpu_fallback': False,
                    'runs': int(match[1]), 'mean_inference_ms': float(match[2]) * 1000 / int(match[1]),
                    'profiled': profile, 'inputs': int(counts[1]) if counts else 1,
                    'outputs': int(counts[2]) if counts else 1}
        finally:
            if 'inhibitor' in locals():
                os.close(inhibitor)
            fcntl.flock(lock, fcntl.LOCK_UN)
    finally:
        lock.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    classify = sub.add_parser('classify', help='Classify an image with pretrained MobileNetV2')
    classify.add_argument('image', type=Path)
    run = sub.add_parser('run', help='Run a compatible single-input/output float32 ONNX model')
    run.add_argument('model', type=Path)
    run.add_argument('input', type=Path, help='Raw float32 input in the model tensor order')
    run.add_argument('output', type=Path, help='Raw float32 output file')
    graph = sub.add_parser('run-graph', help='Run a multi-tensor ONNX graph using indexed raw files')
    graph.add_argument('model', type=Path)
    graph.add_argument('inputs', type=Path, help='Directory containing INDEX-NAME.raw input tensors')
    graph.add_argument('outputs', type=Path, help='New directory for INDEX-NAME.raw output tensors')
    graph.add_argument('--dim', action='append', default=[], metavar='SYMBOL=VALUE',
                       help='Fix a symbolic ONNX dimension before QNN graph compilation')
    for cmd in (classify, run, graph):
        cmd.add_argument('--runs', type=int, default=1)
        cmd.add_argument('--timeout', type=float, default=300, help='Model loading/execution deadline in seconds')
        cmd.add_argument('--no-profile', action='store_true', help='Disable large ORT/QNN traces for long soak runs')
        cmd.add_argument('--report', type=Path, help='New directory for execution evidence')
    args = parser.parse_args()
    if not 1 <= args.runs <= 100000:
        parser.error('--runs must be between 1 and 100000')
    if not .01 <= args.timeout <= 3600:
        parser.error('--timeout must be between 0.01 and 3600 seconds')
    with tempfile.TemporaryDirectory(prefix='gts9u-ai-') as temporary:
        temporary = Path(temporary)
        if args.report:
            report = args.report.resolve()
            report.mkdir(parents=True, exist_ok=False)
        else:
            report = temporary
        if args.command == 'classify':
            import numpy as np
            from PIL import Image, ImageOps
            with Image.open(args.image) as original:
                im = ImageOps.exif_transpose(original).convert('RGB')
            width, height = im.size
            im = im.resize((round(width * 256 / min(width, height)),
                            round(height * 256 / min(width, height))), Image.Resampling.BILINEAR)
            width, height = im.size
            im = im.crop(((width - 224) // 2, (height - 224) // 2,
                          (width - 224) // 2 + 224, (height - 224) // 2 + 224))
            x = np.asarray(im, dtype=np.float32) / 255
            x = (x - np.array([.485, .456, .406], dtype=np.float32)) / np.array([.229, .224, .225], dtype=np.float32)
            input_file = temporary / 'input.f32'
            x.transpose(2, 0, 1)[None].copy().tofile(input_file)
            output_file = temporary / 'output.f32'
            info = execute(ROOT / 'models/mobilenetv2-12.onnx', input_file, output_file, args.runs, report, args.timeout, profile=not args.no_profile)
            scores = np.fromfile(output_file, dtype=np.float32)
            labels = (ROOT / 'models/imagenet_classes.txt').read_text().splitlines()
            if len(scores) != len(labels):
                raise RuntimeError('Model output and label counts differ')
            probabilities = np.exp(scores - scores.max())
            probabilities /= probabilities.sum()
            top = np.argsort(scores)[-5:][::-1]
            info['predictions'] = [{'index': int(i), 'label': labels[i],
                                    'probability': float(probabilities[i])} for i in top]
        elif args.command == 'run':
            model, input_file, output_file = args.model.resolve(), args.input.resolve(), args.output.resolve()
            if not model.is_file() or not input_file.is_file():
                raise RuntimeError('Model and input must be existing files')
            if output_file.exists():
                raise RuntimeError('Choose a new output path; existing files are not overwritten')
            info = execute(model, input_file, output_file, args.runs, report, args.timeout, profile=not args.no_profile)
        else:
            model, inputs, outputs = args.model.resolve(), args.inputs.resolve(), args.outputs.resolve()
            if not model.is_file() or not inputs.is_dir():
                raise RuntimeError('Model and input directory must exist')
            if outputs.exists():
                raise RuntimeError('Choose a new output directory; existing paths are not overwritten')
            invalid = [item for item in args.dim if not re.fullmatch(r'[^=\s]+=[1-9]\d*', item)]
            if invalid:
                raise RuntimeError('Invalid --dim; expected SYMBOL=POSITIVE_INTEGER: ' + ', '.join(invalid))
            outputs.mkdir()
            info = execute(model, inputs, outputs, args.runs, report, args.timeout, args.dim, profile=not args.no_profile)
            info['output_files'] = sorted(path.name for path in outputs.iterdir())
        if args.report:
            (report / 'result.json').write_text(json.dumps(info, indent=2) + '\n')
        print(json.dumps(info, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
