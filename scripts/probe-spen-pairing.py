#!/usr/bin/python3
"""Accept and trace the S Pen's device-initiated BlueZ pairing request."""

import argparse
from glob import glob
from pathlib import Path
import sys

import dbus
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib


BLUEZ = "org.bluez"
AGENT_PATH = "/io/furios/tabcompanion/spen_agent"
SPEN_SERVICES = {
    "0000fd6c-0000-1000-8000-00805f9b34fb",
    "0000fef5-0000-1000-8000-00805f9b34fb",
}


class Agent(dbus.service.Object):
    def __init__(self, bus, path, manager):
        super().__init__(bus, path)
        self.manager = manager

    def _accept(self, device):
        interfaces = self.manager.GetManagedObjects().get(device, {})
        if not is_docked() or not is_spen(interfaces.get("org.bluez.Device1", {})):
            raise dbus.DBusException(
                "Pairing request is not from the docked S Pen",
                name="org.bluez.Error.Rejected",
            )

    @dbus.service.method("org.bluez.Agent1", in_signature="", out_signature="")
    def Release(self):
        print("AGENT release", flush=True)

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="s")
    def RequestPinCode(self, device):
        self._accept(device)
        print(f"AGENT pin {device}", flush=True)
        return "0000"

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="u")
    def RequestPasskey(self, device):
        self._accept(device)
        print(f"AGENT passkey {device}", flush=True)
        return dbus.UInt32(0)

    @dbus.service.method("org.bluez.Agent1", in_signature="ouq", out_signature="")
    def DisplayPasskey(self, device, passkey, entered):
        self._accept(device)
        print(f"AGENT display-passkey {device} {passkey:06d} {entered}", flush=True)

    @dbus.service.method("org.bluez.Agent1", in_signature="os", out_signature="")
    def DisplayPinCode(self, device, pincode):
        self._accept(device)
        print(f"AGENT display-pin {device} {pincode}", flush=True)

    @dbus.service.method("org.bluez.Agent1", in_signature="ou", out_signature="")
    def RequestConfirmation(self, device, passkey):
        self._accept(device)
        print(f"AGENT confirm {device} {passkey:06d}", flush=True)

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="")
    def RequestAuthorization(self, device):
        self._accept(device)
        print(f"AGENT authorize {device}", flush=True)

    @dbus.service.method("org.bluez.Agent1", in_signature="os", out_signature="")
    def AuthorizeService(self, device, uuid):
        self._accept(device)
        print(f"AGENT service {device} {uuid}", flush=True)

    @dbus.service.method("org.bluez.Agent1", in_signature="", out_signature="")
    def Cancel(self):
        print("AGENT cancel", flush=True)


def is_spen(properties):
    name = str(properties.get("Alias") or properties.get("Name") or "")
    services = {str(uuid).lower() for uuid in properties.get("UUIDs", [])}
    return name.startswith("SPEN") and SPEN_SERVICES.issubset(services)


def is_docked():
    paths = glob("/sys/bus/i2c/devices/*/pen_docked")
    if not paths:
        return False
    try:
        return Path(paths[0]).read_text(encoding="ascii").strip() == "1"
    except OSError:
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=45)
    args = parser.parse_args()

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    manager = dbus.Interface(bus.get_object(BLUEZ, "/"), "org.freedesktop.DBus.ObjectManager")
    objects = manager.GetManagedObjects()
    adapter_path = next(path for path, ifaces in objects.items() if "org.bluez.Adapter1" in ifaces)
    adapter_object = bus.get_object(BLUEZ, adapter_path)
    adapter = dbus.Interface(adapter_object, "org.bluez.Adapter1")
    adapter_properties = dbus.Interface(adapter_object, "org.freedesktop.DBus.Properties")
    was_pairable = adapter_properties.Get("org.bluez.Adapter1", "Pairable")
    adapter_properties.Set("org.bluez.Adapter1", "Powered", dbus.Boolean(True))
    adapter_properties.Set("org.bluez.Adapter1", "Pairable", dbus.Boolean(True))

    Agent(bus, AGENT_PATH, manager)
    agent_manager = dbus.Interface(bus.get_object(BLUEZ, "/org/bluez"), "org.bluez.AgentManager1")
    with suppress_dbus("org.bluez.Error.AlreadyExists"):
        agent_manager.RegisterAgent(AGENT_PATH, "DisplayYesNo")
    agent_manager.RequestDefaultAgent(AGENT_PATH)

    connected = set()

    def connect(path, properties):
        if path in connected or not is_spen(properties):
            return
        connected.add(path)
        print(f"FOUND {path}", flush=True)
        try:
            dbus.Interface(bus.get_object(BLUEZ, path), "org.bluez.Device1").Connect()
            print("CONNECT requested", flush=True)
        except dbus.DBusException as error:
            print(f"CONNECT {error.get_dbus_name()} {error}", flush=True)

    def added(path, interfaces):
        if "org.bluez.Device1" in interfaces:
            connect(path, interfaces["org.bluez.Device1"])

    def changed(interface, changed_properties, invalidated, path=None):
        if interface == "org.bluez.Device1":
            state = {key: changed_properties[key] for key in ("Connected", "Paired", "Bonded", "ServicesResolved") if key in changed_properties}
            if state:
                print(f"STATE {path} {state}", flush=True)

    bus.add_signal_receiver(added, dbus_interface="org.freedesktop.DBus.ObjectManager", signal_name="InterfacesAdded")
    bus.add_signal_receiver(changed, dbus_interface="org.freedesktop.DBus.Properties", signal_name="PropertiesChanged", path_keyword="path")

    for path, interfaces in objects.items():
        if "org.bluez.Device1" in interfaces:
            connect(path, interfaces["org.bluez.Device1"])

    with suppress_dbus("org.bluez.Error.InProgress"):
        adapter.StartDiscovery()
    loop = GLib.MainLoop()
    GLib.timeout_add_seconds(args.seconds, loop.quit)
    print("READY", flush=True)
    try:
        loop.run()
    finally:
        with suppress_dbus("org.bluez.Error.NotReady", "org.bluez.Error.Failed"):
            adapter.StopDiscovery()
        with suppress_dbus("org.bluez.Error.DoesNotExist"):
            agent_manager.UnregisterAgent(AGENT_PATH)
        adapter_properties.Set("org.bluez.Adapter1", "Pairable", was_pairable)
    return 0


class suppress_dbus:
    def __init__(self, *names):
        self.names = names

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return isinstance(exc, dbus.DBusException) and exc.get_dbus_name() in self.names


if __name__ == "__main__":
    sys.exit(main())
