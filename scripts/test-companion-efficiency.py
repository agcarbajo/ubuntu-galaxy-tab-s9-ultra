#!/usr/bin/env python3
"""Exercise duplicate-work reductions without a real pen or system bus."""
import ast
from pathlib import Path
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
print('PASS: one snapshot per sample, event refresh remains live, trust writes only when needed')