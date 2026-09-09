#!/usr/bin/env python3
"""Mock the diagnostic lifecycle on Linux; never opens real block devices."""
import argparse,pathlib,subprocess,tempfile
parser=argparse.ArgumentParser(description=__doc__)
for arg in ('kernel8', 'init-boot', 'kernel10', 'diagnostic-init'):
 parser.add_argument('--'+arg,type=pathlib.Path,required=True)
args=parser.parse_args()
source=pathlib.Path(__file__).with_name('kernel10-ramroot-test').read_text()
images={'kernel8.img':args.kernel8.resolve(),'init_boot.img':args.init_boot.resolve()}
for case in ('pass','early-wake','ufs-error'):
 with tempfile.TemporaryDirectory(prefix='ramroot-harness-') as temp:
  root=pathlib.Path(temp);work=root/'work';work.mkdir()
  fakefs=root/'fakefs';fs=fakefs/'var/lib/gts9u-diagnostics/kernel10-ramroot';fs.mkdir(parents=True)
  for name,p in images.items(): (fs/name).symlink_to(p)
  sysroot=root/'sys';rtc=sysroot/'class/rtc/rtc0';(rtc/'device/power').mkdir(parents=True)
  for name,value in [('since_epoch','1000'),('device/power/wakeup','enabled'),('wakealarm','0')]: (rtc/name).write_text(value)
  (sysroot/'power/suspend_stats').mkdir(parents=True)
  for name,value in [('power/pm_test','none'),('power/mem_sleep','deep'),('power/state',''),('power/suspend_stats/fail','0'),('class/block/sda35/uevent','PARTNAME=linuxroot\n'),('firmware/devicetree/base/compatible','samsung,gts9uwifi')]:
   p=sysroot/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(value)
  proc=root/'proc';proc.mkdir();(proc/'mounts').write_text('tmpfs /run tmpfs rw 0 0\n');(proc/'sysrq-trigger').touch()
  (root/'armed').touch();(root/'phase').write_text('0');(root/'kmsg').touch()
  data=root/'root-partition';data.write_bytes(bytes(8*1024*1024))
  boot=root/'boot';init=root/'init_boot'
  subprocess.run(['cp',str(args.kernel10.resolve()),str(boot)],check=True)
  subprocess.run(['cp',str(args.diagnostic_init.resolve()),str(init)],check=True)
  script=source.replace('SHA=/gts9u-tools/sha256sum','SHA=/usr/bin/sha256sum').replace('DD=/gts9u-tools/dd','DD=/usr/bin/dd').replace('TIMEOUT=/gts9u-tools/timeout','TIMEOUT=/usr/bin/timeout')
  for old,new in [('WORK=/run/gts9u-ramroot','WORK='+str(work)),('ROOT=/dev/sda35','ROOT='+str(data)),('BOOT=/dev/sda21','BOOT='+str(boot)),('INIT=/dev/sda22','INIT='+str(init)),('/sys/',str(sysroot)+'/'),('/proc/',str(proc)+'/'),('/dev/kmsg',str(root/'kmsg')),('/gts9u-ramroot-armed',str(root/'armed'))]:script=script.replace(old,new)
  prelude=f'''
mount() {{ echo "$*" >> '{root}/mount-log'; rm -rf '{work}/root'; ln -s '{fakefs}' '{work}/root'; }}
umount() {{ rm -f '{work}/root'; }}
uname() {{ echo '#10 mocked'; }}
blockdev() {{ case "$1" in --getsize64) case "$2" in */init_boot) echo 8388608;; *) echo 100663296;; esac;; --getro) echo 1;; esac; }}
udevadm() {{ :; }}
insmod() {{ :; }}
sleep() {{ exit 0; }}
dmesg() {{ if [ '{case}' = ufs-error ]; then echo 'phy initialization timed-out'; else echo 'no errors'; fi; }}
cat() {{
 if [ "$1" = '{rtc}/since_epoch' ]; then
  phase=$(/bin/cat '{root}/phase')
  if [ "$phase" = 0 ]; then echo 1 > '{root}/phase'; /bin/cat "$1";
  else
   delta=$(/bin/cat '{rtc}/wakealarm'); delta=${{delta#+}}
   [ '{case}' != early-wake ] || delta=1
   value=$(/bin/cat "$1"); value=$((value + delta)); echo "$value" > "$1"; echo "$value"; echo 0 > '{root}/phase'
  fi
 else /bin/cat "$@"; fi
}}
'''
  result=subprocess.run(['/bin/sh'],input=prelude+script,text=True,capture_output=True,timeout=40)
  assert result.returncode==0,(case,result.stderr)
  assert boot.read_bytes()==images['kernel8.img'].read_bytes(),case
  assert init.read_bytes()==images['init_boot.img'].read_bytes(),case
  assert (proc/'sysrq-trigger').read_text().strip()=='b',case
  if case=='pass':
   assert (fs/'status').read_text().strip()=='RAMROOT_PASS'
   assert (fs/'result.txt').read_text().count('PASS duration=')==3
  else:
   assert not (fs/'status').exists()
   assert len((root/'mount-log').read_text().splitlines())==1,'Error path mounted storage again'
  print('PASS ramroot mocked lifecycle:',case,flush=True)
