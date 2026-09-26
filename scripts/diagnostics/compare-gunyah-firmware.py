#!/usr/bin/env python3
"""Compare loadable ARM64 ELF content in two private hypvm images.

Print hashes and layout only. A changed loadable segment requires a new RM
analysis; matching filenames or firmware build numbers prove nothing.
"""

import argparse
import hashlib
import struct
from pathlib import Path


ELF_MAGIC = b"\x7fELF"
ELF_HEADER_SIZE = 64
PROGRAM_HEADER_SIZE = 56
PT_LOAD = 1
PF_X = 1
EM_AARCH64 = 183


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def embedded_elfs(image):
    """Return valid loadable AArch64 ELF images and their segment metadata."""
    found = []
    cursor = 0
    while True:
        origin = image.find(ELF_MAGIC, cursor)
        if origin < 0:
            break
        cursor = origin + len(ELF_MAGIC)
        data = memoryview(image)[origin:]
        if len(data) < ELF_HEADER_SIZE or bytes(data[:6]) != b"\x7fELF\x02\x01":
            continue
        if struct.unpack_from("<H", data, 18)[0] != EM_AARCH64:
            continue
        header_size = struct.unpack_from("<H", data, 52)[0]
        phoff = struct.unpack_from("<Q", data, 32)[0]
        phentsize, phnum = struct.unpack_from("<HH", data, 54)
        if header_size < ELF_HEADER_SIZE or phentsize < PROGRAM_HEADER_SIZE:
            continue
        if not 1 <= phnum <= 128 or phoff + phentsize * phnum > len(data):
            continue
        segments = []
        valid = True
        for index in range(phnum):
            typ, flags, offset, vaddr, _, filesz, _, _ = struct.unpack_from(
                "<IIQQQQQQ", data, phoff + index * phentsize
            )
            if typ != PT_LOAD:
                continue
            if filesz == 0 or offset + filesz > len(data):
                valid = False
                break
            payload = data[offset : offset + filesz]
            segments.append((index, flags, offset, vaddr, filesz, sha256(payload)))
        if valid and segments and any(flags & PF_X for _, flags, *_ in segments):
            found.append((origin, segments))
    return found


def summarize(label, path):
    image = path.read_bytes()
    elfs = embedded_elfs(image)
    print(f"{label}: size={len(image)} sha256={sha256(image)}")
    for origin, segments in elfs:
        print(f"  ARM64 ELF at {origin:#x}, loadable segments={len(segments)}")
        for index, flags, offset, vaddr, filesz, digest in segments:
            print(
                f"    PT_LOAD[{index}] flags={flags:#x} file={offset:#x} "
                f"vaddr={vaddr:#x} size={filesz:#x} sha256={digest}"
            )
    return elfs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()
    reference = summarize("reference", args.reference)
    candidate = summarize("candidate", args.candidate)
    if len(reference) != len(candidate) or not reference:
        print("RESULT: ELF inventory changed; inspect the candidate manually")
        return
    changed = False
    for index, ((_, old_segments), (_, new_segments)) in enumerate(
        zip(reference, candidate)
    ):
        old = [(flags, vaddr, size, digest) for _, flags, _, vaddr, size, digest in old_segments]
        new = [(flags, vaddr, size, digest) for _, flags, _, vaddr, size, digest in new_segments]
        if old != new:
            print(f"RESULT: ELF {index} loadable content or layout changed")
            changed = True
        else:
            print(f"RESULT: ELF {index} loadable content and layout match")
    if changed:
        print("The previous RM dispatch result cannot be transferred to this image.")
        return
    print("RESULT: every discovered ARM64 ELF PT_LOAD segment matches")
    print("This compares bytes on disk; it does not prove a guest can execute.")


if __name__ == "__main__":
    main()
