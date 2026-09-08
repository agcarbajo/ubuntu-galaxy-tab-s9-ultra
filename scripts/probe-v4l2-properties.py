#!/usr/bin/env python3
"""Exercise the installed OBS V4L2 property API without changing OBS settings."""
import ctypes as C

obs = C.CDLL("libobs.so.0", mode=C.RTLD_GLOBAL)


def api(name, result, *args):
    fn = getattr(obs, name)
    fn.restype, fn.argtypes = result, args
    return fn


assert api("obs_startup", C.c_bool, C.c_char_p, C.c_char_p, C.c_void_p)(b"en-US", None, None)
module = C.c_void_p()
assert api("obs_open_module", C.c_int, C.c_void_p, C.c_char_p, C.c_char_p)(
    C.byref(module), b"/usr/lib/aarch64-linux-gnu/obs-plugins/linux-v4l2.so",
    b"/usr/share/obs/obs-plugins/linux-v4l2") == 0
assert api("obs_init_module", C.c_bool, C.c_void_p)(module)
print("Calling V4L2 property enumeration", flush=True)
source = api("obs_source_create_private", C.c_void_p, C.c_char_p, C.c_char_p, C.c_void_p)(
    b"v4l2_input", b"Disposable camera property probe", None)
assert source
props = api("obs_source_properties", C.c_void_p, C.c_void_p)(source)
assert props
print("V4L2 properties created", flush=True)
api("obs_properties_destroy", None, C.c_void_p)(props)
api("obs_source_release", None, C.c_void_p)(source)
api("obs_shutdown", None)()
