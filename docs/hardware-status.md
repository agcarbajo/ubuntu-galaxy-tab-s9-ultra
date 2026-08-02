# Estado de hardware del SM-X910 bajo Ubuntu 24.04

Última actualización: 2026-08-02, durante el bring-up de la funda EF-DX920.

Ubuntu **ya arranca** en la tablet. Esta matriz distingue explícitamente lo
heredado de lo comprobado, y ningún componente pasa a ✅ sin observación real.

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
| Arranque Android v4 + rootfs microSD | ✅ | ✅ | confirmado | Arranca desde microSD con `root=LABEL=`. Initramfs propio en LZ4 legacy dentro de `init_boot` |
| Pantalla interna 2960×1848@120 | ✅ | ✅ | medido | La recuperación cold-boot está validada bajo Ubuntu: el journal registra `panel id 00 00 00` → ciclo `pm_test=platform` → `80 00 04` |
| GPU Adreno 740 | ✅ | ✅ | confirmado | Confirmado por la usuaria en el primer arranque. Falta medir `vulkaninfo`/`glmark2` |
| Escritorio GNOME/Wayland | ✅ | ✅ | confirmado | GDM3 y GNOME 46 nativos, sin el workaround de cuentas greeter de Alpine |
| Brillo / blanking | ✅ | ⏳ | heredado | Backlight DCS. El brillo automático no funciona en ninguna distro |
| Táctil Goodix GT9916 | ✅ | ✅ | confirmado | Layout Samsung de eventos de 16 bytes |
| Botones power y volumen | ✅ | ✅ | confirmado | |
| UFS interna | ✅ | ⏳ | heredado | Seis LUN `sda`–`sdf`; usada solo para las particiones de arranque |
| microSD | ✅ | ✅ | medido | Raíz por etiqueta `UBTS9U_ROOT`; la partición se expande en el primer arranque |
| Wi-Fi WCN7850 / ath12k | ✅ | ✅ | confirmado | Conectada a la red por la usuaria; SSH en uso para el desarrollo |
| Bluetooth y A2DP | ✅ | ✅ | confirmado | La unidad espera a `bluetoothd`, alimenta correctamente `btmgmt` y reaplica la dirección nativa; controlador y A2DP validados |
| Altavoces 4× CS35L45 y DMIC | ✅ | ✅ | confirmado | PipeWire nativo, sin PulseAudio. Requiere el arranque tardío del ADSP y `protection-domain-mapper` |
| Protección DSP de altavoces | ❌ | ❌ | supuesto | Firmware Cirrus sin cargar; volumen de hardware conservador |
| Batería | ✅ | ✅ | confirmado | SM5714: porcentaje, voltaje, corriente y temperatura del pack |
| Carga USB-PD/PPS | 🟡 | ⏳ | heredado | SM5714 TCPM + SM5440 2:1; a batería baja sigue sin revalidar |
| Suspensión profunda | ✅ | ✅ | confirmado | Probada mediante la funda |
| Funda / Hall `SW_LID` | ✅ | ✅ | confirmado | Cerrar apaga la pantalla |
| Acelerómetro y autorrotación | ✅ | ✅ | medido | `libssc` + `hexagonrpcd` empaquetados por este port. Acelerómetro leído desde arranque limpio (gravedad 9,76 m/s²) y expuesto en `net.hadess.SensorProxy` como `HasAccelerometer: true` |
| Giroscopio y brújula LSM6DSO | ✅ | ✅ | medido | El mismo canal SSC; `monitor-sensor` sigue el rumbo de la brújula |
| USB gadget / RNDIS | ✅ | ⏳ | heredado | |
| USB host, HID y almacenamiento | ✅ | ✅ | confirmado | Con y sin alimentación externa |
| DisplayPort USB-C | ✅ | ✅ | confirmado | Salida de vídeo confirmada por la usuaria |
| Ethernet RTL8153 | 🟡 | ⏳ | heredado | Enumera y carga firmware; falta enlace y tráfico reales |
| UAS | ❓ | ❓ | supuesto | Nunca probado: no hubo unidad con interfaz UAS |
| Luz ambiental STK31610 | ❌ | ❌ | supuesto | El SSC lo descubre pero no emite lux; vía agotada en pmOS |
| Proximidad | — | — | — | El firmware SSC stock del X910 no instancia el sensor |
| S Pen (Wacom I²C 0x56) | ❌ | ❌ | supuesto | |
| Teclado pogo EF-DX920 (STM32 I²C 0x2a) | ❌ | 🟡 | medido | Teclas `EV_KEY` confirmadas; SE15 a 100 kHz estable en dos reinicios y un rebind bajo carga, pendiente escritura sostenida normal |
| Huella (EgisTec EL7xx, SPI) | ❌ | ❌ | supuesto | Sin driver mainline |
| Vibración / hápticos | ❌ | ❌ | supuesto | Hardware sin identificar |
| Flash / linterna | ❌ | ❌ | supuesto | PM8350C; candidato `leds-qcom-flash` |
| Cámaras | ❌ | ❌ | supuesto | No iniciadas |
| Módem | — | — | — | No aplica al modelo Wi-Fi |

## Riesgos de Ubuntu: cómo quedaron

Los cinco riesgos anticipados antes del primer arranque, con lo que ocurrió
realmente.

1. **UCM — resuelto.** El perfil propio de la X910 convive con el
   `alsa-ucm-conf` de Ubuntu sin conflicto; se instala en
   `conf.d/sm8550/` y `Qualcomm/sm8550/GTS9U/` y tiene prioridad.
2. **PipeWire frente a PulseAudio — resuelto a favor de PipeWire.** No hizo
   falta PulseAudio: PipeWire nativo expone los cuatro CS35L45 y los DMIC. A2DP
   sigue sin probar porque el controlador Bluetooth no se mantiene estable.
3. **`initramfs-tools` — resuelto, con trabajo.** Cumple los tres requisitos
   duros, pero solo tras forzar `COMPRESS=lz4`, corregir `MODULES` y podar la
   base de datos de udev para caber en `init_boot`.
4. **AppArmor — no se manifestó.** Los servicios de recuperación del panel y de
   arranque del ADSP escriben en `/sys/power` y en `remoteproc` sin que ningún
   perfil los bloquee. No se ha tocado AppArmor.
5. **Sensores — confirmado como el hueco previsto, y resuelto.** `pd-mapper` sí
   existe en Ubuntu (`protection-domain-mapper`), pero `libssc` y `hexagonrpcd`
   no. Empaquetarlos fue necesario pero no suficiente: hicieron falta tres
   correcciones más, todas en el repositorio y ninguna específica de Ubuntu.
   Ver «Autorrotación: los cuatro obstáculos» en el registro de porte.

### Frente abierto: funda con teclado EF-DX920

La v0.9 reproduce la máquina de estados de Samsung: QUPv3 SE15, VDDO, el
MAX77816 de SE4, las dos IRQ y la entrada/salida del bootloader ROM. El STM32
pasó de la aplicación antigua `00 34 00 34` a la imagen oficial del X910
`00 37 00 37`; los 52.132 bytes se releyeron y compararon antes de arrancarla.
Sin el reset adicional posterior a VDDO —que el stock no hace— el controlador
anuncia el modelo `0xd6` y Linux registra `Book Cover Keyboard Slim (EF-DX920)`.
El dispositivo solo existe mientras el modelo real está presente, por lo que
GNOME no pierde la autorrotación por un teclado fantasma. La fase de aplicación
stock también responde con versión, modo, CRC y ausencia esperada de touchpad.
La secuencia correcta —leer VERSION dentro de la IRQ y diferir 10 ms el resto—
desbloqueó las pulsaciones: `evtest` midió presiones y liberaciones reales. Una
traza posterior encontró la causa de la tormenta: el flanco descendente de
GPIO75 podía ejecutarse cuando DATA ya estaba inactiva y provocaba una lectura
de una cola vacía, timeout GENI y ciclo de alimentación. El handler conserva el
flanco para no perder pulsos cortos, pero aplica antes la comprobación de nivel
del driver Samsung. Bajo una tecla colocada como carga permaneció seis minutos
con cero pulsos GPIO62, cero recuperaciones y cero timeouts. Falta confirmar con
escritura física sostenida normal que todas las pulsaciones y liberaciones se
conservan.

Ese primer éxito a 400 kHz no sobrevivió al reinicio siguiente: bajo escritura
aparecieron decenas de GPIO62, NACK `-6`, timeouts y recreaciones de `event3`.
Forzar el runtime PM de SE15 a `on` no cambió el patrón, por lo que autosuspend
quedó descartado. La diferencia temporal mostró transacciones/reintentos de
~230–250 ms en el arranque malo. Reducir únicamente `clock-frequency` de SE15
a 100 kHz eliminó la tormenta en dos arranques consecutivos y tras un rebind del
driver; una tecla física se recibió en los tres casos. El estado sigue amarillo
hasta que la dueña pruebe escritura variada a esta frecuencia.

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
