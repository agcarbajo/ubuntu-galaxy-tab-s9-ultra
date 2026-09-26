#!/bin/sh
# One-shot diagnostic: keep ath12k's long MHI power-up outside device PM resume.
# Install in /usr/lib/systemd/system-sleep and arm with the /run file below.
set -eu

driver=/sys/bus/pci/drivers/ath12k_wifi7_pci
armed=/run/gts9u-wifi-suspend-isolation.armed
state=/run/gts9u-wifi-suspend-isolation.bdf

case "${1:-}" in
    pre)
        [ -e "$armed" ] || exit 0
        rm -f -- "$armed"
        for device in "$driver"/????:??:??.?; do
            [ -L "$device" ] || continue
            bdf=${device##*/}
            printf '%s\n' "$bdf" > "$state"
            if printf '%s' "$bdf" > "$driver/unbind"; then
                logger -t gts9u-wifi-isolation "unbound $bdf before suspend"
                exit 0
            fi
            rm -f -- "$state"
            logger -t gts9u-wifi-isolation "failed to unbind $bdf"
            exit 1
        done
        logger -t gts9u-wifi-isolation 'no bound ath12k PCIe device found'
        ;;
    post)
        [ -f "$state" ] || exit 0
        IFS= read -r bdf < "$state"
        case "$bdf" in
            ????\:??\:??.?) ;;
            *) logger -t gts9u-wifi-isolation 'invalid saved PCIe device'; exit 1 ;;
        esac
        if printf '%s' "$bdf" > "$driver/bind"; then
            rm -f -- "$state"
            logger -t gts9u-wifi-isolation "rebound $bdf after suspend"
        else
            logger -t gts9u-wifi-isolation "failed to rebind $bdf"
            exit 1
        fi
        ;;
esac
