# SPDX-License-Identifier: MIT
"""D-Bus-only hardware boundary used by the preferences UI."""

from dataclasses import dataclass

from gi.repository import Gio, GLib, GObject


BUS_NAME = "io.github.agcarbajo.TabCompanion.Hardware"
OBJECT_PATH = "/io/github/agcarbajo/TabCompanion/Hardware"
INTERFACE = BUS_NAME


@dataclass(frozen=True)
class HardwareState:
    pen_state: str = "unavailable"
    pen_orientation: str = "unknown"
    pen_battery: int = -1
    pen_charging: bool = False
    keyboard_present: bool = False
    keyboard_model: str = ""
    keyboard_name: str = ""
    remapping_available: bool = False
    last_special_key: str = ""
    button_actions_available: bool = False
    bluetooth_available: bool = False
    gesture_available: bool = False
    haptics_available: bool = False


class HardwareClient(GObject.Object):
    """Small async client; no sysfs or input path is allowed above this layer."""

    __gsignals__ = {"state-changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self):
        super().__init__()
        self.state = HardwareState()
        self.proxy = None
        Gio.DBusProxy.new_for_bus(
            Gio.BusType.SESSION,
            Gio.DBusProxyFlags.NONE,
            None,
            BUS_NAME,
            OBJECT_PATH,
            INTERFACE,
            None,
            self._proxy_ready,
        )

    def _proxy_ready(self, _source, result):
        try:
            self.proxy = Gio.DBusProxy.new_for_bus_finish(result)
        except GLib.Error:
            return
        self.proxy.connect("g-properties-changed", self._properties_changed)
        self._read_properties()

    def _properties_changed(self, *_args):
        self._read_properties()

    def _value(self, name, fallback):
        value = self.proxy.get_cached_property(name)
        return value.unpack() if value is not None else fallback

    def _read_properties(self):
        self.state = HardwareState(
            pen_state=self._value("PenState", "unavailable"),
            pen_orientation=self._value("PenOrientation", "unknown"),
            pen_battery=self._value("PenBattery", -1),
            pen_charging=self._value("PenCharging", False),
            keyboard_present=self._value("KeyboardPresent", False),
            keyboard_model=self._value("KeyboardModel", ""),
            keyboard_name=self._value("KeyboardName", ""),
            remapping_available=self._value("RemappingAvailable", False),
            last_special_key=self._value("LastSpecialKey", ""),
            button_actions_available=self._value("ButtonActionsAvailable", False),
            bluetooth_available=self._value("BluetoothAvailable", False),
            gesture_available=self._value("GestureAvailable", False),
            haptics_available=self._value("HapticsAvailable", False),
        )
        self.emit("state-changed")

    def vibrate(self, duration_ms=80, magnitude=65535):
        if self.proxy is None:
            return
        self.proxy.call(
            "Vibrate",
            GLib.Variant("(uu)", (duration_ms, magnitude)),
            Gio.DBusCallFlags.NONE,
            2000,
            None,
            None,
        )
