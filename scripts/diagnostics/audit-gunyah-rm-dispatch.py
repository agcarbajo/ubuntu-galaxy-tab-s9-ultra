#!/usr/bin/env python3
"""Offline dispatcher test on hash-pinned private RM bytes; never a live RPC.

Only the message-dispatch prefix is exercised. Recognized control handlers stop
before executing their body. The known printf routine is stubbed; its return
value is unused on the tested unsupported path. The reply routine is intercepted
to observe its arguments, not executed. This is not a complete RM VM emulator.
The EZI2 image shares the tested ELF layout; changed code elsewhere is not
assumed to have identical behavior.
"""
import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE, UcError
from unicorn.arm64_const import (
    UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3,
    UC_ARM64_REG_X4, UC_ARM64_REG_X5, UC_ARM64_REG_X6,
    UC_ARM64_REG_X30, UC_ARM64_REG_SP, UC_ARM64_REG_PC,
)

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('image', type=Path)
parser.add_argument('--output', type=Path, help='Create a new private JSON report; refuse overwrite')
args = parser.parse_args()
data = args.image.read_bytes()
digest = hashlib.sha256(data).hexdigest()
if digest not in {
    '6249c495ff8c63f45450496c36dfba34e664b49cf5447a5168a600591ddb824c',
    'dc03857f02055531c221476fa68e6e76006797c20b8e884a1ebd01cee3043b52',
    '83673420c2d7dafe2abb960563b7b13ad6c863bdfef28f35d8f36a1d645c6644',
}:
    raise SystemExit('Unrecognized private firmware; no emulation performed')
rm = data[0x1145c0:]
if rm[:6] != b'\x7fELF\x02\x01':
    raise SystemExit('Not the expected nested ELF64 LE')
phoff = struct.unpack_from('<Q', rm, 32)[0]
phsize, phnum = struct.unpack_from('<HH', rm, 54)
segments = []
for i in range(phnum):
    typ, flags, off, va, pa, fs, ms, align = struct.unpack_from('<IIQQQQQQ', rm, phoff+i*phsize)
    if typ == 1:
        if va+ms > 0x100000 or off+fs > len(rm):
            raise SystemExit('Unexpected ELF segment bounds')
        segments.append((va, rm[off:off+fs]))

CONTROL_HANDLERS = {0x56000001: 0x39244, 0x56000030: 0x38ac4}
CASES = (
    (0x56000001, 'ALLOC_CONTROL'),
    (0x56000030, 'TIME_BASE_CONTROL'),
    (0x56000031, 'SET_BOOT_CONTEXT'),
    (0x56000032, 'SET_FIRMWARE_MEM'),
    (0x56000033, 'SET_DEMAND_PAGING'),
    (0x56000034, 'SET_ADDRESS_LAYOUT'),
)
reports = []
for message, name in CASES:
    emu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    emu.mem_map(0, 0x100000)
    for va, payload in segments:
        emu.mem_write(va, payload)
    emu.mem_map(0x100000, 0x20000)
    emu.reg_write(UC_ARM64_REG_SP, 0x10f000)
    for reg, value in zip((UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2,
                           UC_ARM64_REG_X3, UC_ARM64_REG_X4, UC_ARM64_REG_X5,
                           UC_ARM64_REG_X6),
                          (3, message, 0x1234, 1, 0x110000, 32, 0x111000)):
        emu.reg_write(reg, value)
    report = {'message': hex(message), 'name': name, 'steps': 0}
    trace = []

    def on_code(uc, address, size, unused):
        report['steps'] += 1
        trace.append(hex(address))
        if address == CONTROL_HANDLERS.get(message):
            report['result'] = 'recognized_handler_not_executed'
            uc.emu_stop()
        elif address == 0x22de8:  # printf only; no firmware or RPC effects.
            report['printf_stub_calls'] = report.get('printf_stub_calls', 0) + 1
            uc.reg_write(UC_ARM64_REG_X0, 0)
            uc.reg_write(UC_ARM64_REG_PC, uc.reg_read(UC_ARM64_REG_X30))
        elif address == 0x3ce5c:  # Observe common response arguments.
            result = uc.reg_read(UC_ARM64_REG_X3) & 0xffffffff
            result = result if result < 0x80000000 else result - 0x100000000
            report.update(result='reply_intercepted', raw_rm_error=result,
                          reply_message=hex(uc.reg_read(UC_ARM64_REG_X1) & 0xffffffff))
            uc.emu_stop()

    emu.hook_add(UC_HOOK_CODE, on_code)
    try:
        # Start just after the PAC prologue. Authentication/return are not part
        # of this dispatcher-prefix test, and no firmware instruction is patched.
        emu.emu_start(0x37888, 0x60000, timeout=1_000_000, count=1000)
    except UcError as exc:
        raise RuntimeError(f'{name}: emulator failed at {emu.reg_read(UC_ARM64_REG_PC):#x}') from exc
    if message in CONTROL_HANDLERS:
        passed = report.get('result') == 'recognized_handler_not_executed'
    else:
        passed = (report.get('result') == 'reply_intercepted'
                  and report.get('raw_rm_error') == -1
                  and report.get('reply_message') == hex(message))
    report['pass'] = passed
    report['trace'] = trace
    reports.append(report)
    if not passed:
        print(json.dumps(report, indent=2))
        raise SystemExit('Dispatch result differed from hypothesis; investigate')
result = {'private_image_sha256': digest, 'scope': 'offline_dispatch_only',
          'cases': reports, 'all_pass': True}
if args.output:
    import os
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps({**result, 'cases': [{k: v for k, v in r.items() if k != 'trace'}
                                        for r in reports]}, indent=2))
else:
    print(json.dumps(result, indent=2))
