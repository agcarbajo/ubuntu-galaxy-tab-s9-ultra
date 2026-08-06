# The EF-DX920 pogo keyboard, in one page

The Book Cover Keyboard Slim talks to an STM32G0 that lives **in the tablet**,
on I2C6 at address `0x2a`, not in the cover.  That controller runs one of two
applications, and only one of them works here:

| Version | Under Ubuntu | Under One UI |
|---|---|---|
| **V37** (Samsung's X910 blob) | works | works |
| V34 (older application) | announces no protocol ID; cover is dead | works |

The mainline driver reproduces Samsung's V37 start-up sequence.  V34 speaks a
different one: the controller boots fine, pulses the connection line every
~2.1 s and never sends `0xd6`.  That is the whole failure, and it looks exactly
like a wiring or timing problem, which is why it cost several sessions.

## Checking

```
cat /sys/bus/i2c/devices/6-002a/diagnostics
```

`flash_version=00370037` is healthy.  `flash_version=00340034` means the
controller has been put back to V34 and the cover will not work until it is
restored.

## Restoring

`ubuntu-gts9u-pogo-firmware.service` does it automatically, once per boot,
whenever the version is not V37, the cover is attached and the battery is at
least 50 %.  It needs no supervision: the STM32 ROM bootloader cannot be erased
and answers on every boot, and the driver re-reads all 52 KiB before reporting
success, so an interrupted write is simply completed on the next boot.

To run it by hand:

```
sudo /usr/libexec/ubuntu-gts9u-pogo-firmware-update
```

To stop it from ever writing:

```
sudo systemctl mask ubuntu-gts9u-pogo-firmware.service
```

## What still is not known

Nothing in this port ships a V34 image, so the downgrade does not come from
here.  The likely source is Samsung's own `stm32_pogo_v3` driver with its
vendor blobs, under One UI or under the Ubuntu Touch port.  If the cover stops
working after booting one of those, check `flash_version` first.
