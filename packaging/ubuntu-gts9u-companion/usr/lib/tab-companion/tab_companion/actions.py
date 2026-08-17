# SPDX-License-Identifier: MIT
"""Shared action catalogue for pen gestures and cover keyboard keys."""

from dataclasses import dataclass

from .i18n import _, N_


@dataclass(frozen=True)
class Action:
    action_id: str
    label: str
    icon_name: str


"""
The two lists differ by one entry each, and the difference is real.

A cover key already does something on its own, so leaving it alone is a
meaningful choice: that is "none", which tells the daemon not to intercept the
key at all.  A pen gesture has no such fallback -- nothing in the system reacts
to a double press of the S Pen button -- so offering to "keep the default"
promised something that does not exist.  The pen therefore starts at "nothing",
and only the keyboard keeps "none".

"nothing" means the opposite of "none" where a key is concerned: intercept it
and then do nothing, which is how you silence a key that would otherwise act.
"""

DO_NOTHING = Action("nothing", N_("Do nothing"), "action-unavailable-symbolic")
KEEP_DEFAULT = Action("none", N_("Default action"), "edit-clear-all-symbolic")

_SHARED = (
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

PEN_ACTIONS = (DO_NOTHING,) + _SHARED
KEY_ACTIONS = (KEEP_DEFAULT, DO_NOTHING) + _SHARED

# Kept for anything that just needs to know an identifier exists.
ACTIONS = (KEEP_DEFAULT, DO_NOTHING) + _SHARED
ACTION_IDS = tuple(action.action_id for action in ACTIONS)


def actions_for(setting):
    """Which list a settings key chooses from.

    The prefix is the whole rule: `key-*` is a cover key, everything else is a
    pen gesture.  Passing the list around instead would mean threading it
    through every row, button and dialog for no extra information.
    """
    return KEY_ACTIONS if setting.startswith("key-") else PEN_ACTIONS


def action_for(setting, action_id):
    """The action a stored identifier means, for this kind of setting.

    A pen gesture saved as "none" by an older version lands on "nothing", which
    is what it always did in practice: the pen had no default to keep.
    """
    for action in actions_for(setting):
        if action.action_id == action_id:
            return action
    return actions_for(setting)[0]


def action_index(setting, action_id):
    """Return a safe model index for a persisted action identifier."""
    return actions_for(setting).index(action_for(setting, action_id))


def action_label(setting, action_id):
    """Return the display label for a persisted action identifier."""
    return _(action_for(setting, action_id).label)
