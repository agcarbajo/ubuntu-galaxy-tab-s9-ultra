// SPDX-License-Identifier: MIT
// gjs -m this-file.mjs file:///absolute/path/to/authRecovery.js
// Opens/closes ONLY its own private connection; never contacts GDM or fprintd.
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
const {recoverClosedCancellation} = await import(ARGV[0]);
const connection = Gio.DBusConnection.new_for_address_sync(
    GLib.getenv('DBUS_SESSION_BUS_ADDRESS'),
    Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
    null, null);
const proxy = Gio.DBusProxy.new_sync(connection, Gio.DBusProxyFlags.NONE, null,
    'org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus', null);
connection.close_sync(null);
let cleared = false;
let recovered = false;
const receiver = {_userVerifier: proxy, clear() { cleared = true; this._userVerifier = null; }};
const cancel = recoverClosedCancellation(
    () => proxy.call_sync('ListNames', null, Gio.DBusCallFlags.NONE, 1000, null),
    error => error.matches(Gio.IOErrorEnum, Gio.IOErrorEnum.CLOSED),
    () => { recovered = true; });
cancel.call(receiver);
if (!cleared || !recovered || receiver._userVerifier !== null)
    throw new Error('closed connection was not cleared');
print('PASS real GJS/GIO closed-connection recovery; no authentication performed');
