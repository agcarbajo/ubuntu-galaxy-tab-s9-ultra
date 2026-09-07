#!/usr/bin/env python3
"""Build a minimal Android DT table image from DTBO payloads."""

import argparse
import struct
from pathlib import Path


DT_TABLE_MAGIC = 0xD7B7AB1E
FDT_MAGIC = 0xD00DFEED
HEADER_SIZE = 32
ENTRY_SIZE = 32


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("dtbo", nargs="+", type=Path)
    args = parser.parse_args()

    payloads = [path.read_bytes() for path in args.dtbo]
    for path, payload in zip(args.dtbo, payloads):
        if len(payload) < 4 or struct.unpack_from(">I", payload)[0] != FDT_MAGIC:
            parser.error(f"{path} is not a flattened device-tree overlay")

    entries_offset = HEADER_SIZE
    data_offset = entries_offset + ENTRY_SIZE * len(payloads)
    entries = []
    data = bytearray()
    for payload in payloads:
        entries.append(struct.pack(">8I", len(payload), data_offset,
                                   0, 0, 0, 0, 0, 0))
        data.extend(payload)
        padding = (-len(payload)) & 3
        data.extend(b"\0" * padding)
        data_offset += len(payload) + padding

    total_size = data_offset
    header = struct.pack(">8I", DT_TABLE_MAGIC, total_size, HEADER_SIZE,
                         ENTRY_SIZE, len(payloads), entries_offset, 4096, 0)
    args.output.write_bytes(header + b"".join(entries) + data)


if __name__ == "__main__":
    main()
