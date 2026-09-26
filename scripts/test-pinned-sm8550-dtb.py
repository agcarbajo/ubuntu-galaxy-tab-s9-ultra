#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Guard the small source transform that retains the physically booted DTB."""
import importlib.util
import tempfile
import unittest
from pathlib import Path


spec = importlib.util.spec_from_file_location(
    "pin_map", Path(__file__).with_name("pin-sm8550-pcie-iommu-map.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PcieMapTest(unittest.TestCase):
    def test_transform_and_repeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sm8550.dtsi"
            path.write_text("\n".join(
                f"&apps_smmu 0x{stream} 0x0 0x1>"
                for stream in ("1400", "1401", "1480", "1481")))
            self.assertIn("restored", module.pin(path))
            self.assertNotIn("0x0 0x1>", path.read_text())
            self.assertIn("already present", module.pin(path))

    def test_rejects_partial_transition(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sm8550.dtsi"
            path.write_text("\n".join(
                f"&apps_smmu 0x{stream} {'0x0 ' if stream == '1400' else ''}0x1>"
                for stream in ("1400", "1401", "1480", "1481")))
            before = path.read_text()
            with self.assertRaises(ValueError):
                module.pin(path)
            self.assertEqual(path.read_text(), before)


if __name__ == "__main__":
    unittest.main()
