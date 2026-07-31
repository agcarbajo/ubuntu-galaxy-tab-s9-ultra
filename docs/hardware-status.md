# Estado de hardware del SM-X910 bajo Ubuntu 24.04

Última actualización: 2026-07-31. Ubuntu todavía **no ha arrancado** en la
tablet; esta matriz distingue explícitamente lo heredado de lo comprobado.

## Base

- Dispositivo: Samsung Galaxy Tab S9 Ultra Wi-Fi, SM-X910, `gts9uwifi`.
- SoC: Qualcomm Snapdragon 8 Gen 2, SM8550/kalama; GPU Adreno 740.
- Kernel: Linux mainline 7.2-rc3, commit fijado
  `a13c140cc289c0b7b3770bce5b3ad42ab35074aa`.
- Origen del soporte de hardware: postmarketOS v1.71 (kernel r114, device r44,
  firmware r10).
- Userspace objetivo: Ubuntu 24.04 LTS arm64, systemd, GNOME sobre Wayland.
- Rootfs: microSD ext4. Samsung ABL carga `boot` e `init_boot` y el
  DTB/cmdline de `vendor_boot` desde la UFS interna.

Para el primer hito se usa **el mismo kernel 7.2-rc3 y el mismo DTS ya
probados**. Actualizar el kernel se pospone hasta alcanzar paridad: mezclar un
cambio de distribución con un salto de kernel haría imposible atribuir una
regresión.

## Niveles de evidencia

Toda fila de la matriz lleva uno de estos niveles. No se admite «el driver
sondea» como prueba de funcionamiento.

| Nivel | Significado |
|---|---|
| **medido** | Confirmado en logs o instrumentación del propio sistema Ubuntu |
| **observado** | Visto físicamente por el asistente (captura OBS) o por la usuaria |
| **confirmado** | La usuaria lo declara funcional tras una prueba concreta |
| **heredado** | Validado en postmarketOS v1.71, no todavía en Ubuntu |
| **supuesto** | Ni probado ni validado en ninguna distribución |

## Matriz

| Componente | pmOS v1.71 | Ubuntu | Nivel | Notas |
|---|---|---|---|---|
| Arranque Android v4 + rootfs microSD | ✅ | ⏳ | heredado | Ubuntu necesita initramfs propio, LZ4 legacy y `root=LABEL=` |
| Pantalla interna 2960×1848@120 | ✅ | ⏳ | heredado | ANA38407/AMSA46AS02, DSI command mode, DSC y TE. Exige la recuperación cold-boot antes del display manager |
| GPU Adreno 740 | ✅ | ⏳ | heredado | Mesa/Freedreno/Turnip, OpenGL 4.6. `card0` render, `card1` DPU para KMS |
| Escritorio GNOME/Wayland | ✅ | ⏳ | heredado | Ubuntu debe probar GDM3 y Mutter nativos antes de portar parches |
| Brillo / blanking | ✅ | ⏳ | heredado | Backlight DCS. El brillo automático no funciona en ninguna distro |
| Táctil Goodix GT9916 | ✅ | ⏳ | heredado | Layout Samsung de eventos de 16 bytes |
| Botones power y volumen | ✅ | ⏳ | heredado | |
| UFS interna | ✅ | ⏳ | heredado | Seis LUN `sda`–`sdf`; usada solo para las particiones de arranque |
| microSD | ✅ | ⏳ | heredado | `sdhc_2`; la partición raíz se expande en el primer arranque |
| Wi-Fi WCN7850 / ath12k | ✅ | ⏳ | heredado | Firmware oficial + BDF QRD en ELF; solo ath12k y ath12k_wifi7 son módulos |
| Bluetooth y A2DP | ✅ | ⏳ | heredado | Dirección pública leída de EFS en `ro,noload`; en Ubuntu el sink pasa por PipeWire, no PulseAudio |
| Altavoces 4× CS35L45 y DMIC | ✅ | ⏳ | heredado | UCM propio; hay que verificar que `alsa-ucm-conf` de Ubuntu no lo tape |
| Protección DSP de altavoces | ❌ | ❌ | supuesto | Firmware Cirrus sin cargar; volumen de hardware conservador |
| Batería | ✅ | ⏳ | heredado | SM5714: porcentaje, voltaje, corriente y temperatura del pack |
| Carga USB-PD/PPS | 🟡 | ⏳ | heredado | SM5714 TCPM + SM5440 2:1; a batería baja sigue sin revalidar |
| Suspensión profunda | ✅ | ⏳ | heredado | Wake de 2–3 s; funda y botón power probados en pmOS |
| Funda / Hall `SW_LID` | ✅ | ⏳ | heredado | GPIO107; `HoldoffTimeoutSec=0` es necesario |
| Sensores de movimiento y autorrotación | ✅ | ⏳ | heredado | SSC/ADSP; requiere `libssc`, `hexagonrpcd` y `pd-mapper` empaquetados para Ubuntu |
| USB gadget / RNDIS | ✅ | ⏳ | heredado | |
| USB host, HID y almacenamiento | ✅ | ⏳ | heredado | Hubs alimentados y bus-powered |
| DisplayPort USB-C | ✅ | ⏳ | heredado | 1920×1080@60, incluido arranque con dock conectado |
| Ethernet RTL8153 | 🟡 | ⏳ | heredado | Enumera y carga firmware; falta enlace y tráfico reales |
| UAS | ❓ | ❓ | supuesto | Nunca probado: no hubo unidad con interfaz UAS |
| Luz ambiental STK31610 | ❌ | ❌ | supuesto | El SSC lo descubre pero no emite lux; vía agotada en pmOS |
| Proximidad | — | — | — | El firmware SSC stock del X910 no instancia el sensor |
| S Pen (Wacom I²C 0x56) | ❌ | ❌ | supuesto | |
| Teclado pogo (STM32 I²C 0x2a) | ❌ | ❌ | supuesto | Sin driver mainline |
| Huella (EgisTec EL7xx, SPI) | ❌ | ❌ | supuesto | Sin driver mainline |
| Vibración / hápticos | ❌ | ❌ | supuesto | Hardware sin identificar |
| Flash / linterna | ❌ | ❌ | supuesto | PM8350C; candidato `leds-qcom-flash` |
| Cámaras | ❌ | ❌ | supuesto | No iniciadas |
| Módem | — | — | — | No aplica al modelo Wi-Fi |

## Riesgos específicos de Ubuntu ya identificados

Ninguno está confirmado todavía; se registran para que la primera prueba
física sepa qué mirar.

1. **UCM.** Ubuntu instala `alsa-ucm-conf` de upstream. El perfil propio de la
   X910 debe tener prioridad o los cuatro CS35L45 no aparecerán como salida.
2. **PipeWire frente a PulseAudio.** La baseline validó audio y A2DP con
   PulseAudio 17. PipeWire es la opción nativa de Ubuntu y debe probarse
   primero, pero el resultado de la baseline no se transfiere automáticamente.
3. **`initramfs-tools` frente a `mkinitfs`.** Compresión LZ4 legacy, tamaño
   bajo 8 MiB y montaje por etiqueta son requisitos duros que el initramfs por
   defecto de Ubuntu no cumple.
4. **AppArmor.** Ubuntu lo trae activo; los servicios de recuperación del panel
   y de sensores escriben en `/sys/power` y en `remoteproc`. Si un perfil los
   bloquea, la solución es un perfil explícito, no desactivar AppArmor.
5. **Sensores.** `iio-sensor-proxy` de Ubuntu no sirve de nada sin `libssc`,
   `hexagonrpcd` y `pd-mapper`, que no existen en el archivo de Ubuntu.

## Invariantes heredadas que no se pueden romper

- Proveedores críticos **built-in**; solo ath12k/ath12k_wifi7 como módulos
  aislados firmados, y siempre de la misma compilación que `boot`.
- Cambiar el DTS obliga a reescribir `vendor_boot`.
- No reactivar `lpass_ag_noc`: provocó bloqueos y el audio funciona sin él.
- Conservar el aplazamiento del HPD DisplayPort hasta después de la
  recuperación cold-boot del panel.
- Wi-Fi con firmware oficial y BDF QRD **con** envoltorio ELF. La BDF Samsung
  HMT.2.0 crashea el amss HMT.1.1 y no debe mezclarse ni despojarse de su ELF.
- No añadir lecturas MMIO/ioremap improvisadas para diagnosticar probes.
- Nunca escribir PIT, EFS, persist, modem/modemst ni calibraciones.
