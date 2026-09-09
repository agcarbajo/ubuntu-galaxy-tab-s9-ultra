#!/usr/bin/env python3
"""Pack, never flash, the one-shot diagnostic init_boot with an audited base."""
import argparse
import hashlib
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

p = argparse.ArgumentParser(description=__doc__)
for name in ("baseline", "ramdisk", "output", "avbtool"):
    p.add_argument("--" + name, type=Path, required=True)
a = p.parse_args()
base = a.baseline.read_bytes()
ramdisk = a.ramdisk.read_bytes()
assert hashlib.sha256(base).hexdigest() == "7881d5859f223a2bfdcc6be0fe12edf561b71c02d7c6ab854ab7e14dcf0e1705"
assert base[:8] == b"ANDROID!" and len(base) == 8388608
assert struct.unpack_from("<I", base, 8)[0] == 0
assert struct.unpack_from("<I", base, 40)[0] == 4
assert struct.unpack_from("<I", base, 1580)[0] == 0
# Preserve the device's original legacy LZ4 format. The gzip diagnostic
# failed early boot on hardware; do not silently reproduce that artifact.
if not ramdisk.startswith(b"\x02\x21\x4c\x18"):
    raise ValueError("Expected the hardware-validated legacy LZ4 ramdisk")
archive = subprocess.run(["lz4", "-dc", str(a.ramdisk)], check=True,
                         stdout=subprocess.PIPE).stdout
assert archive.startswith(b"070701") and b"TRAILER!!!" in archive
assert b"exec /gts9u-ramroot-test\n" in archive
assert b"gts9u-ramroot-armed" in archive
assert not a.output.exists()
assert hashlib.sha256(a.avbtool.read_bytes()).hexdigest() == "69783733ce5e198317b02a5567cc356e898c891de872f58a963e9d5c082973c6"


def avb(*args):
    subprocess.run([sys.executable, str(a.avbtool), *args], check=True)


def verify(path):
    with tempfile.TemporaryDirectory(prefix="gts9u-init-verify-") as tmp:
        link = Path(tmp) / "init_boot.img"
        link.symlink_to(path.resolve())
        avb("verify_image", "--image", str(link))


verify(a.baseline)
header = bytearray(base[:4096])
struct.pack_into("<I", header, 12, len(ramdisk))
payload = bytes(header) + ramdisk
payload += bytes(-len(payload) % 4096)
assert len(payload) + 65536 < len(base)
with a.output.open("xb") as f:
    f.write(payload)
avb("add_hash_footer", "--image", str(a.output), "--partition_name", "init_boot",
    "--partition_size", str(len(base)), "--hash_algorithm", "sha256",
    "--salt", hashlib.sha256(ramdisk).hexdigest(), "--algorithm", "NONE")
verify(a.output)
result = a.output.read_bytes()
assert len(result) == len(base)
assert result[:12] == base[:12] and result[16:4096] == base[16:4096]
assert result[4096:4096 + len(ramdisk)] == ramdisk
print("PASS: original header, diagnostic ramdisk, capacity and AVB hash")
print(hashlib.sha256(result).hexdigest(), a.output)
