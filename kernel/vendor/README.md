# Vendor kernel sources

This directory contains redistributable kernel source code obtained from
hardware-vendor source releases. It never contains binary firmware.

`samsung-stm32-pogo/` is imported by
`scripts/import-samsung-pogo-sources.sh` from Samsung's official SM-X910 Android
16 source archive. The files are GPL version 2 and retain their original
copyright and licence notices. `SHA256SUMS` records the imported bytes.

The imported tree is kept unchanged as an auditable reference. The
mainline-compatible driver used by this project lives separately under
`kernel/drivers/` and documents which protocol definitions it derives from.

