#!/usr/bin/env python3
"""User-authorised notification/UI preview; no real update preparation.

Run as the logged-in desktop user with the normal Companion process closed.
The installed application code is untouched. Closing the preview restores
normal discovery; public mock metadata lives only in a temporary cache.
"""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import Mock, patch

if os.geteuid() == 0:
    raise SystemExit("Run this preview as the desktop user, never root")

sys.path.insert(0, "/usr/lib/tab-companion")
from tab_companion import main, update_bundle, update_monitor, update_page
from gi.repository import Adw, Gio, GLib

NOTES = """# Vista previa de la build v1.4.0

**Actualización ficticia para probar Tab Companion.** No es una versión
publicada y no contiene paquetes descargables.

## Kernel y hardware

- Kernel de ejemplo: **7.2.8-gts9u**.
- Ajustes de reconexión del **S Pen** después de activar las funciones remotas.
- Recuperación de Wi-Fi al salir de suspensión.
- Mejor sincronización del indicador de **Bloq Mayús** con el teclado.

## Escritorio y aplicaciones

1. Ubuntu **24.04 LTS** como base de esta demostración.
2. Novedades con *Markdown*, enlaces y bloques de código.
3. Notificación del sistema con acceso directo a **Actualizaciones**.

| Componente | Versión de ejemplo |
| --- | --- |
| Port | 1.4.0 |
| Kernel | 7.2.8-gts9u |
| Ubuntu | 24.04 LTS |

> Los documentos, cuentas y ajustes se conservarían en una actualización
> compatible. En esta prueba no se modifica el sistema.

### Comprobación de ejemplo

```sh
uname -r
# 7.2.8-gts9u (valor ficticio)
```

Consulta el [repositorio del port](https://github.com/agcarbajo/ubuntu-galaxy-tab-s9-ultra).

~~Descarga e instalación reales~~ — desactivadas durante esta vista previa.
"""

INFO = {"tag": "v1.4.0~demo", "name": "VISTA PREVIA — sin paquete real",
        "size": 2300 * 1024**2, "sha256": "0" * 64,
        "supports_updates": True, "notes": NOTES,
        "url": "https://example.invalid/no-real-package.zip"}


def preview_notice(page, *_args):
    dialog = Adw.MessageDialog(transient_for=page.window, modal=True,
        heading="Vista previa de actualización",
        body="Esta actualización es ficticia. Puedes revisar las novedades y la notificación, pero no descargarla ni instalarla.")
    dialog.add_response("close", "Cerrar")
    dialog.set_close_response("close")
    dialog.present()


def main_preview():
    original_release = update_bundle.release
    def release(tag=None):
        return dict(INFO) if tag is None or tag == INFO["tag"] else original_release(tag)

    with tempfile.TemporaryDirectory(prefix="tab-companion-update-preview-") as cache, \
         patch.object(update_bundle, "release", side_effect=release), \
         patch.object(update_monitor, "cache_path", return_value=Path(cache) / "updates.json"), \
         patch.object(update_page.UpdatePage, "_confirm", preview_notice), \
         patch.object(update_page.UpdatePage, "_start", preview_notice), \
         patch.object(update_page.UpdatePage, "_restart", preview_notice), \
         patch.object(update_page.UpdatePage, "_restart_confirmed", preview_notice), \
         patch.object(update_page.UpdatePage, "_request_repair", preview_notice):
        app = main.CompanionApplication()
        if not app.register(None) or app.get_is_remote():
            raise SystemExit("Close the normal Tab Companion before starting the preview")
        # Keep the real application ID/actions for the desktop notification.
        # Only the read-only discovery cache is redirected; GSettings is not.
        app.hold()
        original_activate = app._activate
        def activate(_app):
            original_activate(_app)
            window = app.props.active_window
            if not getattr(window, "_preview_close_hook", False):
                window._preview_close_hook = True
                window.set_title("Tab Companion — VISTA PREVIA")
                window.update_page.local.set_sensitive(False)
                window.connect("close-request", lambda *_: (app.release(), False)[1])
        # Replace the existing activate handler, keeping the normal window.
        app.disconnect_by_func(original_activate)
        app.connect("activate", activate)

        def notify():
            app.hold()  # balanced by the real _weekly_result callback
            enabled = Mock()
            enabled.get_boolean.return_value = True
            # The callback requires opt-in. Override its read only, not the
            # user's saved preference or the subsequent UI's bindings.
            with patch.object(main.Gio.Settings, "new", return_value=enabled):
                app._weekly_result(dict(INFO), None)
            print("Preview notification sent; real updates and cache untouched", flush=True)
            return False
        app._weekly_check = lambda: None  # no repeat network/timer notification
        GLib.timeout_add(750, notify)
        try:
            return app.run([sys.argv[0], "--check-updates"])
        finally:
            app.withdraw_notification("system-update")


if __name__ == "__main__":
    raise SystemExit(main_preview())
