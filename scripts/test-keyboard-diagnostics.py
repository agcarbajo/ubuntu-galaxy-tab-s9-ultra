#!/usr/bin/env python3
"""Run in a GTK session; does not collect logs or operate hardware."""
import sys,json
from pathlib import Path
source=Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).resolve().parents[1]/"packaging/ubuntu-gts9u-companion/usr/lib/tab-companion"
sys.path.insert(0,str(source))
from tab_companion import keyboard_diagnostics as k
from unittest.mock import patch
import gi
gi.require_version("Adw","1")
from gi.repository import Adw, Gio, Gtk
import tempfile
from tab_companion import keyboard_diagnostics_ui as ui
Adw.init()
a=Adw.AboutWindow(application_name="Diagnostics test",debug_info="Test")
ui.add_to_about(a)
rows=[]
def walk(w):
 if isinstance(w,Adw.ActionRow) and w.get_title()==ui._("Save keyboard cover logs…"): rows.append(w)
 child=w.get_first_child()
 while child: walk(child);child=child.get_next_sibling()
walk(a)
assert len(rows)==1, len(rows)
parent=rows[0].get_parent()
while parent and not isinstance(parent,Adw.NavigationPage): parent=parent.get_parent()
assert parent is not None and parent.get_tag()=="troubleshooting"
assert not a.get_support_url()
with patch.object(ui,"confirm") as confirm:
 rows[0].emit("activated")
 confirm.assert_called_once_with(a)
a.close()
assert k.safe_diagnostics("attached=1 last_key=0x8030 key_events=3")=="attached=1 last_key=[omitted] key_events=3"
assert "0x8030" not in k.filtered_log({"output":"pogo: invalid key event 0x8030\npogo: event read failed: -5"})["output"]
with tempfile.TemporaryDirectory() as tmp, patch.object(ui.GLib,"get_user_special_dir",return_value=tmp), patch.object(ui,"message"):
 ui.save(a,'{"test":"UTF-8: ñ é ü"}\n')
 paths=list(Path(tmp).rglob("*.json"))
 assert len(paths)==1
 assert json.loads(paths[0].read_text(encoding="utf-8"))["test"]=="UTF-8: ñ é ü"
 assert paths[0].stat().st_mode & 0o077 == 0
 # A missing/unwritable Documents destination must not discard the report.
 blocked=Path(tmp)/"not-a-directory";blocked.write_text("occupied")
 with patch.object(ui.GLib,"get_user_special_dir",return_value=str(blocked)), patch.object(ui.Path,"home",return_value=Path(tmp)):
  fallback=ui.save_report("{}")
  assert ".local/state/tab-companion/diagnostics" in str(fallback)
print("PASS Troubleshooting action, private UTF-8 save, invalid-folder fallback, historical key filtering")
