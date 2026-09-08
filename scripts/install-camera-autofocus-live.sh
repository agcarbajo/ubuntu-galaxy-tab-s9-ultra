#!/bin/bash
# Narrow, pinned live transaction. Does not change kernel, tuning or relay code.
set -Eeuo pipefail
[[ $EUID == 0 ]] || { echo 'Requires root via pkexec.' >&2; exit 1; }
exec 9>/run/lock/gts9u-camera-gpu.lock
flock -n 9
files=(
 usr/lib/aarch64-linux-gnu/libcamera.so.0.7.2
 usr/lib/aarch64-linux-gnu/libcamera-base.so.0.7.2
 usr/lib/aarch64-linux-gnu/libcamera/ipa/ipa_soft_simple.so
 usr/lib/aarch64-linux-gnu/libcamera/ipa/ipa_soft_simple.so.sign
 usr/libexec/libcamera/soft_ipa_proxy
 usr/bin/cam
)
hashes=(
 2bebd6e5d819421f1a50778c432ae947bc290de39b9f3fc24d1ac2ec5151779e
 45db597d33a76a8732f6d1aaf51c74b541de5f26597238481f462ed8c58e4aec
 7ff0a5af6149788b8f7ee5d081d94961caf424e425f23af1ebe9fca50958c8f8
 e6609c92e1c4e43738dbbedd98cf306f026c02c382fd606adfe3b22933093142
 882b3a72a322772d1455349d119bd647227cb9171f85d4e13125c2633faa003f
 2657421dcfdf56e62ecaa76c64812800ee8aba2ea72ba25889187f430933d17b
)
[[ $(id -u agcar) == 1000 && -S /run/user/1000/bus ]]
userctl() {
 runuser -u agcar -- env XDG_RUNTIME_DIR=/run/user/1000 \
  DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus systemctl --user "$@"
}
stop_stack() {
 systemctl stop ubuntu-gts9u-camera-relays.service
 userctl stop wireplumber.service pipewire-pulse.service pipewire-pulse.socket pipewire.service pipewire.socket
}
start_stack() {
 userctl start pipewire.socket pipewire-pulse.socket pipewire.service pipewire-pulse.service wireplumber.service
 systemctl start ubuntu-gts9u-camera-relays.service
}
verify() {
 local base=$1 i sum
 for i in "${!files[@]}"; do
  [[ -f "$base/${files[$i]}" && ! -L "$base/${files[$i]}" ]]
  sum=$(sha256sum "$base/${files[$i]}")
  [[ ${sum%% *} == "${hashes[$i]}" ]]
 done
}
replace_files() {
 local base=$1 rel temporary
 for rel in "${files[@]}"; do
  temporary=$(mktemp "/$rel.gts9u.XXXXXXXX")
  cp --preserve=mode,timestamps "$base/$rel" "$temporary"
  chown root:root "$temporary"
  mv -f "$temporary" "/$rel"
 done
 ldconfig
}
rollback() {
 stop_stack
 replace_files "$backup/original"
 start_stack
 echo "Restored camera libraries from $backup"
}
mode=${1:-}
case "$mode" in
 install)
  stage=$(realpath -e "${2:?candidate stage required}")
  verify "$stage"
  [[ $(sha256sum /usr/lib/aarch64-linux-gnu/libcamera.so.0.7.2 | cut -d' ' -f1) == c113d774c287cf60d2fcc69449517d8b917cc40926bef149a740269ed0f3a60b ]]
  install -d -m 0700 /var/lib/gts9u-camera-backups
  backup=$(mktemp -d /var/lib/gts9u-camera-backups/af-20260908.XXXXXXXX)
  install -m 0755 "$(realpath "$0")" "$backup/transaction.sh"
  mkdir "$backup/original" "$backup/candidate"
  for rel in "${files[@]}"; do
   [[ -f /$rel && ! -L /$rel ]]
   (cd / && cp -a --parents "$rel" "$backup/original")
   (cd "$stage" && cp -a --parents "$rel" "$backup/candidate")
  done
  verify "$backup/candidate"
  unit=gts9u-camera-rollback-${backup##*/}
  systemd-run --unit="$unit" --on-active=15m \
   "$backup/transaction.sh" rollback "$backup"
  trap 'trap - ERR; rollback; exit 1' ERR
  stop_stack
  replace_files "$backup/candidate"
  verify /
  start_stack
  trap - ERR
  echo "Installed candidate. Backup: $backup"
  echo "Rollback timer: $unit.timer (accept only after live tests)"
  ;;
 rollback|accept)
  backup=$(realpath -e "${2:?backup directory required}")
  [[ $backup == /var/lib/gts9u-camera-backups/af-20260908.* && -d $backup/original ]]
  unit=gts9u-camera-rollback-${backup##*/}
  if [[ $mode == rollback ]]; then rollback; else verify /; fi
  systemctl stop "$unit.timer" || true
  echo "$mode completed; backup retained at $backup"
  ;;
 *) echo 'Usage: install STAGE | rollback BACKUP | accept BACKUP' >&2; exit 2 ;;
esac
