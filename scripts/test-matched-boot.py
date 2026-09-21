import gzip
from pathlib import Path
import runpy
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'packaging/ubuntu-gts9u-companion/usr/lib/tab-companion'))
module = runpy.run_path(str(ROOT / 'scripts/diagnostics/apply-matched-boot.py'))


class BootTests(unittest.TestCase):
    def test_saved_boot_replacement_is_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / 'candidate', Path(tmp) / 'saved'
            source.write_bytes(b'new boot')
            target.write_bytes(b'previous boot')
            module['atomic_copy'](source, target)
            self.assertEqual(target.read_bytes(), source.read_bytes())
            self.assertEqual(len(list(Path(tmp).iterdir())), 2)

    def test_copy_failure_preserves_saved_boot_and_allows_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / 'candidate', Path(tmp) / 'saved'
            source.write_bytes(b'new boot')
            target.write_bytes(b'previous boot')
            with patch.object(module['shutil'], 'copyfileobj', side_effect=OSError('injected')):
                with self.assertRaises(OSError):
                    module['atomic_copy'](source, target)
            self.assertEqual(target.read_bytes(), b'previous boot')
            self.assertEqual(len(list(Path(tmp).iterdir())), 2)
            module['atomic_copy'](source, target)
            self.assertEqual(target.read_bytes(), b'new boot')

    def test_dtb_is_separated_from_gzip_without_modification(self):
        header = bytearray(4096)
        payload = gzip.compress(b'kernel fixture') + b'dtb fixture'
        struct.pack_into('<I', header, 8, len(payload))
        self.assertEqual(module['dtb'](bytes(header) + payload), b'dtb fixture')

    def test_incomplete_gzip_is_rejected(self):
        header = bytearray(4096)
        payload = gzip.compress(b'kernel fixture')[:-1]
        struct.pack_into('<I', header, 8, len(payload))
        with self.assertRaises(RuntimeError):
            module['dtb'](bytes(header) + payload)


if __name__ == '__main__':
    unittest.main()
