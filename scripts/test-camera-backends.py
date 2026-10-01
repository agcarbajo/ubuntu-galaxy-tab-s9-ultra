#!/usr/bin/env python3
"""Evaluate packaged Lua rules without creating PipeWire objects or cameras."""
import ctypes
import ctypes.util
from pathlib import Path
import sys

config = (Path(sys.argv[1]) if len(sys.argv) > 1 else
          Path(__file__).resolve().parents[1] / "packaging/ubuntu-gts9u-device/usr/share/wireplumber/main.lua.d/51-gts9u-camera-backends.lua")
library = ctypes.util.find_library("lua5.4")
if not library:
    raise SystemExit("Run with the Lua 5.4 runtime used by Noble WirePlumber")
lua = ctypes.CDLL(library)
lua.luaL_newstate.restype = ctypes.c_void_p
lua.luaL_openlibs.argtypes = [ctypes.c_void_p]
lua.luaL_loadbufferx.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p, ctypes.c_char_p]
lua.lua_pcallk.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_ssize_t, ctypes.c_void_p]
lua.lua_tolstring.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
lua.lua_tolstring.restype = ctypes.c_char_p
lua.lua_close.argtypes = [ctypes.c_void_p]
checks = r'''
assert(#libcamera_monitor.rules == 4)
assert(#v4l2_monitor.rules == 4)
local labels = {"GTS9U-Front-Ultra-Wide", "GTS9U-Front-Main", "GTS9U-Rear-Main", "GTS9U-Rear-Ultra-Wide"}
local function disabled(props)
  for _, rule in ipairs(v4l2_monitor.rules) do
    for _, match in ipairs(rule.matches) do
      local matches = true
      for _, c in ipairs(match) do
        local value = props[c[1]] or ""
        if c[2] == "equals" then
          matches = matches and value == c[3]
        elseif c[2] == "matches" then
          local pattern = c[3]:gsub("([%.%-%+%?%[%]%^%$%%])", "%%%1"):gsub("%*", ".*")
          matches = matches and value:match("^" .. pattern .. "$") ~= nil
        else error("Unexpected predicate") end
      end
      if matches and rule.apply_properties["device.disabled"] then return true end
    end
  end
  return false
end
for n, label in ipairs(labels) do
  assert(libcamera_monitor.rules[n].apply_properties["media.class"] == "Video/Source")
  local virtual = "v4l2_device._sys_devices_virtual_video4linux_video" .. (19+n)
  assert(disabled({["device.name"]=virtual, ["device.description"]=label}))
  assert(not disabled({["device.name"]="v4l2_device.usb-webcam", ["device.description"]=label}))
  assert(not disabled({["device.name"]=virtual, ["device.description"]="Other loopback"}))
  assert(not disabled({["device.name"]="libcamera_device.sensor", ["device.description"]=label}))
end
'''
code = ("libcamera_monitor={rules={}}; v4l2_monitor={rules={}}\n" + config.read_text() + "\n" + checks).encode()
state = lua.luaL_newstate()
assert state
try:
    lua.luaL_openlibs(state)
    result = lua.luaL_loadbufferx(state, code, len(code), b"camera-rules-test", None)
    if not result:
        result = lua.lua_pcallk(state, 0, 0, 0, 0, None)
    if result:
        raise AssertionError(lua.lua_tolstring(state, -1, None).decode())
finally:
    lua.lua_close(state)
print("PASS: four native sources, board loopbacks filtered, USB/other virtual cameras retained")
