#!/usr/bin/env python3
"""Decode the temporary PM trace from a Samsung reserved-memory snapshot."""

import argparse
import struct
from pathlib import Path

MAGIC = 0x4D505447
RECORD_SIZE = 64
LEGACY_LOGM_SIZE = 0x200000
DEBUG_POOL_SIZE = 0xFF000
ACTION_NAMES = (
    "module_loaded", "module_unloaded", "CPU_OFF", "CPU_ON",
    "syscore_suspend", "syscore_resume", "console_resume_all",
    "dpm_complete", "dpm_prepare", "dpm_resume", "dpm_resume_early",
    "dpm_resume_noirq", "dpm_suspend", "dpm_suspend_late",
    "dpm_suspend_noirq", "freeze_processes", "machine_suspend",
    "suspend_enter", "sync_filesystems", "thaw_processes",
    "ath12k_pci_pm_resume_early", "ath12k_core_resume_early",
    "ath12k_pci_power_up", "ath12k_pci_sw_reset", "ath12k_mhi_start",
    "ath12k_mhi_set_state", "mhi_prepare_for_power_up",
    "mhi_sync_power_up",
)


def hash_action(action: str) -> int:
    value = 2166136261
    for byte in action.encode("ascii"):
        value = ((value ^ byte) * 16777619) & 0xFFFFFFFF
    return value


ACTION_HASHES = {hash_action(name): name for name in ACTION_NAMES}
ACTION_HASHES.update({hash_action(name) & 0x7FFFFFFF: name
                      for name in ACTION_NAMES})


def recover_redundant_ring(page: bytes, records: int, copies: int,
                           record_size: int) -> tuple[bytes, int]:
    ring_size = 16 + records * record_size
    recovered = bytearray(ring_size)
    errors = 0
    for index in range(ring_size):
        sample_bytes = [page[copy * ring_size + index]
                        for copy in range(copies)]
        recovered[index] = sum(
            1 << bit for bit in range(8)
            if sum((byte >> bit) & 1 for byte in sample_bytes) > copies // 2
        )
        errors += sum((byte ^ recovered[index]).bit_count()
                      for byte in sample_bytes)
    return bytes(recovered), errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshot", type=Path)
    args = parser.parse_args()
    data = args.snapshot.read_bytes()
    if len(data) == LEGACY_LOGM_SIZE:
        offset, expected_version, expected_count = 0x180000, 1, 128
    elif len(data) == DEBUG_POOL_SIZE:
        data = data[-4096:]
        offset, expected_version, expected_count = 0, 2, 48
    elif len(data) == 4096:
        offset, expected_version, expected_count = 0, 2, 48
    else:
        parser.error("unexpected reserved-memory snapshot size")
    if len(data) == 4096:
        recovered, errors = recover_redundant_ring(data, 11, 20, 16)
        recovered_version = struct.unpack_from("<4I", recovered)[1]
        if struct.unpack_from("<I", recovered)[0] == MAGIC and recovered_version in (4, 5, 6):
            data = recovered
            offset, expected_version, expected_count = 0, recovered_version, 11
            print(f"recovered_bit_errors={errors}")
        else:
            recovered, errors = recover_redundant_ring(data, 10, 5, 64)
            if struct.unpack_from("<4I", recovered)[:2] == (MAGIC, 3):
                data = recovered
                offset, expected_version, expected_count = 0, 3, 10
                print(f"recovered_bit_errors={errors}")
    magic, version, last, count = struct.unpack_from("<4I", data, offset)
    if (magic, version, count) != (MAGIC, expected_version, expected_count):
        parser.error("no matching PM trace at the expected offset")
    print(f"last_sequence={last}")
    if version in (5, 6):
        rows = []
        for slot in range(count):
            sequence, value, action_hash, active = struct.unpack_from(
                "<IiIB3x", data, 16 + slot * 16
            )
            if not sequence:
                continue
            if slot:
                if action_hash & 0x80000000:
                    action = f"device_hash=0x{action_hash & 0x7FFFFFFF:08x}"
                else:
                    action = ACTION_HASHES.get(action_hash,
                                               f"hash=0x{action_hash:08x}")
                state = "ACTIVE" if active else "done"
            else:
                action = ACTION_HASHES.get(action_hash,
                                           f"hash=0x{action_hash:08x}")
                state = "begin" if active else "end"
            rows.append((sequence, slot, action, value, state))
        for sequence, slot, action, value, state in sorted(rows):
            print(f"{sequence:5d} slot={slot:2d} {action} value={value} {state}")
        return
    entries = []
    for slot in range(count):
        entry_size = 16 if version == 4 else RECORD_SIZE
        entry_offset = offset + 16 + slot * entry_size
        if version == 4:
            sequence, value, action_hash, start = struct.unpack_from(
                "<IiIB3x", data, entry_offset
            )
            if action_hash & 0x80000000 and action_hash not in ACTION_HASHES:
                action = f"device_hash=0x{action_hash & 0x7FFFFFFF:08x}"
            else:
                action = ACTION_HASHES.get(action_hash,
                                           f"hash=0x{action_hash:08x}")
            time_ns = None
        else:
            time_ns, sequence, value, start, action = struct.unpack_from(
                "<QIiB3x40s", data, entry_offset
            )
            action = action.split(b"\0", 1)[0].decode("ascii", "replace")
        if not sequence or sequence > last or sequence <= last - count:
            continue
        entries.append((sequence, time_ns, value, start, action))
    for sequence, time_ns, value, start, action in sorted(entries):
        timestamp = f"{time_ns / 1e9:12.6f}" if time_ns is not None else ""
        print(f"{sequence:5d} {timestamp} {action} value={value} "
              f"{'begin' if start else 'end'}")


if __name__ == "__main__":
    main()
