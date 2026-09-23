#!/usr/bin/env python3
"""Exercise duplicate-work reductions without a real pen or system bus."""
import ast
from pathlib import Path
import struct
from types import SimpleNamespace
from unittest.mock import Mock

root=Path(__file__).resolve().parents[1]
helpers=root/'packaging/ubuntu-gts9u-companion/usr/libexec'

def method(file,name,namespace):
    tree=ast.parse((helpers/file).read_text())
    node=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name==name)
    exec(compile(ast.Module(body=[node],type_ignores=[]),file,'exec'),namespace)
    return namespace[name]

props=Mock()
ns={'is_spen':lambda p:True,'dbus':SimpleNamespace(Interface=lambda *a:props,Boolean=bool,DBusException=RuntimeError),'BLUEZ':'bluez','PROPERTIES_IFACE':'props','DEVICE_IFACE':'device'}
consider=method('tab-companion-spen-pairing','consider',ns)
service=SimpleNamespace(remote_enabled=True,connect_failures={},pairing=False,bus=Mock(),finish_pairing=Mock(),docked=lambda:False,connect=Mock())
consider(service,'/pen',{'Paired':True,'Trusted':True})
props.Set.assert_not_called()
consider(service,'/pen',{'Paired':True,'Trusted':False})
props.Set.assert_called_once_with('device','Trusted',True)
service.connect.assert_not_called()
ns={'dbus':SimpleNamespace(DBusException=RuntimeError),'BLUEZ_ADAPTER':'adapter','BLUEZ_DEVICE':'device'}
powered=method('tab-companion-hardware','_refresh_bluetooth_powered',ns)
ble=method('tab-companion-hardware','_refresh_spen_ble',ns)
manager=Mock();manager.GetManagedObjects.return_value={}
service=SimpleNamespace(bluez_manager=manager,_set_bluetooth_powered=Mock(),_remote_effective=lambda:True,_ble_disconnected=Mock())
snapshot=powered(service)
ble(service,snapshot)
assert manager.GetManagedObjects.call_count==1
ble(service)
assert manager.GetManagedObjects.call_count==2
pairing_tree=ast.parse((helpers/'tab-companion-spen-pairing').read_text())
remote=next(n for n in ast.walk(pairing_tree) if isinstance(n,ast.FunctionDef) and n.name=='SetRemoteEnabled')
assert any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='idle_add' and n.args and isinstance(n.args[0],ast.Attribute) and n.args[0].attr=='tick_once' for n in ast.walk(remote))
ns={'GLib':SimpleNamespace(SOURCE_REMOVE=False)}
tick_once=method('tab-companion-spen-pairing','tick_once',ns)
service=SimpleNamespace(tick=Mock())
assert tick_once(service) is False
service.tick.assert_called_once_with()
print('PASS: one snapshot per sample, event refresh remains live, trust writes only when needed, idle tick stops')

clock = SimpleNamespace(SOURCE_CONTINUE=True, SOURCE_REMOVE=False, IO_HUP=2, IO_ERR=4,
                        IO_IN=1, timeout_add=Mock(side_effect=range(1, 100)),
                        source_remove=Mock(), io_add_watch=Mock())
input_event = struct.Struct('llHHi')
pen_os = SimpleNamespace(read=Mock(), open=Mock(return_value=5), close=Mock(),
                         O_RDONLY=0, O_NONBLOCK=2048)
pen_ioctl = Mock()
pen_ns = {'GLib': clock, 'EV_KEY': 1, 'BTN_STYLUS': 331, 'BTN_TOOL_PEN': 320,
          'EVIOCGKEY': 0x80004518, 'INPUT_EVENT': input_event, 'os': pen_os,
          'fcntl': SimpleNamespace(ioctl=pen_ioctl),
          'classify_spen_motion': lambda points: 'gesture-swipe-right' if points else None}

class PenService:
    pass

for name in ('_set_pen_proximity', '_pen_event', '_pen_button', '_pen_single_press',
             '_pen_long_press', '_spen_ble_button_data', '_ensure_pen_reader',
             '_close_pen_reader'):
    setattr(PenService, name, method('tab-companion-hardware', name, pen_ns))

def pen_service(mode='gestures'):
    service = PenService()
    service.settings = SimpleNamespace(get_string=lambda key: mode)
    service._remote_effective = lambda: True
    service.execute_mapping = Mock()
    service.virtual_pointer = Mock()
    service._sync_pointer = Mock()
    service._pointer_move = Mock()
    service.pen_fd = 5
    service.pen_in_proximity = False
    service.pen_gesture_blocked = False
    service.pen_pressed = False
    service.pen_long_timer = None
    service.pen_single_timer = None
    service.pen_long_fired = False
    service.pen_motion = []
    service.pen_motion_energy = 0
    service.pen_motion_active = False
    return service

def send_events(service, *events):
    pen_os.read.return_value = b''.join(input_event.pack(0, 0, 1, code, value)
                                         for code, value in events)
    assert service._pen_event(None, 0) is True

service = pen_service()
send_events(service, (320, 1), (331, 1), (331, 0))
service._pen_single_press()
service.execute_mapping.assert_not_called()
send_events(service, (320, 0), (331, 1), (331, 0))
service._pen_single_press()
service.execute_mapping.assert_called_once_with('gesture-single-press')

service = pen_service()
service._pen_button(True)
service._pen_button(False)
service._pen_button(True)
service._pen_button(False)
service.execute_mapping.assert_called_once_with('gesture-double-press')

service = pen_service()
service._pen_button(True)
service._pen_button(False)
assert service.pen_single_timer is not None
send_events(service, (320, 1))
assert service.pen_single_timer is None
service._pen_single_press()
service.execute_mapping.assert_not_called()
service._pen_button(True)
send_events(service, (320, 0), (331, 0))
service.execute_mapping.assert_not_called()

service = pen_service()
service._pen_button(True)
send_events(service, (320, 1), (320, 0))
service._pen_long_press()
service._pen_button(False)
service.execute_mapping.assert_not_called()

service = pen_service()
send_events(service, (320, 1))
service._spen_ble_button_data(bytes([15, 200, 0, 200, 0, 0]))
service._spen_ble_button_data(bytes([14, 200, 0, 200, 0, 0]))
assert service.pen_motion == [] and service.pen_motion_energy == 0
service.execute_mapping.assert_not_called()
send_events(service, (320, 0))
service._spen_ble_button_data(bytes([3]))
service._spen_ble_button_data(bytes([0, 0, 0, 0, 0, 0]))
service._pen_single_press()
service.execute_mapping.assert_called_once_with('gesture-single-press')

service = pen_service()
for _ in range(5):
    service._spen_ble_button_data(bytes([15, 100, 0, 0, 0, 0]))
service._spen_ble_button_data(bytes([14, 100, 0, 0, 0, 0]))
service.execute_mapping.assert_called_once_with('gesture-swipe-right')

service = pen_service('pointer')
send_events(service, (320, 1), (331, 1), (331, 0))
assert [entry.args for entry in service.virtual_pointer.button.call_args_list] == [
    (True,), (False,)
]
service.execute_mapping.assert_not_called()
service._spen_ble_button_data(bytes([3]))
service._spen_ble_button_data(bytes([0, 0, 0, 0, 0, 0]))
assert [entry.args for entry in service.virtual_pointer.button.call_args_list] == [
    (True,), (False,), (True,), (False,)
]

service = pen_service()
service.pen_fd = None
service.pen_watch = None
service._find_pen_event = lambda: '/dev/input/event-test'
pen_ioctl.side_effect = lambda fd, request, keys, mutate: keys.__setitem__(320 // 8, 1)
service._ensure_pen_reader()
assert service.pen_in_proximity
assert pen_ioctl.call_args.args[1] == 0x80294518
service._pen_button(True)
service._pen_button(False)
service.execute_mapping.assert_not_called()

service = pen_service()
service._pen_button(True)
service._close_pen_reader()
assert service.pen_in_proximity and not service.pen_pressed
service._pen_button(False)
service.execute_mapping.assert_not_called()
print('PASS: S Pen hover suppresses EMR/BLE gestures, cancels timers, seeds proximity, preserves pointer clicks')