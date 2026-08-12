# SPDX-License-Identifier: MIT
"""Shared action catalogue for pen gestures and cover keyboard keys."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Action:
    action_id: str
    label: str


ACTIONS = (
    Action("none", "Do nothing"),
    Action("app", "Open an application"),
    Action("screenshot", "Take a screenshot"),
    Action("back", "Back"),
    Action("home", "Home"),
    Action("overview", "Overview"),
    Action("play-pause", "Play / pause"),
    Action("previous", "Previous track"),
    Action("next", "Next track"),
    Action("volume-up", "Volume up"),
    Action("volume-down", "Volume down"),
    Action("mute", "Mute"),
    Action("command", "Custom command"),
)

ACTION_IDS = tuple(action.action_id for action in ACTIONS)


def action_index(action_id):
    """Return a safe model index for a persisted action identifier."""
    try:
        return ACTION_IDS.index(action_id)
    except ValueError:
        return 0
