#!/usr/bin/env python3
"""Package verified NPU inputs and freshly signed modules for installs/updates."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

REPO = Path(__file__).resolve().parents[1]
MODULES = ('gts9u_cdsp', 'gts9u_dsp_stats', 'system_heap',
           'gts9u_fastrpc_prepared', 'gts9u_cdsp_intents_probe')


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('runtime', 'firmware', 'session', 'kernel-build', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    a = parser.parse_args()
    version = (REPO / 'VERSION').read_text().strip()
    expected = json.loads((REPO / 'configs/npu/release-runtime.json').read_text())
    for name, checksum in expected['files'].items():
        if not name.startswith(('opt/gts9u-npu/', 'opt/gts9u-npu-bionic/')) or '/models/' in name:
            raise SystemExit('Input outside NPU support runtime: ' + name)
        path = (a.runtime / name).resolve()
        if not path.is_relative_to(a.runtime.resolve()) or digest(path) != checksum:
            raise SystemExit('NPU runtime input mismatch: ' + name)
    firmware_files = {}
    for line in (REPO / 'configs/npu/stock-cdsp.sha256').read_text().splitlines():
        checksum, name = line.split()
        if name.startswith('cdsp/'):
            target = 'usr/lib/firmware/qcom/sm8550/' + name.removeprefix('cdsp/')
        else:
            target = 'usr/share/qcom/sm8550/Samsung/gts9uwifi/cdsp/' + name.removeprefix('dsp/cdsp/')
        if digest(a.firmware / target) != checksum:
            raise SystemExit('CDSP firmware mismatch: ' + name)
        firmware_files[target] = checksum
    release = (a.kernel_build / 'include/config/kernel.release').read_text().strip()
    serial = subprocess.check_output(['openssl', 'x509', '-inform', 'DER', '-in',
        str(a.kernel_build / 'certs/signing_key.x509'), '-noout', '-serial'], text=True).strip().split('=')[1].upper()
    for name in MODULES:
        module = a.session / 'modules' / (name + '.ko')
        def field(key):
            return subprocess.check_output(['modinfo', '-F', key, str(module)], text=True).strip()
        if field('vermagic').split()[0] != release or field('sig_key').replace(':', '').upper() != serial:
            raise SystemExit('NPU module does not match release kernel: ' + name)
    a.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='npu-package-') as tmp:
        root = Path(tmp)
        def copy(source, target, mode=0o644):
            dest = root / target
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, dest)
            dest.chmod(mode)
        # Only hashed inputs enter the package, never logs or personal models.
        for name in expected['files']:
            copy(a.runtime / name, name, 0o755 if '/bin/' in name else 0o644)
        for name in firmware_files:
            # Existing releases already own this map in ubuntu-gts9u-hardware.
            # Keep that ownership so updates never need --force-overwrite.
            if name != 'usr/lib/firmware/qcom/sm8550/cdspr.jsn':
                copy(a.firmware / name, name)
        for name in MODULES:
            copy(a.session / 'modules' / (name + '.ko'), 'opt/gts9u-npu-session/modules/' + name + '.ko')
        for name in ('npu-bootstrap-traffic', 'npu-power-keeper'):
            copy(a.session / 'bin' / name, 'opt/gts9u-npu-session/bin/' + name, 0o755)
        copy(REPO / 'scripts/run-npu-session.py', 'opt/gts9u-npu-session/bin/run-npu-session.py', 0o755)
        for source, dest in (
            ('check-npu.sh', 'usr/sbin/gts9u-npu-check'),
            ('validate-npu.sh', 'usr/bin/gts9u-validate-npu')):
            copy(REPO / 'scripts' / source, dest, 0o755)
        for source, dest in (
            ('gts9u-npu.service', 'etc/systemd/system/gts9u-npu.service'),
            ('70-gts9u-npu.rules', 'etc/udev/rules.d/70-gts9u-npu.rules'),
            ('49-gts9u-npu.rules', 'etc/polkit-1/rules.d/49-gts9u-npu.rules'),
            ('gts9u-npu-tmpfiles.conf', 'etc/tmpfiles.d/gts9u-npu.conf')):
            copy(REPO / 'configs/npu' / source, dest)
        for name in ('gts9u-npu-sleep', 'gts9u-npu-resume'):
            copy(REPO / 'configs/npu' / name, 'usr/lib/systemd/system-sleep/' + name, 0o755)
        control = root / 'DEBIAN'
        control.mkdir()
        (control / 'control').write_text(f'''Package: ubuntu-gts9u-npu
Version: {version}
Architecture: arm64
Maintainer: Ubuntu gts9uwifi port contributors <noreply@example.invalid>
Depends: python3, libgomp1, systemd, kmod, polkitd, util-linux, ubuntu-gts9u-device
Description: Verified SM-X910 NPU hardware support and runtime
 On-demand HTP inference with release-matched signed modules.
 No local AI application or models are included.
''')
        (control / 'conffiles').write_text(''.join('/' + str(f.relative_to(root)) + '\n'
            for f in sorted((root / 'etc').rglob('*')) if f.is_file()))
        (control / 'postinst').write_text('''#!/bin/sh
set -e
if [ -d /run/systemd/system ]; then
 systemctl daemon-reload
 systemd-tmpfiles --create /etc/tmpfiles.d/gts9u-npu.conf
 udevadm control --reload-rules || true
fi
''')
        (control / 'postinst').chmod(0o755)
        evidence = root / 'usr/share/doc/ubuntu-gts9u-npu'
        evidence.mkdir(parents=True)
        (evidence / 'inputs.json').write_text(json.dumps({'runtime': expected,
            'firmware': firmware_files, 'kernel_release': release,
            'module_signing_certificate_serial': serial}, indent=2) + '\n')
        for path in root.rglob('*'):
            os.utime(path, (0, 0), follow_symlinks=False)
        subprocess.run(['dpkg-deb', '--root-owner-group', '--build', str(root),
            str(a.output / f'ubuntu-gts9u-npu_{version}_arm64.deb')], check=True)


if __name__ == '__main__':
    main()
