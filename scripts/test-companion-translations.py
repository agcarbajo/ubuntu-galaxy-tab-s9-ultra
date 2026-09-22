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
import types
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
    def test_core_catalogue_formatting(self):
        for message, values in i18n.TRANSLATIONS.items():
            self.assertEqual(len(values), 5, message)
            for value in values:
                self.assertTrue(value.strip(), message)
                self.assertEqual(fields(message), fields(value), message)
                self.assertNotIn("\ufffd", value)

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
        for name in (p.name for p in SOURCE.glob("*.py")):
            tree = ast.parse((SOURCE / name).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                fn = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
                args = node.args[:1] if fn in ("_", "N_") else node.args[:2] if fn == "_hero" else []
                for arg in args:
                    for value in strings(arg):
                        self.assertIn(value, known, (name, value))


class KeyChooserTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("TAB_COMPANION_GTK_TEST"), "Requires an active GTK session")
    def test_real_gtk_chooser(self):
        import gi
        gi.require_version("Adw", "1")
        from gi.repository import Adw
        Adw.init()
        KeyChooser = importlib.import_module("tab_companion.key_selector").KeyChooser
        selected = []
        chooser = KeyChooser(Adw.Window(), "", selected.append)
        chooser._modifier_buttons[29].set_active(True)
        chooser._screen_key(None, 30)
        chooser._screen_key(None, 21)
        self.assertEqual(chooser.current_label.get_label(), "Ctrl + Y")
        self.assertFalse(chooser._key_buttons[30].get_active())
        self.assertEqual(selected, [])
        chooser._save(None)
        self.assertEqual(selected, ["29+21"])
        chooser = KeyChooser(Adw.Window(), "", selected.append)
        chooser._modifier_buttons[42].set_active(True)
        chooser._save(None)
        self.assertEqual(selected[-1], "42")

    def test_key_selection_waits_for_save_and_accepts_modifiers_only(self):
        gdk = types.SimpleNamespace(**{name: index for index, name in enumerate((
            "KEY_Control_L", "KEY_Control_R", "KEY_Shift_L", "KEY_Shift_R",
            "KEY_Alt_L", "KEY_Meta_L", "KEY_Meta_R", "KEY_Super_L",
            "KEY_Super_R", "KEY_ISO_Level3_Shift"), 1000)})
        gi = types.ModuleType("gi")
        gi.repository = types.SimpleNamespace(Adw=types.SimpleNamespace(Window=object), Gdk=gdk, Gtk=object)
        with patch.dict(sys.modules, {"gi": gi, "gi.repository": gi.repository}):
            from tab_companion import key_selector
            importlib.reload(key_selector)
        chooser = object.__new__(key_selector.KeyChooser)
        chosen = []
        active = {}

        class Button:
            def __init__(self, code):
                self.code = code
                self.value = False

            def get_active(self):
                return self.value

            def set_active(self, value):
                self.value = value
                if self.code in key_selector.MODIFIERS:
                    chooser._modifier_toggled(self, self.code)

        chooser._selected = chosen.append
        chooser.close = lambda: chosen.append("closed")
        chooser.current_label = types.SimpleNamespace(set_label=lambda value: active.update(label=value))
        chooser._modifiers = set()
        chooser._key = None
        chooser._modifier_buttons = {code: Button(code) for code in (29, 42)}
        chooser._key_buttons = {code: Button(code) for code in (30, 21)}
        chooser._save(None)
        self.assertEqual(chosen, [])
        chooser._physical_key(None, gdk.KEY_Control_L, 37, 0)
        chooser._physical_key(None, gdk.KEY_Shift_L, 50, 0)
        self.assertEqual(active["label"], "Ctrl + Shift")
        chooser._screen_key(None, 30)
        chooser._physical_key(None, ord("y"), 29, 0)
        self.assertFalse(chooser._key_buttons[30].get_active())
        self.assertTrue(chooser._key_buttons[21].get_active())
        self.assertEqual(chosen, [])
        chooser._physical_key(None, gdk.KEY_Shift_L, 50, 0)
        chooser._save(None)
        self.assertEqual(chosen, ["29+21", "closed"])
        chosen.clear()
        chooser._key = None
        chooser._save(None)
        self.assertEqual(chosen, ["29", "closed"])


if __name__ == "__main__":
    unittest.main()
