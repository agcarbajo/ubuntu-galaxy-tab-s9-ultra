# SPDX-License-Identifier: MIT
"""Gettext boundary shared by every Tab Companion UI module."""

import gettext
import os

from .translations import LANGUAGE_INDEX, TRANSLATIONS
from .fingerprint_translations import ES as FINGERPRINT_ES


DOMAIN = "ubuntu-gts9u-companion"
LOCALE_DIR = "/usr/share/locale"
_translation = gettext.translation(DOMAIN, LOCALE_DIR, fallback=True)
_locale = (
    os.environ.get("LANGUAGE")
    or os.environ.get("LC_ALL")
    or os.environ.get("LC_MESSAGES")
    or os.environ.get("LANG")
    or "en"
).split(":", 1)[0]
_language = _locale.split("_", 1)[0].split("-", 1)[0].lower()


def _(message):
    translated = _translation.gettext(message)
    if translated != message:
        return translated
    if _language == "es" and message in FINGERPRINT_ES:
        return FINGERPRINT_ES[message]
    index = LANGUAGE_INDEX.get(_language)
    values = TRANSLATIONS.get(message)
    return values[index] if index is not None and values is not None else message
ngettext = _translation.ngettext


def N_(message):
    """Mark a deferred string for extraction without translating it yet."""
    return message
