# Estado de hardware del SM-X910 bajo Ubuntu 24.04

Última actualización: 2026-08-10, al mover la raíz a la UFS interna y acotar
qué parte de las cámaras funciona y cuál no.

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
- Rootfs: ext4 dentro de `userdata`, en la UFS interna, desde v0.18. Samsung
  ABL carga `boot` e `init_boot` y el DTB/cmdline de `vendor_boot` de esa misma
  UFS. Hasta v0.17 la raíz vivía en una microSD ext4.

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
| Arranque Android v4 + rootfs microSD | ✅ | ✅ | confirmado | Arranca desde microSD con `root=LABEL=UBTS9U_ROOT`. Initramfs propio en LZ4 legacy dentro de `init_boot`. Es la cadena de hasta v0.17 |
| Arranque con rootfs en UFS | — | ✅ | confirmado | v0.18 escribe la raíz en `userdata` y arranca con `root=LABEL=UBTS9U_UFS`. Flasheada por sideload y arrancada en el dispositivo el 2026-08-10. Solo cambia dónde busca la raíz el initramfs; el resto de la cadena es la misma |
| Pantalla interna 2960×1848@120 | ✅ | ✅ | medido | La recuperación cold-boot está validada bajo Ubuntu: el journal registra `panel id 00 00 00` → ciclo `pm_test=platform` → `80 00 04` |
| GPU Adreno 740 | ✅ | ✅ | confirmado | Confirmado por la usuaria en el primer arranque. Falta medir `vulkaninfo`/`glmark2` |
| Escritorio GNOME/Wayland | ✅ | ✅ | confirmado | GDM3 y GNOME 46 nativos, sin el workaround de cuentas greeter de Alpine |
| Brillo / blanking | ✅ | ⏳ | heredado | Backlight DCS. El brillo automático no funciona en ninguna distro |
| Táctil Goodix GT9916 | ✅ | ✅ | confirmado | Layout Samsung de eventos de 16 bytes |
| Botones power y volumen | ✅ | ✅ | confirmado | |
| UFS interna | ✅ | ✅ | medido | Seis LUN `sda`–`sdf`. Desde v0.18 aloja también la raíz, en `userdata` (`sda34`, 1 007 985 586 176 B), etiquetada `UBTS9U_UFS`. **Se reutiliza la partición tal cual: no se crea, borra ni redimensiona ninguna**, y en el primer arranque solo se redimensiona el sistema de ficheros con `resize2fs` |
| microSD | ✅ | ✅ | medido | Raíz por etiqueta `UBTS9U_ROOT` hasta v0.17; la partición se expande en el primer arranque. Desde 2026-08-03 se crea **con journal** y `errors=remount-ro`: sin journal un apagado sucio acabó tirando el arranque a modo emergencia. La misma decisión se hereda en la imagen de UFS |
| Wi-Fi WCN7850 / ath12k | ✅ | ✅ | confirmado | Conectada a la red por la usuaria; SSH en uso para el desarrollo |
| Bluetooth y A2DP | ✅ | ✅ | confirmado | La unidad espera a `bluetoothd`, alimenta correctamente `btmgmt` y reaplica la dirección nativa; controlador y A2DP validados |
| Altavoces 4× CS35L45 y DMIC | ✅ | ✅ | confirmado | PipeWire nativo, sin PulseAudio. Requiere el arranque tardío del ADSP y `protection-domain-mapper` |
| Protección DSP de altavoces | ❌ | ❌ | supuesto | Firmware Cirrus sin cargar; volumen de hardware conservador |
| Batería | ✅ | ✅ | confirmado | SM5714: porcentaje, voltaje, corriente y temperatura del pack |
| Carga USB-PD/PPS | ✅ | ✅ | medido | SM5714 TCPM + SM5440 2:1. **25,2-25,5 W** sostenidos cinco minutos con el EP-T4510, die a 49,5 °C y pack a 36,4 °C. El techo lo ponía la corriente pedida en el contrato PPS, fijada a 3000 mA; barrida en hardware, el óptimo está en 3400 (por encima sube `ibus` y no la potencia, sólo el die). Ajustable en `/sys/module/sm5440_direct/parameters/pps_op_curr_ma` |
| Suspensión profunda | ✅ | ✅ | confirmado | Probada mediante la funda |
| Funda / Hall `SW_LID` | ✅ | ✅ | confirmado | Cerrar apaga la pantalla |
| Acelerómetro y autorrotación | ✅ | ✅ | confirmado | SSC expuesto a GNOME. `iio-sensor-proxy` ya no gira: la espera síncrona de libssc bloquea en `poll()` en vez de iterar el contexto sin bloquear. 1 tick/2 s frente a 199, y 48,9 °C frente a 94,7. La usuaria confirmó girando la tablet que la rotación sigue bien tras el cambio |
| Giroscopio y brújula LSM6DSO | ✅ | ✅ | medido | El mismo canal SSC; `monitor-sensor` sigue el rumbo de la brújula |
| USB gadget / RNDIS | ✅ | ⏳ | heredado | |
| USB host, HID y almacenamiento | ✅ | ✅ | confirmado | Con y sin alimentación externa |
| DisplayPort USB-C | ✅ | ✅ | confirmado | Salida de vídeo confirmada por la usuaria |
| Ethernet RTL8153 | 🟡 | ⏳ | heredado | Enumera y carga firmware; falta enlace y tráfico reales |
| UAS | ❓ | ❓ | supuesto | Nunca probado: no hubo unidad con interfaz UAS |
| Luz ambiental STK31610 | ❌ | ❌ | medido | El SSC lo descubre, acepta el `enable` y nunca manda la respuesta de configuración, así que `ssc_sensor_light_open_sync()` no termina jamás. El driver `ssc-light` ya no se ofrece; vía agotada también en pmOS |
| Proximidad | — | — | — | El firmware SSC stock del X910 no instancia el sensor |
| S Pen: escritura (Wacom I²C 0x56) | ❌ | ✅ | confirmado | Driver propio: hover con distancia, presión 0–4095, inclinación ±63 y botón lateral. Enganche automático, ~440 Hz y rotación correcta en las cuatro orientaciones. La salida de rango se sintetiza también por silencio (timer de 250 ms): sin eso el controlador enmudecía al apartar el lápiz y `BTN_TOOL_PEN` se quedaba a 1 hasta el reinicio |
| S Pen: acoplamiento (detección de guardado) | ❌ | ❌ | **no empezado** | Sin detectar cuándo entra o sale del hueco. Vía prevista: un `power_supply`/switch en el kernel, sin userspace nuevo |
| S Pen: batería y carga | ❌ | ❌ | **no empezado** | El nivel del lápiz no se lee ni se expone. Vía prevista: `power_supply` → UPower, que GNOME ya muestra junto al resto de baterías sin interfaz propia |
| S Pen: emparejamiento BLE | ❌ | ❌ | **no empezado** | El lápiz no está emparejado ni se ha visto anunciarse. El escaneo BLE del adaptador sí funciona (unos 30 dispositivos del entorno), pero no se ha probado con el lápiz en modo emparejamiento, así que su ausencia no prueba nada todavía |
| S Pen: gestos | ❌ | ❌ | **no empezado** | Depende del anterior y de destripar el perfil GATT de Samsung. Medido en esta sesión: GNOME no puede cubrirlo: las acciones de botón de stylus son sólo `default, middle, right, back, forward`, y el `keybinding` que permitiría «gesto → acción» existe únicamente para botones de *pad*. Requiere demonio propio (uinput), esquema GSettings propio y app propia |
| Táctil: zona que sólo responde al lápiz | — | ❌ | **abierto** | Intermitente. Una región deja de aceptar toques nuevos con el dedo; un arrastre iniciado fuera sí la atraviesa. La marca de proximidad pegada del S Pen se descartó como explicación suficiente: con el flag clavado y verificado, no había zona muerta. Sin diagnosticar; `work/catch-dead-zone.sh` decide si los toques llegan al kernel |
| Teclado pogo EF-DX920 (STM32 I²C 0x2a) | ❌ | ✅ | confirmado | Requiere V37 en el MCU: con V34 la aplicación pulsa CONN y no anuncia el protocolo. Reprogramado a V37, teclea desde arranque en frío y sobrevive a desconectar y reconectar la funda. Desde v0.16 la restauración es automática en el primer arranque |
| Huella (EgisTec EL7xx, SPI) | ❌ | ❌ | supuesto | Sin driver mainline |
| Vibración / hápticos | ❌ | ❌ | supuesto | Hardware sin identificar |
| Flash / linterna | ❌ | ✅ | observado | PM8550 SID 1, canales 0+1 agrupados por `leds-qcom-flash`; iluminación real observada en modo estrobo y linterna. El mosaico **Linterna** de ajustes rápidos está instalado, activo y probado físicamente |
| Cámaras | ❌ | 🟡 | observado | Los cuatro sensores hacen fotos y pasan por `libcamera` simple + software ISP, apareciendo como exactamente cuatro cámaras V4L2 normales y nombradas. GNOME Cámara, Chrome WebRTC y OBS abrieron y alternaron las cuatro con vídeo cambiante, también después de un arranque en frío; la trasera principal enfoca con su DW9808. El relevo entre sensores queda cerrado. Siguen abiertos la calibración de fábrica y el flash fotográfico automático |
| Módem | — | — | — | No aplica al modelo Wi-Fi |

### Cámaras y flash: alcance exacto de la validación

La enumeración no se tomó como prueba. Se configuró cada enlace físico por
separado hacia `msm_csid0` → `msm_vfe0_rdi0` → `/dev/video0` y se guardó un
fotograma completo. La relación observada es:

| objetivo | sensor / subdispositivo | CSIPHY | formato capturado |
|---|---|---|---|
| trasera principal | HI1337 `1-0021`, `/dev/v4l-subdev32` | `msm_csiphy1` | 4128×3096 RAW10, 16.000.128 bytes |
| trasera angular | HI847 `0-0021`, `/dev/v4l-subdev34` | `msm_csiphy2` | 3264×2448 RAW10, 9.987.840 bytes |
| frontal principal | HI1337 `3-0020`, `/dev/v4l-subdev31` | `msm_csiphy4` | 3408×2556 RAW10, 10.919.232 bytes |
| frontal angular | HI1337 `9-0021`, `/dev/v4l-subdev30` | `msm_csiphy5` | 4000×3000 RAW10, 15.024.000 bytes |

`/dev/video0` es el nodo de captura común: no identifica por sí solo una lente;
el sensor se elige cambiando los enlaces y formatos del grafo de medios. Sobre
esa capa se empaqueta `libcamera` 0.7.2 con el pipeline `simple`, software ISP y
ayudantes de ganancia HI1337/HI847. El tuning aplica pedestal RAW10, AE, AWB de
mundo gris y una matriz de color conservadora. Tras 150 frames de convergencia,
las cuatro salidas RGB mostraron exposición útil y blancos/grises sin la
dominante magenta de la conversión inicial:

- [frontal angular](../work/resultado-frontal-angular.jpg);
- [frontal principal](../work/resultado-frontal-principal.jpg);
- [trasera principal](../work/resultado-trasera-principal.jpg);
- [trasera angular](../work/resultado-trasera-angular.jpg).

El escalado del ISP conserva ahora el rectángulo completo del sensor: usa
ajuste *contain* centrado y relleno negro si la relación solicitada no coincide,
en vez de recortar los laterales para llenar la salida. La interfaz V4L2 base es
1280×960 (4:3); un cliente que pida 16:9 puede aplicar después su propio
`crop-and-scale`. La trasera principal sigue teniendo un campo óptico
naturalmente más estrecho que las ultra gran angular.

La trasera principal enlaza el actuador DW9808 `2-000c` como lente del HI1337.
El driver expone `focus_absolute` 0–1023 y la IPA software hace un barrido de
contraste grueso y otro fino antes de mantener la mejor posición. Con la luz
continua, el texto del billete quedó legible tanto en GNOME Cámara como en OBS.

`/dev/udmabuf` se entrega a `video` mediante udev. PipeWire conserva las cuatro
fuentes libcamera y cuatro procesos `v4l2-relayd` las conectan bajo demanda con
`/dev/video20`–`23`, creados por un `v4l2loopback` parcheado, firmado y compilado
contra el kernel exacto. Las cámaras se llaman `GTS9U-Front-Ultra-Wide`,
`GTS9U-Front-Main`, `GTS9U-Rear-Main` y `GTS9U-Rear-Ultra-Wide`; no requieren
escenas ni configuración por usuario.

Los cuatro sensores comparten CAMSS/ISP, por lo que los relés serializan sus
entradas. Si una aplicación abre la cámara nueva antes de cerrar la anterior,
el relé nuevo pide la preempción del dueño actual y espera a que libcamera haya
soltado CAMSS. Los enlaces de medios se reinician antes de cada configuración y
la cola de salida de `v4l2loopback` sobrevive a la negociación del consumidor.
El propietario del bloqueo se reescribe desde el offset cero: sin ese detalle,
el fichero acumulaba huecos NUL y el siguiente relé no podía descubrir a quién
señalar, dejando una imagen negra o estática.

Chrome enumeró sólo esas cuatro cámaras y abrió cada una a 1280×720 mediante
WebRTC. Tres rondas seguidas exigieron más de un segundo de tiempo multimedia y
cambio de píxeles entre muestras separadas dos segundos; las doce aperturas
pasaron. Tras otro arranque en frío, el primer consumidor repitió 4/4 con
2,030–2,034 s y 98,76–100 % de píxeles cambiantes en la escena disponible. El
selector V4L2 estándar de un perfil OBS completamente vacío mostró las mismas
cuatro y capturó cada `/dev/video20`–`23`. Dos capturas separadas tres segundos
por cámara cambiaron entre 20,04 % y 31,12 % de los píxeles del preview, por lo
que no eran imágenes cacheadas. El complemento empaquetado oculta únicamente
los endpoints RAW internos `Qualcomm Camera Subsystem` y corrige el caso en que
no existen los directorios `by-id`/`by-path`, que antes terminaba en `SIGSEGV`.

Discord en Chrome enumera también los cuatro identificadores V4L2 correctos.
Su selector de previsualización observado conserva internamente el stream
predeterminado `/dev/video20` aunque la etiqueta cambie a una trasera; el mismo
Chrome abre inmediatamente esas traseras por su `deviceId` exacto en WebRTC.
Esto queda documentado como comportamiento de esa interfaz de Discord, no como
un alias o una cámara ausente del sistema; no se instala ningún userscript ni
configuración por perfil para maquillarlo.

Los arranques reales terminan con cuatro nodos, cuatro relés y las cuatro
fuentes PipeWire utilizables antes de iniciar sesión gráfica. La cuenta creada
por la persona propietaria conserva su gestor systemd mediante *linger*; su
nombre y UID se resuelven en cada arranque y se escriben en un drop-in bajo
`/run`, nunca en la unidad empaquetada. El servicio vigila el PID real de
PipeWire: si éste cambia, destruye y recrea el conjunto completo de relés en vez
de dejar nodos V4L2 activos que sólo entregan negro.

Las capturas posteriores al reinicio mostraron canales equilibrados en las dos
frontales y una dominante verde moderada en superficies neutras iluminadas por
el flash trasero. La escena trasera estaba dominada por objetos rojos y marrones,
por lo que el AWB de mundo gris puede sesgarse; no se aplicó una matriz global
que habría degradado otras luces. La calibración de fábrica sigue abierta hasta
medir una carta neutra y de color bajo varias iluminaciones controladas.

El flash se verificó en sus dos rutas de hardware. El estrobo se armó mediante
la clase V4L2 flash y disparó durante una captura; la linterna mantuvo los dos
canales encendidos durante otra. Las dos imágenes muestran reflejos e
iluminación que no aparecen en la captura sin luz.

Para uso diario, GNOME carga la extensión de sistema
`flashlight@ubuntu-gts9u` y muestra **Linterna** en los ajustes rápidos
(`Super+S`). El mosaico usa luz continua al nivel conservador 128/255, refleja
el estado real del LED y lo apaga al deshabilitarse. También queda disponible
`gts9u-flashlight on|off|toggle|status`; no necesita `sudo`. Udev concede al
grupo `video` escritura únicamente sobre `brightness`: estrobo, timeout y
fallos siguen siendo controles de `root`. Un hook de suspensión fuerza nivel
cero para que el LED no quede encendido dentro de una funda.

Tras reiniciar por un atasco de la sesión multimedia, se repitieron 120 frames
de vídeo RAW, 60 frames VP9 codificados/decodificados y 30 frames de cada una
de las cuatro fuentes PipeWire. Las validaciones posteriores con GNOME Cámara
y OBS confirmaron orientación en las cuatro: monitor derecho en las frontales
y billete derecho en ambas traseras. La principal mostró además detalle a
corta distancia después de converger el autofoco.

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

### Soporte medido: funda con teclado EF-DX920

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
desbloqueó las pulsaciones: `evtest` midió presiones y liberaciones reales.

Ese primer éxito a 400 kHz no sobrevivió al reinicio siguiente: bajo escritura
aparecieron decenas de GPIO62, NACK `-6`, timeouts y recreaciones de `event3`.
Forzar el runtime PM de SE15 a `on` no cambió el patrón, por lo que autosuspend
quedó descartado. La diferencia temporal mostró transacciones/reintentos de
~230–250 ms en el arranque malo. Reducir únicamente `clock-frequency` de SE15
a 100 kHz eliminó la tormenta en reposo durante tres arranques consecutivos y
tras un rebind del driver, pero no sobrevivió a escritura sostenida: la dueña
volvió a observar teclas pegadas y el journal acumuló `-110`, NACK, resets y
pulsos GPIO62. La frecuencia queda como mejora de reposo, no como causa raíz.

Mover la lectura lógica de GPIO75 desde el hilo al hard-IRQ sí produjo una
ventana estable importante: 2.046 transiciones durante más de ocho horas,
`keys_down=0` y reconexión física correcta. Un primer reinicio recibió otras 61
transiciones. Sin embargo, el reinicio siguiente volvió a dejar teclas pegadas
y a detener el input con el mismo `boot`, `vendor_boot` y frecuencia DT. Por
tanto esa prueba no demuestra una causa raíz definitiva: cambia el estado frío
del STM32/teclado o la fase temporal del transporte, no las imágenes.

La investigación posterior cambió la conclusión. Un volcado completo y
estrictamente de solo lectura de los 64 KiB del STM32 dio SHA-256
`8937281d2efa08400390f9a2b02e40ca914b634e646d6dd544980c38464533ef`, contiene
`00 34 00 34` en `0x200` y no contiene ninguna copia V37. Es una imagen ARM
coherente y sus cadenas identifican explícitamente `TabS9(STM32G0) Series ->
V34`; por tanto V34 no es una lectura marginal ni prueba de corrupción.

De ahí se dedujo que One UI usaba V34 y que el hueco estaba en nuestra
inicialización fría. **Era un salto**: que la imagen sea válida no dice quién la
puso. El único blob del proyecto —el oficial del X910, el mismo que empaqueta
pmOS— es V37, y fue el que la sesión 8 programó para obtener las primeras
pulsaciones reales. El MCU había vuelto a V34 por su cuenta.

Reprogramarlo a V37 con el actualizador del propio driver restauró el teclado en
el acto y sobrevivió a un arranque en frío: `0xd6` a los 4,5 s, inicialización de
aplicación a los 7,6 s, escritura real de la dueña y reconexión física correcta
de la funda. Sigue sin medirse **qué** devolvió el MCU a V34; lo más probable es
el `stm32_pogo_v3.ko` de Samsung bajo One UI o Ubuntu Touch, así que arrancar
esos sistemas puede volver a degradarlo. La recuperación es de un comando:

```
sudo env GTS9U_ALLOW_POGO_FLASH=YES \
  /usr/libexec/ubuntu-gts9u-pogo-firmware-update
```

También se probó, sin escribir flash, el comando ROM `GO 0x08000000`, primero
solo y después con VDDO/MAX77816 activos y 100 ms de estabilización. El
bootloader aceptó ambos saltos, pero la aplicación siguió sin levantar DATA ni
anunciar `0xd6`; GPIO62 continuó pulsando cada ~2,126 s. Eso era la aplicación
V34, que el driver mainline no sabe hablar. La fuente final volvió exactamente
al driver del último estado conocido bueno (`504ff29`). Las escrituras
automáticas del accesorio siguen bloqueadas: exigen la guarda explícita
`GTS9U_ALLOW_POGO_FLASH=YES` y el servicio queda enmascarado, de modo que
ninguna programación del MCU ocurre durante el arranque.

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
