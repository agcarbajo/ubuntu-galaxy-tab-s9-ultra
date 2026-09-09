#!/usr/bin/env python3
"""Exercise launcher diversion lifecycle without touching dpkg or system files."""
import os
from pathlib import Path
import subprocess
import sys
import socket
import tempfile
from unittest.mock import patch

source=(Path(__file__).resolve().parents[1]/'packaging/ubuntu-gts9u-device/usr/libexec/ubuntu-gts9u-chromium-launchers').read_text()
with tempfile.TemporaryDirectory() as tmp:
 root=Path(tmp); target=root/'vendor-launcher'; original=Path(str(target)+'.gts9u-original')
 vendor='#!/bin/sh\nprintf "%s\\n" "$0" "$@"\n'
 target.write_text(vendor);target.chmod(0o755)
 code=source.replace("TARGETS = ['/opt/google/chrome/google-chrome', '/usr/lib/chatgpt/codex-launcher']",'TARGETS = '+repr([str(target)]))
 owner=['']
 def query(args,**kwargs):return owner[0]+'\n'
 def mutate(args,**kwargs):
  assert args[0]=='dpkg-divert'
  if '--add' in args:target.rename(original);owner[0]='ubuntu-gts9u-device'
  else:original.rename(target);owner[0]=''
 def apply(remove=False):
  with patch.object(sys,'argv',['installer']+(['--remove'] if remove else [])),patch('subprocess.check_output',query),patch('subprocess.run',mutate):exec(compile(code,'installer','exec'),{'__name__':'__main__'})
 bindir=root/'bin';bindir.mkdir();grep=bindir/'grep';grep.write_text('#!/bin/sh\nexit 0\n');grep.chmod(0o755)
 env={**os.environ,'PATH':str(bindir)+':'+os.environ['PATH']}
 apply();apply()
 args=['https://example.invalid/a b?x=1&y=2','--app-id=literal','']
 actual=subprocess.check_output([str(target),*args],env=env,text=True).splitlines()
 assert actual==[str(target),'--use-angle=vulkan',*args],actual
 actual=subprocess.check_output([str(target),'--use-angle=gl',*args],env=env,text=True).splitlines()
 assert actual==[str(target),'--use-angle=gl',*args],actual
 original.write_text(vendor+'# vendor update\n')
 apply();assert '# vendor update' in original.read_text()
 apply(True);assert not owner[0] and not original.exists() and '# vendor update' in target.read_text()
 apply(True)
 # Exercise the Electron-specific Wayland choice with an actual Unix socket.
 target=root/'codex-launcher';original=Path(str(target)+'.gts9u-original')
 target.write_text(vendor);target.chmod(0o755)
 code=source.replace("TARGETS = ['/opt/google/chrome/google-chrome', '/usr/lib/chatgpt/codex-launcher']",'TARGETS = '+repr([str(target)]))
 runtime=root/'runtime';runtime.mkdir()
 sock=socket.socket(socket.AF_UNIX);sock.bind(str(runtime/'wayland-0'))
 env.update(XDG_RUNTIME_DIR=str(runtime),WAYLAND_DISPLAY='wayland-0')
 apply()
 actual=subprocess.check_output([str(target),'test argument'],env=env,text=True).splitlines()
 assert actual==[str(target),'--ozone-platform=wayland','--use-angle=vulkan','test argument'],actual
 actual=subprocess.check_output([str(target),'--ozone-platform=x11','--use-angle=gl'],env=env,text=True).splitlines()
 assert actual==[str(target),'--ozone-platform=x11','--use-angle=gl'],actual
 apply(True);sock.close()
print('PASS: install, idempotence, argument preservation, explicit override, vendor update and removal')
