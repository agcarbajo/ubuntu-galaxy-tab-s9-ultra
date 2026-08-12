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
    bluetooth_available: bool = False
    gesture_available: bool = False


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
            bluetooth_available=self._value("BluetoothAvailable", False),
            gesture_available=self._value("GestureAvailable", False),
        )
        self.emit("state-changed")
