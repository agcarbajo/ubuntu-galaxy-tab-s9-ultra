#!/usr/bin/env python3
"""Check Android UI resources in every supported language."""
from collections import Counter
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET
ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "android/bootswitcher/app/src/main/res"
NAMES = {"app_name", "tile_label", "storage_android", "storage_linux"}

def catalogue(path):
    elements = list(ET.parse(path).getroot())
    names = [e.attrib["name"] for e in elements]
    if len(names) != len(set(names)):
        raise AssertionError("Duplicate resource name: " + str(path))
    return {e.attrib["name"]: "".join(e.itertext()) for e in elements}

def formats(value):
    return Counter(re.findall(r"%(?:[0-9]+\$)?[sdf]", value))

class Translations(unittest.TestCase):
    def test_all_supported_languages(self):
        source = catalogue(RES / "values/strings.xml")
        for lang in ("es", "fr", "de", "it", "pt"):
            translated = catalogue(RES / ("values-" + lang) / "strings.xml")
            self.assertEqual(set(source) - NAMES, set(translated) - NAMES, lang)
            for key, value in translated.items():
                self.assertTrue(value.strip(), (lang, key))
                self.assertNotIn("\ufffd", value)
                self.assertEqual(formats(source[key]), formats(value), (lang, key))
                self.assertEqual(re.findall(r"https?://[^\s<]+", source[key]),
                                 re.findall(r"https?://[^\s<]+", value), (lang, key))

if __name__ == "__main__":
    unittest.main()
