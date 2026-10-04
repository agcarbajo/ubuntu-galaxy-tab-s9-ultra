#!/usr/bin/env python3
"""Stage only hardware firmware from a hash-verified public release fixture."""
import argparse
import json
from pathlib import Path
import shutil
import tarfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    provenance = json.loads((root.parent / 'provenance.json').read_text())
    if provenance.get('version') != '1.3.0' or provenance.get('tablet_data') is not False:
        parser.error('a trusted clean public 1.3.0 fixture is required')
    if args.output.exists():
        parser.error('choose a new firmware staging directory')
    args.output.mkdir(parents=True)
    firmware = root / 'usr/lib/firmware'
    names = {name: 'qcom/' + name for name in
             ('a740_zap.mdt', 'a740_zap.b00', 'a740_zap.b01', 'a740_zap.b02', 'a740_sqe.fw', 'gmu_gen70200.bin')}
    for file in (firmware / 'qcom/sm8550').glob('adsp*'):
        if file.is_file():
            names[file.name] = 'qcom/sm8550/' + file.name
    for name in ('cdspr.jsn', 'Samsung-Galaxy-Tab-S9-Ultra-tplg.bin'):
        names[name] = 'qcom/sm8550/' + name
    for name, original in (('official-amss.bin', 'amss.bin'), ('m3.bin', 'm3.bin'),
                           ('official-board-2.bin', 'board-2.bin'), ('qrd-board.bin', 'board.bin'),
                           ('regdb.bin', 'regdb.bin')):
        names[name] = 'ath12k/WCN7850/hw2.0/' + original
    for name in ('hmtbtfw20.tlv', 'hmtnv20.b21'):
        names[name] = 'qca/' + name
    names['stm32_gts9family.bin'] = 'keyboard_stm/stm32_gts9family.bin'
    for file in firmware.glob('cs35l45-*'):
        if file.is_file():
            names[file.name] = file.name
    for name, relative in names.items():
        shutil.copyfile(firmware / relative, args.output / name)
    tree = root / 'usr/share/qcom/sm8550/Samsung/gts9uwifi'
    with tarfile.open(args.output / 'sensor-hexagonfs.tar.gz', 'w:gz') as archive:
        for file in sorted(tree.rglob('*')):
            relative = file.relative_to(tree)
            if relative.parts[0] == 'cdsp':
                continue
            archive.add(file, arcname='sensor-hexagonfs/' + relative.as_posix(), recursive=False)
    print('Staged', len(names), 'public-release firmware files and the sensor tree')


if __name__ == '__main__':
    main()
