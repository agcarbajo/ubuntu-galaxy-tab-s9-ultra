# SPDX-License-Identifier: MIT
"""Shared action catalogue for pen gestures and cover keyboard keys."""

from dataclasses import dataclass

from .i18n import _, N_


@dataclass(frozen=True)
class Action:
    action_id: str
    label: str
    icon_name: str


ACTIONS = (
    Action("none", N_("Keep the default action"), "edit-clear-all-symbolic"),
    Action("app", N_("Open an application"), "application-x-executable-symbolic"),
    Action("key", N_("Simulate a key"), "input-keyboard-symbolic"),
    Action("screenshot", N_("Take a screenshot"), "camera-photo-symbolic"),
    Action("back", N_("Back"), "go-previous-symbolic"),
    Action("home", N_("Home"), "go-home-symbolic"),
    Action("overview", N_("Overview"), "view-grid-symbolic"),
    Action("play-pause", N_("Play / pause"), "media-playback-start-symbolic"),
    Action("previous", N_("Previous track"), "media-skip-backward-symbolic"),
    Action("next", N_("Next track"), "media-skip-forward-symbolic"),
    Action("volume-up", N_("Volume up"), "audio-volume-high-symbolic"),
    Action("volume-down", N_("Volume down"), "audio-volume-low-symbolic"),
    Action("mute", N_("Mute"), "audio-volume-muted-symbolic"),
    Action("flashlight", N_("Toggle the flashlight"), "gts9u-flashlight-symbolic"),
    Action("command", N_("Run a command"), "utilities-terminal-symbolic"),
)

ACTION_IDS = tuple(action.action_id for action in ACTIONS)


def action_index(action_id):
    """Return a safe model index for a persisted action identifier."""
    try:
        return ACTION_IDS.index(action_id)
    except ValueError:
        return 0


def action_label(action_id):
    """Return the display label for a persisted action identifier."""
    return _(ACTIONS[action_index(action_id)].label)
