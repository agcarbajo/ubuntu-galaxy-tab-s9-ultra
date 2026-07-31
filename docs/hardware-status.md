# Estado de hardware del SM-X910 bajo Ubuntu 24.04

Última actualización: 2026-07-31, tras el primer arranque físico.

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
| Bluetooth y A2DP | ✅ | 🟡 | medido | La dirección de EFS levanta el controlador, verificado. Pero tras un **reinicio en caliente** el firmware no baja: `command 0xfc00 tx timeout`. Solo funcionó en arranque en frío. A2DP sin probar |
| Altavoces 4× CS35L45 y DMIC | ✅ | ✅ | confirmado | PipeWire nativo, sin PulseAudio. Requiere el arranque tardío del ADSP y `protection-domain-mapper` |
| Protección DSP de altavoces | ❌ | ❌ | supuesto | Firmware Cirrus sin cargar; volumen de hardware conservador |
| Batería | ✅ | ✅ | confirmado | SM5714: porcentaje, voltaje, corriente y temperatura del pack |
| Carga USB-PD/PPS | 🟡 | ⏳ | heredado | SM5714 TCPM + SM5440 2:1; a batería baja sigue sin revalidar |
| Suspensión profunda | ✅ | ✅ | confirmado | Probada mediante la funda |
| Funda / Hall `SW_LID` | ✅ | ✅ | confirmado | Cerrar apaga la pantalla |
| Sensores de movimiento y autorrotación | ✅ | ❌ | medido | `/dev/fastrpc-adsp` ya existe tras arrancar el ADSP, pero faltan `libssc` y `hexagonrpcd`, que Ubuntu no empaqueta |
| USB gadget / RNDIS | ✅ | ⏳ | heredado | |
| USB host, HID y almacenamiento | ✅ | ✅ | confirmado | Con y sin alimentación externa |
| DisplayPort USB-C | ✅ | ✅ | confirmado | Salida de vídeo confirmada por la usuaria |
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
5. **Sensores — confirmado como el hueco previsto.** `pd-mapper` sí existe en
   Ubuntu (`protection-domain-mapper`), pero `libssc` y `hexagonrpcd` no, y sin
   ellos `iio-sensor-proxy` no tiene de dónde leer.

### Frente abierto: Bluetooth tras reinicio en caliente

El controlador contesta a todas las consultas de versión y solo se atasca al
descargar el firmware (`command 0xfc00 tx timeout`). Solo se ha visto funcionar
en un arranque en frío. La recuperación por software está descartada con
evidencia: `rfkill` no cambia nada y un unbind/rebind del serdev empeora el
estado. Pendiente de comprobar si un apagado completo lo restaura.

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
