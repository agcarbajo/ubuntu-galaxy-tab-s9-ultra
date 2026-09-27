#!/usr/bin/env python3
"""Regression for a docked stale bond and truthful remote status."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import sys

ROOT = Path(__file__).resolve().parents[1]
COMPANION = ROOT / "packaging/ubuntu-gts9u-companion/usr/lib/tab-companion/tab_companion"
sys.path.insert(0, str(COMPANION))
from spen_status import remote_status_phase

source = ROOT / "packaging/ubuntu-gts9u-companion/usr/libexec/tab-companion-spen-pairing"
tree = ast.parse(source.read_text())
method = next(node for node in ast.walk(tree)
              if isinstance(node, ast.FunctionDef) and node.name == "SetRemoteEnabled")
method.decorator_list = []
clock = SimpleNamespace(now=100.0)
glib = SimpleNamespace(idle_add=Mock())
scope = {"time": SimpleNamespace(monotonic=lambda: clock.now), "GLib": glib}
exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), scope)
set_remote = scope["SetRemoteEnabled"]


def service(disabled_for, docked=True):
    return SimpleNamespace(
        remote_enabled=False, remote_disabled_at=clock.now-disabled_for,
        _save_remote_enabled=Mock(), finish_pairing=Mock(), connecting=set(),
        next_connect=20.0, disconnect_spen=Mock(), tick_once=Mock(),
        docked=lambda: docked, paired_spen=Mock(return_value=("/pen", {"Connected": False})),
        recover_stale_bond=Mock(return_value=True),
    )


long_pause = service(25)
assert set_remote(long_pause, True)
long_pause.recover_stale_bond.assert_called_once_with("/pen", "after remote re-enable")
assert not glib.idle_add.called
assert long_pause.remote_enabled and long_pause.remote_disabled_at is None
assert long_pause.reset_for_dock is False

short_pause = service(3)
assert set_remote(short_pause, True)
short_pause.recover_stale_bond.assert_not_called()
assert short_pause.reset_for_dock is False
glib.idle_add.assert_called_once_with(short_pause.tick_once)
glib.idle_add.reset_mock()

undocked = service(30, docked=False)
assert set_remote(undocked, True)
undocked.recover_stale_bond.assert_not_called()
assert undocked.repair_on_next_dock is True
glib.idle_add.assert_called_once_with(undocked.tick_once)
glib.idle_add.reset_mock()

already_connected = service(30)
already_connected.paired_spen.return_value = ("/pen", {"Connected": True})
assert set_remote(already_connected, True)
already_connected.recover_stale_bond.assert_not_called()
glib.idle_add.assert_called_once_with(already_connected.tick_once)
glib.idle_add.reset_mock()

for paired, connected, ready, pairing_active, expected in (
    (True, False, False, False, "reconnecting"),
    (False, False, False, True, "pairing"),
    (False, False, False, False, "pairing-needed"),
    (True, True, False, False, "preparing"),
    (True, True, True, False, "ready"),
    (True, False, True, False, "reconnecting"),
):
    assert remote_status_phase(bluetooth=True, enabled=True, docked=True,
                               paired=paired, connected=connected, ready=ready,
                               pairing_active=pairing_active) == expected
assert remote_status_phase(bluetooth=False, enabled=True, docked=True,
                           paired=True, connected=True, ready=True) == "bluetooth-off"
assert remote_status_phase(bluetooth=True, enabled=False, docked=True,
                           paired=True, connected=False, ready=False) == "remote-off"

tick_method = next(node for node in ast.walk(tree)
                   if isinstance(node, ast.FunctionDef) and node.name == "tick")
tick_scope = {"time": SimpleNamespace(monotonic=lambda: clock.now),
              "GLib": SimpleNamespace(SOURCE_CONTINUE=True)}
exec(compile(ast.Module(body=[tick_method], type_ignores=[]), str(source), "exec"),
     tick_scope)


def expired_window(attempts):
    state = SimpleNamespace(
        docked=lambda: True, remote_enabled=True, pairing=True,
        pairing_deadline=clock.now - 1, pairing_attempts=attempts,
        repairing_bond=True, reset_for_dock=True, repair_on_next_dock=False,
        paired_spen=lambda: (None, None), begin_pairing=Mock(),
    )
    state.finish_pairing = Mock(side_effect=lambda: setattr(state, "pairing", False))
    tick_scope["tick"](state)
    return state


first_timeout = expired_window(1)
first_timeout.begin_pairing.assert_called_once_with()
assert first_timeout.repairing_bond is False
last_timeout = expired_window(2)
last_timeout.begin_pairing.assert_not_called()
assert last_timeout.reset_for_dock is True

deferred = SimpleNamespace(
    docked=lambda: True, remote_enabled=True, repair_on_next_dock=True,
    paired_spen=lambda: ("/pen", {"Connected": False}),
    recover_stale_bond=Mock(return_value=True),
)
tick_scope["tick"](deferred)
deferred.recover_stale_bond.assert_called_once_with("/pen", "after next dock")
assert deferred.repair_on_next_dock is False

print("PASS: docked stale-bond recovery and connection/readiness status")
