#!/usr/bin/python3
"""Connect to the Samsung S Pen and record its BlueZ GATT notifications."""

import argparse

import dbus
import dbus.mainloop.glib
from gi.repository import GLib


BLUEZ = "org.bluez"
DEVICE_IFACE = "org.bluez.Device1"
GATT_IFACE = "org.bluez.GattCharacteristic1"
PROPERTIES_IFACE = "org.freedesktop.DBus.Properties"
SPEN_SERVICES = {
    "0000fd6c-0000-1000-8000-00805f9b34fb",
    "0000fef5-0000-1000-8000-00805f9b34fb",
}
BATTERY_LEVEL_UUID = "5a87b4ef-3bfa-76a8-e642-92933c31434f"
MODE_UUID = "aca1ab48-08ba-e79e-ab48-a9b9e6429293"


def is_spen(properties):
    name = str(properties.get("Alias") or properties.get("Name") or "")
    services = {str(uuid).lower() for uuid in properties.get("UUIDs", [])}
    return name.startswith("SPEN") and SPEN_SERVICES.issubset(services)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen-seconds", type=int, default=30)
    args = parser.parse_args()

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    manager = dbus.Interface(bus.get_object(BLUEZ, "/"), "org.freedesktop.DBus.ObjectManager")
    objects = manager.GetManagedObjects()
    device_path = next(
        (
            path
            for path, interfaces in objects.items()
            if DEVICE_IFACE in interfaces
            and interfaces[DEVICE_IFACE].get("Paired", False)
            and is_spen(interfaces[DEVICE_IFACE])
        ),
        None,
    )
    if device_path is None:
        raise RuntimeError("Paired S Pen not found")

    device = bus.get_object(BLUEZ, device_path)
    properties = dbus.Interface(device, PROPERTIES_IFACE)
    if not properties.Get(DEVICE_IFACE, "Connected"):
        dbus.Interface(device, DEVICE_IFACE).Connect()
    if not properties.Get(DEVICE_IFACE, "ServicesResolved"):
        raise RuntimeError("S Pen services are not resolved")

    objects = manager.GetManagedObjects()
    characteristics = {
        str(interfaces[GATT_IFACE]["UUID"]).lower(): path
        for path, interfaces in objects.items()
        if path.startswith(f"{device_path}/") and GATT_IFACE in interfaces
    }
    battery = dbus.Interface(
        bus.get_object(BLUEZ, characteristics[BATTERY_LEVEL_UUID]), GATT_IFACE
    ).ReadValue({})
    print(f"BATTERY {int(battery[0])}", flush=True)

    mode = dbus.Interface(bus.get_object(BLUEZ, characteristics[MODE_UUID]), GATT_IFACE)
    mode.WriteValue(dbus.Array([dbus.Byte(0x10)], signature="y"), {})
    print("MODE 10", flush=True)

    paths_to_uuids = {path: uuid for uuid, path in characteristics.items()}

    def changed(interface, changed_properties, _invalidated, path=None):
        if interface != GATT_IFACE or "Value" not in changed_properties:
            return
        value = bytes(changed_properties["Value"])
        print(f"NOTIFY {paths_to_uuids.get(path, path)} {value.hex()}", flush=True)

    bus.add_signal_receiver(
        changed,
        dbus_interface=PROPERTIES_IFACE,
        signal_name="PropertiesChanged",
        path_keyword="path",
    )

    subscribed = []
    for uuid, path in characteristics.items():
        flags = objects[path][GATT_IFACE]["Flags"]
        if "notify" not in flags:
            continue
        characteristic = dbus.Interface(bus.get_object(BLUEZ, path), GATT_IFACE)
        try:
            characteristic.StartNotify()
        except dbus.DBusException as error:
            print(f"SKIP {uuid} {error.get_dbus_name()}", flush=True)
        else:
            subscribed.append(characteristic)

    print(f"READY {len(subscribed)}", flush=True)
    loop = GLib.MainLoop()
    GLib.timeout_add_seconds(args.listen_seconds, loop.quit)
    try:
        loop.run()
    finally:
        for characteristic in subscribed:
            try:
                characteristic.StopNotify()
            except dbus.DBusException:
                pass


if __name__ == "__main__":
    main()
