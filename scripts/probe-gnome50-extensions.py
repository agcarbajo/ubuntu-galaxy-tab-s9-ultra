#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Static compatibility gate against the exact Ubuntu GNOME Shell source.

This cannot establish that an extension works in a compositor session. It
checks imports and the private APIs this port currently relies on.
"""
import argparse
import json
import re
from pathlib import Path


REQUIRED_SOURCE = {
    "js/extensions/extension.js": ("export class Extension", "gettext"),
    "js/gdm/util.js": ("export class ShellUserVerifier", "cancel()", "clear()",
                       "this.emit('show-message', message.serviceName, message.text, message.type)"),
    "js/gdm/authPrompt.js": ("this._userVerifier",),
    "js/ui/screenShield.js": ("this._dialog",),
    "js/ui/keyboard.js": ("get keyboardActor()", "maybeHandleEvent(event)",
                          "_a11yApplicationsSettings", "_syncEnabled()"),
    "js/ui/panel.js": ("addExternalIndicator(indicator",),
    "js/ui/quickSettings.js": ("export const QuickToggle", "export const QuickMenuToggle",
                               "export const SystemIndicator"),
    "js/ui/slider.js": ("export const Slider",),
    "js/misc/loginManager.js": ("export function getLoginManager",),
}
RESOURCE = re.compile(r"resource:///org/gnome/shell/([A-Za-z0-9/._-]+\.js)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shell-source", type=Path, required=True)
    args = parser.parse_args()
    source = args.shell_source.resolve()
    repo = Path(__file__).resolve().parents[1]
    extensions = list(repo.glob("packaging/ubuntu-gts9u-*/usr/share/gnome-shell/extensions/*"))
    if len(extensions) != 5:
        raise SystemExit(f"expected five project extensions, found {len(extensions)}")
    for relative, tokens in REQUIRED_SOURCE.items():
        data = (source / relative).read_text()
        for token in tokens:
            if token not in data:
                raise SystemExit(f"GNOME 50 API changed: {relative}: {token}")
    for extension in extensions:
        metadata = json.loads((extension / "metadata.json").read_text())
        if metadata["uuid"] != extension.name or "50" not in metadata["shell-version"]:
            raise SystemExit(f"GNOME 50 metadata mismatch: {extension.name}")
        modules = set()
        for file in extension.glob("*.js"):
            modules.update(RESOURCE.findall(file.read_text()))
        for name in modules:
            if not (source / "js" / name).is_file():
                raise SystemExit(f"GNOME 50 module missing for {extension.name}: {name}")
        print(f"{extension.name}: {len(modules)} Shell modules present; private API markers present")
    print("Static GNOME 50 extension probe passed; a live Shell/GDM test remains required")


if __name__ == "__main__":
    main()
