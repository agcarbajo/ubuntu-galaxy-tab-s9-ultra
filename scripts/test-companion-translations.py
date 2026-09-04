#!/usr/bin/env python3
"""Check new UI catalogues, interpolation, markup and language selection."""
import ast
from collections import Counter
import gettext
import importlib
import os
from pathlib import Path
import string
import sys
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "packaging/ubuntu-gts9u-companion/usr/lib/tab-companion/tab_companion"
if len(sys.argv) > 1:
    SOURCE = Path(sys.argv.pop(1))
sys.path.insert(0, str(SOURCE.parent))
from tab_companion import i18n
from tab_companion.fingerprint_translations import ES as FP_ES
from tab_companion.update_translations import ES as UP_ES
from tab_companion.fingerprint_languages import TRANSLATIONS as FP
from tab_companion.update_languages import TRANSLATIONS as UP
from tab_companion.keyboard_translations import TRANSLATIONS as KB


def fields(text):
    return Counter((name, spec, conversion) for _, name, spec, conversion
                   in string.Formatter().parse(text) if name is not None)


class TranslationTests(unittest.TestCase):
    def test_keyboard_diagnostics_translations(self):
        for message, values in KB.items():
            self.assertEqual(len(values), 5)
            for value in values:
                self.assertTrue(value.strip())
                self.assertEqual(fields(message), fields(value))

    def test_complete_catalogues_and_formatting(self):
        for spanish, other in ((FP_ES, FP), (UP_ES, UP)):
            self.assertEqual(set(spanish), set(other))
            for message, values in other.items():
                self.assertEqual(len(values), 4, message)
                for value in (spanish[message], *values):
                    self.assertTrue(value.strip(), message)
                    self.assertEqual(fields(message), fields(value), message)
                    self.assertNotIn("\ufffd", value)
                    self.assertNotIn("\u00c3", value)
                    if '<a href=' in message:
                        original = ET.fromstring("<root>" + message + "</root>")
                        translated = ET.fromstring("<root>" + value + "</root>")
                        self.assertEqual([(e.tag, e.attrib) for e in original.iter()],
                                         [(e.tag, e.attrib) for e in translated.iter()])

    def test_all_languages_reach_their_catalogue(self):
        # Keep the user's locale and any system gettext installation out of the test.
        for lang in ("en", "es", "fr", "de", "it", "pt"):
            with patch.dict(os.environ, {"LANGUAGE": lang}), patch.object(
                    gettext, "translation", return_value=gettext.NullTranslations()):
                importlib.reload(i18n)
                for message in set(FP) | set(UP):
                    if lang == "en":
                        expected = message
                    elif lang == "es":
                        expected = FP_ES.get(message, UP_ES.get(message))
                    else:
                        expected = (FP.get(message) or UP[message])[
                            ("fr", "de", "it", "pt").index(lang)]
                    self.assertEqual(i18n._(message), expected, (lang, message))

    def test_new_pages_have_catalogue_entries(self):
        known = set(i18n.TRANSLATIONS) | set(FP_ES) | set(UP_ES)
        def strings(node):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                return [node.value]
            if isinstance(node, ast.IfExp):
                return strings(node.body) + strings(node.orelse)
            return []
        for name in ("update_page.py", "fingerprint_page.py", "keyboard_diagnostics_ui.py"):
            tree = ast.parse((SOURCE / name).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                fn = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
                args = node.args[:1] if fn in ("_", "N_") else node.args[:2] if fn == "_hero" else []
                for arg in args:
                    for value in strings(arg):
                        self.assertIn(value, known, (name, value))


if __name__ == "__main__":
    unittest.main()
