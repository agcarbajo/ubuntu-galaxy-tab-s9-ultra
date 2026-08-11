# Notas de desarrollo

Conclusiones duraderas del port Ubuntu y la lista de cosas que **no hay que
repetir**. El historial cronológico está en
[`porting-log.md`](porting-log.md); el estado vigente, en
[`hardware-status.md`](hardware-status.md).

Este documento arranca heredando el conocimiento del port postmarketOS. Las
entradas marcadas **[pmOS]** provienen de allí y ya están pagadas con tiempo de
depuración: repetir esos experimentos es tiempo perdido.

## Objetivo y alcance

Un Ubuntu 24.04 LTS arm64 de escritorio sobre el mismo kernel mainline y el
mismo hardware validado por postmarketOS v1.71. La raíz vivió en microSD hasta
v0.17 y desde v0.18 vive en la UFS interna. A largo plazo, compatibilidad con
software de escritorio ARM64 y, después, Vulkan/Turnip, FEX, Box64 y
Proton/Steam **evaluados por separado y con evidencia**. Steam no es requisito
para aceptar el primer Ubuntu funcional.

El repositorio postmarketOS es una referencia estable y de solo lectura. El
port Ubuntu no se introduce en él.

## Decisiones de arquitectura

- **Kernel congelado en el primer hito.** Se reutiliza 7.2-rc3 y el DTS
  probados. Un cambio de distribución y un salto de kernel a la vez impide
  atribuir regresiones.
- **Userspace nativo primero.** GDM3, Mutter, PipeWire y systemd de Ubuntu se
  prueban tal cual. Solo se porta un parche de pmOS cuando reaparezca la
  regresión concreta que ese parche resolvía, y con la evidencia documentada.
- **mmdebstrap y no una instalación manual.** Todo cambio definitivo vive en el
  repositorio como configuración, paquete, driver, parche o script. No se
  aceptan arreglos aplicados solo a la instalación viva.
- **Etiquetas de partición nuevas** (`UBTS9U_BOOT`/`UBTS9U_ROOT`) para que un
  initramfs de postmarketOS y otro de Ubuntu no compitan por la misma tarjeta.

## Entorno de trabajo

- Base de build Ubuntu: `wsl.exe -d Ubuntu-24.04 -u root`, directorio
  `/root/ubuntu-gts9u`. La base pmOS es `/root/pmos-gts9u` y no se mezcla.
- La distribución WSL llamada simplemente `Ubuntu` es otro entorno y **no**
  contiene el toolchain correcto.
- Las builds pesadas se ejecutan en filesystem Linux y en una ruta sin
  espacios. Las fuentes versionadas pueden vivir en la carpeta Windows.
- **[pmOS]** No pasar Bash complejo en línea a través de PowerShell: el quoting
  se deforma. Escribir el script en `work/` y ejecutarlo como fichero.
- La misma regla vale para Git Bash, y de forma más traicionera: al invocar
  `wsl.exe ... bash -lc '...'` desde Git Bash, **las variables de shell dentro
  del script en línea se pierden**. Un bucle
  `for f in a b c; do echo "$f"; done` imprime líneas vacías, de modo que una
  comprobación de dependencias llegó a informar «OK» de herramientas que no
  estaban instaladas. No es un fallo ruidoso: **miente en silencio**. Cualquier
  comprobación que decida algo debe ir en un fichero de script.
- **[pmOS]** No usar `Set-Content`/`Out-File` de PowerShell para scripts Bash:
  escriben CRLF o BOM y `set -euo pipefail` falla con `invalid option name`.
  Usar la herramienta Write (LF) o `dos2unix`.
- Con Git Bash en Windows, `wsl.exe` sufre conversión de rutas MSYS; exportar
  `MSYS_NO_PATHCONV=1` antes de invocarlo.

## Trampas del empaquetado ya conocidas

- **[pmOS]** El ramdisk genérico de `init_boot` debe ser **LZ4 legacy**, no
  gzip. Con gzip, ABL produce un initrd que Linux rechaza por «invalid magic at
  start of compressed archive» aunque la imagen Android sea válida.
- **[pmOS]** `APPEND_DTB_TO_KERNEL=1` y `DISABLE_RUNTIME_DTBO=1` son los únicos
  valores seguros. Los contrarios devuelven a ABL a su fork `ufdt`, que rechaza
  el DTB base y entra en Odin.
- **[pmOS]** El overlay temprano va en `/usr/lib/firmware/...`. En el
  initramfs `lib` es un symlink a `usr/lib`; crear un directorio `/lib` encima
  provocó un reset antes de journald (v0.69 de pmOS).
- **[pmOS]** `unzip -p > destino` no aplica los bits POSIX del ZIP, y systemd
  ignora un fichero regular dentro de un directorio `.wants`: hace falta un
  symlink real. El manifiesto debe transportar el modo.
- **[pmOS]** Los salts AVB aleatorios y los timestamps del CPIO rompían la
  reproducibilidad. Los salts derivan del SHA-256 de la imagen y el ZIP usa
  época fija para todos sus miembros.
- **Reproducibilidad del fragmento vendor (hallazgo 2026-07-31).** `cpio
  --reproducible` normaliza device e inode pero **no** el `mtime`. Como el
  overlay del initramfs se copia con `install`, cada build sella la hora
  actual y `vendor_boot.img` cambia de hash aunque su contenido sea idéntico.
  Al regenerar el ZIP v1.71 de rollback, `boot`, `init_boot`, `dtbo` y `vbmeta`
  salieron byte a byte iguales y solo `vendor_boot` difirió por esta causa. El
  pipeline Ubuntu debe fijar `mtime` a 0 en todo el árbol del overlay antes de
  empaquetarlo.
- **`sgdisk` puede bloquearse en WSL 2 al crear un archivo de imagen.** Con el
  kernel WSL `6.6.87.2`, `sgdisk --zap-all` llega a escribir los sectores y se
  queda indefinidamente en su llamada global `sync(2)` (`super_lock`), incluso
  sobre un fichero nuevo de 16 MiB. `build-sd-image.sh` usa `sfdisk` sobre el
  archivo recién recreado y conserva el mismo layout GPT. La regla de ejecutar
  `sgdisk --zap-all` antes de escribir una **microSD física** no cambia.

## Hallazgos propios de este port

- **El kernel validado y el kernel del paquete Alpine no son el mismo.** En el
  port de referencia, la build directa —la que produjo el `boot.img` que se
  flasheó y se validó físicamente— aplica 17 parches pero **no**
  `ignore-console-null.patch`. El APKBUILD hace lo contrario: aplica ese parche
  y en cambio **omite** `set-mi2s-codec-dai-format.patch`, el que hace sonar los
  CS35L45. Como el kernel que arranca es el de la build directa, el audio
  funciona; pero copiar la lista de parches del APKBUILD habría producido un
  kernel distinto del validado. Este port reproduce el conjunto de la build
  directa y deja el parche de consola tras
  `APPLY_IGNORE_CONSOLE_NULL=1`.
- **Fin de línea en ficheros sin extensión.** El instalador TWRP y los scripts
  de `packaging/` no tienen extensión, así que una regla `.gitattributes` por
  extensión no los cubre. Con CRLF, `#!/sbin/sh` simplemente no ejecuta. El
  repositorio fuerza `eol=lf` para todo.
- **Una comprobación negativa pasa con la entrada vacía.** Un `grep` que
  verifica que algo *no* aparece devuelve «correcto» cuando no puede leer nada.
  Al faltar `unzip`, el validador certificó como seguro un instalador que ni
  siquiera había abierto. Toda comprobación debe confirmar primero que pudo leer
  su entrada, y una herramienta ausente tiene que abortar, no degradar.
- **No identificar un fichero por su prosa.** El validador reconocía al
  instalador por una frase de sus comentarios y hacía `grep` de particiones
  prohibidas sobre el fichero entero, marcando como peligrosa justo la
  documentación que lo hace seguro. Se usa una línea de contrato explícita y se
  analiza el código con los comentarios eliminados.
- **`initramfs-tools` omite en silencio un hook no ejecutable.** No falla ni
  avisa. El empaquetado del `.deb` fuerza el bit.
- **En este entorno no hay udev.** `losetup --partscan` no garantiza que
  aparezcan `/dev/loopNpM`; hay que esperar y tener `kpartx` como alternativa.
- **`MODULES=dep` en `initramfs-tools` inspecciona el host de build**, no el
  destino, y falla con «failed to determine device for /». Para construir
  imágenes hay que usar `most` o una lista explícita.

## Bluetooth en Ubuntu: dos trampas de `btmgmt`

Ambas medidas en este dispositivo con BlueZ 5.72, y ambas derrotaron en
silencio a versiones anteriores del servicio.

1. **`btmgmt` es inservible con stdin en `/dev/null`**, que es exactamente lo
   que systemd da a un servicio por defecto. No falla: **sale con código 0 y no
   imprime nada**. Un `grep` sobre su salida no casa nunca y quien lo llama
   concluye que el controlador no está. Con una tubería vacía —`printf '' |
   btmgmt ...`— se comporta con normalidad; un pty vía `script(1)` también.
2. **Ejecutado antes de `bluetoothd` se bloquea en `epoll_wait` durante
   minutos.** El servicio, ordenado `Before=bluetooth.service`, se llevó por
   delante toda la pila: 90 s de timeout en cada arranque y el controlador sin
   configurar. Con el demonio ya arriba la misma llamada tarda 0 s.

De ahí que este port ordene el servicio **después** de `bluetooth.service`, al
revés que el port de referencia. Aplicar la dirección tarde no cuesta nada: un
controlador sin dirección es inutilizable de todos modos, y `bluetoothd` lo
adopta acto seguido sin reiniciarse.

Para comprobar si la dirección ya está puesta se usa `hciconfig`, que es un
ioctl, responde en ~3 ms y no puede bloquearse.

## Un símbolo en `=m` está ausente, no degradado

Este port no instala árbol de módulos: solo los dos ath12k firmados. Por tanto
**cualquier `CONFIG_*=m` equivale a que la función no existe**. Es la causa
única de tres fallos que parecían no tener relación:

| Símbolo | Síntoma visible |
|---|---|
| `SQUASHFS=m` | `apt install firefox` y `chromium` fallan: en Ubuntu son paquetes de transición que instalan un snap, y un snap es una imagen squashfs |
| `BINFMT_MISC=m` | `systemd-binfmt.service` y `proc-sys-fs-binfmt_misc.mount` fallan en cada arranque y el sistema queda `degraded` |
| `OVERLAY_FS=m`, `FUSE_FS=m` | snapd no puede superponer datos escribibles sobre el snap |

Antes de dar por buena una función de escritorio, comprobar que sus símbolos
son `=y`, no `=m`.

## No confiar en `Recommends` para nada que importe

El rootfs v0.5 salió sin `snapd` porque se dejó a que
`ubuntu-desktop-minimal` lo recomendara. Lo que importa se declara explícito.

## Un driver compilado no es un driver ofrecido

`iio-sensor-proxy` trae cuatro drivers SSC compilados, pero cada uno solo mira
dispositivos que udev haya etiquetado con su nombre en `IIO_SENSOR_PROXY_TYPE`.
La regla `80-iio-sensor-proxy.rules` de upstream etiqueta el nodo FastRPC con
`ssc-light ssc-compass` y nada más, de modo que `drv-ssc-accel` jamás recibe un
dispositivo aunque esté enlazado en el binario. El síntoma es desconcertante:
`ssccli` lee el acelerómetro perfectamente y el daemon dice `No accelerometer`.

Cuando una capacidad existe en el código pero el sistema no la ve, mirar
primero el mecanismo de descubrimiento, no la implementación.

## Reiniciar el ADSP en caliente deja el sistema sin sonido

`echo stop/start > /sys/class/remoteproc/remoteproc0/state` con el sistema
arrancado destruye la tarjeta ALSA y los servicios de audio no se vuelven a
registrar solos. Se recupera reiniciando el sistema. Útil para depurar
sensores, pero hay que contarlo antes de dejar la tablet en manos de nadie.

## El primer cliente SSC puede dejar afirmado el handover del ADSP

En Ubuntu, la primera consulta `ssccli` seguida del primer
`iio-sensor-proxy` puede dejar el IRQ `q6v5 handover` disparándose unas cuatro
veces por segundo. El proxy consume casi un núcleo, el hilo
`irq/16-smp2p-adsp` otro, y coinciden timeouts DPU y GENI I2C. Reiniciar todo el
ADSP no es aceptable porque destruye audio; sustituir únicamente el cliente
`iio-sensor-proxy` después de que SSC responda elimina la tormenta.

La recuperación debe ejecutarse `After=display-manager.service`: GNOME es quien
abre realmente el acelerómetro. Si la unidad lleva `Before=display-manager`, la
ventana de salud termina antes de que aparezca el fallo y produce un falso
positivo. El helper mide el contador `q6v5 handover` cada dos segundos durante
30 segundos, refresca el proxy una vez solo si crece más de dos veces, y vuelve
a vigilar el segundo cliente. En el arranque validado el primer cliente produjo
3 IRQ en 2 s; el segundo terminó con incremento 0, 45 ms de CPU y autorrotación
activa.

Esta tormenta agrava la contención global, pero **no explica por sí sola toda la
historia del teclado**: el boot que mantuvo 2.046 transiciones durante ocho
horas también acumuló handovers. No convertir esa correlación en una causa raíz
del transporte pogo sin la prueba física final.

## La espera síncrona de libssc no era una espera, era un bucle

`ssc_common_wait_sync_context()` en libssc 0.4.4 gira el contexto GLib por
defecto con `g_main_context_iteration (..., FALSE)`. Con `may_block` a `FALSE`
GLib fuerza el timeout del poll a cero, así que eso no espera: itera tan
rápido como dé la CPU. Cualquier petición que el SSC no conteste **clava un
núcleo entero durante toda la vida del proceso**.

En el X910 el que no contestaba era el sensor de luz. Con el driver
`ssc-light` todavía ofrecido, GNOME llamaba a `ClaimLight` y
`iio-sensor-proxy` se quedaba dentro de `ssc_sensor_light_open_sync()` para
siempre:

```
#3 ssc_common_wait_sync_context (ctx=…) at ../src/libssc-common.c:56
#4 ssc_sensor_light_open_sync (…)      at ../src/libssc-sensor-light.c:225
#5 ssc_light_set_polling (…)           at ../src/drv-ssc-light.c:94
#6 handle_method_call (… method_name="ClaimLight" …)
```

Coste medido, tablet en reposo: 199 ticks/2 s (un núcleo al 100 %) desde el
arranque, ~35.000 vueltas por segundo, 106.941 `ppoll` en tres segundos —
99,64 % del tiempo de proceso— todas con `{tv_sec=0, tv_nsec=0}` y todas
devolviendo `0 (Timeout)`, **94,7 °C** en la zona térmica más caliente y la
corriente de carga hundida.

Lo desconcertante era que **el demonio que giraba funcionaba**: la
autorrotación iba bien mientras quemaba el núcleo. Ahora se entiende: como el
bucle itera el contexto principal, D-Bus y el flujo del acelerómetro se
despachaban desde dentro de la espera. Y por eso matarlo tampoco servía —
reiniciarlo pierde el sensor hasta que vuelve la sesión, y la instancia nueva
gira igual.

El arreglo es bloquear en `poll()` (`packaging/sensors/fix-ssc-sync-wait-busy-loop.patch`).
No cambia el comportamiento: la callback que termina la espera se despacha
desde ese mismo contexto, así que lo que despierta el poll es justo lo que
acaba la espera, y las demás fuentes se siguen despachando igual. Sólo el hilo
que conduce el contexto puede bloquearse en él, de ahí el
`g_main_context_acquire()` y el respaldo sobre la `GCond` que la callback ya
señalaba.

Con eso, y con `ssc-light` fuera de la tabla de drivers
(`disable-broken-ssc-light.patch`), el mismo arranque da **1 tick/2 s** y
48,9 °C con la autorrotación intacta.

Dos lecciones más allá de este fallo:

- **Un `ppoll` con timeout cero que devuelve `Timeout` siempre no es un
  `GSource` mal armado**: es alguien iterando el contexto sin bloquear. La
  firma apunta al llamante, no al bucle de eventos.
- **La pila de sensores la compilamos nosotros**, así que un bucle así se
  corrige donde está. Domesticar el proceso desde fuera —`renice`, cgroups,
  reinicios vigilados— sólo esconde el consumo, y en este caso además rompía
  la rotación.

## El digitalizador no anuncia que se va: enmudece

`samsung_wacom_w90xx` sintetiza la salida de rango contando frames válidos con
el bit `IN_RANGE` apagado, tres seguidos. Eso cubre el caso en que el
controlador sigue hablando, pero no el otro: **cuando apartas el lápiz, el
controlador puede callarse sin más**. Medido: 0 interrupciones en 5 s con
`BTN_TOOL_PEN` todavía a 1 y `ABS_DISTANCE` congelado. El último frame válido
traía distancia 235 de 255 — el lápiz al borde mismo del rango— y ahí se acabó
la conversación.

Sin timeout, `in_range` se queda a `true` **hasta el siguiente reinicio**.

Importa más de lo que parece porque libinput agrupa este digitalizador con el
táctil Goodix: `udevadm info /dev/input/event4` muestra
`LIBINPUT_DEVICE_GROUP=18/0/0:input/ts`, y ese `18/0/0` son el bus y los IDs
**del lápiz**, no del Goodix. Con una herramienta que cree en proximidad,
libinput arbitra el táctil.

El arreglo es un `timer_list` de 250 ms que trata el silencio como una marcha
(el contador de frames se queda como camino rápido). Los informes en reposo
llegan cada 25 ms, así que son diez frames perdidos: demasiado para dispararse
con el lápiz presente, poco para notarlo cuando no está. `exc3000.c` en
mainline hace exactamente esto por el mismo motivo.

Verificado en hardware tras flashear: el flag sube a 1 al dibujar, y vuelve a 0
solo al apartar el lápiz, y se queda a 0 durante 90 s de muestreo continuo.

**Cuidado con la conclusión fácil, que casi la doy por buena.** Todo esto
explicaba tan bien el síntoma que la dueña reportaba —una zona de la pantalla
que responde al lápiz y no al dedo, salvo arrastrando desde fuera, que es
exactamente cómo se comporta el rectángulo de arbitraje— que estuve a punto de
darlo por causa. No lo es, o no basta: con el flag clavado y comprobado clavado,
ella no encontró ninguna zona muerta. La marca de proximidad pegada es un
defecto real y está corregido; **el fallo del táctil sigue abierto**.

Para el próximo episodio, la pregunta que lo parte en dos está en
`work/catch-dead-zone.sh`: si los toques en la zona muerta llegan al kernel, el
que los descarta es userspace; si no llegan, es el Goodix y el lápiz no pinta
nada. La herramienta está validada contra un toque real, para que un «0
contactos» signifique algo.

## La carga no la limitaba el lazo, la limitaba lo que pedíamos en el contrato

Durante dos sesiones se buscó el techo de carga en el sitio equivocado. El
comentario de `SM5440_TARGET_IBUS_MA` decía que 3200 había hundido el bus y que
2200 era «prudencia, no un límite medido», así que lo natural era volver a
subir ese objetivo. **No sirve de nada**, y ahora se sabe por qué.

Con `TARGET_IBUS_MA` en 2200, 2600 y 2800, la `ibus` medida no se movía: 2587,
2596, 2600 mA. Y al forzarlo a 3400 la petición sí subió —`in0_input` llegó a
9860 mV, casi el techo— pero bajaron **a la vez** la tensión y la corriente,
que es la firma de una fuente plegándose, no de un lazo que no empuja.

El motivo estaba dos líneas más allá, en `sm5440_start()`:

```c
target_ma = min(target_ma, 3000);
```

La corriente del **contrato PPS** estaba fijada a 3000 mA. `dmesg` lo decía
desde el principio: `direct charge started: PPS 8760 mV/3000 mA`. La `ibus`
topaba en 2895 porque el adaptador estaba en límite de corriente, y el suelo
que el propio lazo pedía —unos 700 mV sobre `2×vbat`, que a 0,17 Ω son ~4,1 A—
ya quería más de lo que teníamos derecho a tomar.

TCPM no añadía ningún tope: `tcpm.c` recorta la petición contra lo que anuncia
la fuente (`min(src_ma, req_op_curr)`), y ésta anuncia 5 A.

Barrido en hardware, 41-44 % de carga, 20 s por escalón:

| contrato | pack | ibus | vbus | die |
|---|---|---|---|---|
| 3000 mA | 21,4 W | 2601 mA | 8556 mV | 45,5 °C |
| 3200 mA | 22,8 W | 2864 mA | 8611 mV | 46,5 °C |
| **3400 mA** | **25,0 W** | 2960 mA | 8652 mV | 48,5 °C |
| 3600 mA | 24,2 W | 3141 mA | 8801 mV | 54,0 °C |
| 3800 mA | 24,2 W | 3128 mA | 8780 mV | 55,0 °C |
| 4000 mA | 24,2 W | 3167 mA | 8835 mV | 55,0 °C |

Por encima de 3400 la corriente de entrada sigue subiendo y la potencia
entregada no: eso es pérdida en la bomba, y se paga en seis grados de die a
cambio de nada. 3400 aguantó **25,2-25,5 W durante cinco minutos** con el die
plano en 49,5 °C y el pack en 36,4 °C.

Tres cosas que llevarse:

- **Un lazo que no reacciona a su consigna está saturado en otro sitio.** La
  señal fue que `ibus` no se movía entre 2200 y 2800; eso ya decía que el
  objetivo no era el limitador, antes de tocar nada más.
- **Pedir más tensión contra una fuente en límite de corriente la pliega.** Es
  lo que se interpretó en su día como resistencia serie del cable. La caída
  entre lo pedido y lo medido *crece cuando baja la corriente*, que es justo lo
  contrario de lo que hace una resistencia — el propio driver ya lo advertía
  del ADC de `vbus`.
- **Diez minutos de compilación, no cuarenta.** Medido: `.config` a `boot.img`
  en 10 min 38 s, 5269 objetos en 16 núcleos. Aun así conviene exponer lo que
  se va a barrer como parámetro (`/sys/module/sm5440_direct/parameters/`): un
  escalón pasa de once minutos más un reinicio a dos segundos, y el reinicio
  además corta la carga y mueve las condiciones de la medida.

## Los gestos del S Pen no los puede cubrir GNOME, y Ajustes no admite paneles

Anotado antes de empezarlo, para no volver a investigarlo desde cero.

**Lo que GNOME ya da gratis.** Reconoce el lápiz y le guarda ajustes por
dispositivo: `dconf dump /org/gnome/desktop/peripherals/` muestra
`[stylus/default-056a:0000]` con `button-action` y `pressure-curve`, y
`[tablets/056a:0000]` con `area`. O sea que el panel «Wacom Tablet» funciona
con nuestro digitalizador sin tocar nada. Merece la pena definir un stylus real
en la entrada libwacom en vez de `@generic-no-eraser`, o el panel ofrece tres
botones para un lápiz que tiene uno.

**Dónde se acaba.** Las acciones que admite un botón de stylus son sólo
`default, middle, right, back, forward`. El valor `keybinding` —el único que
permitiría «gesto → acción arbitraria»— pertenece a
`GDesktopPadButtonAction`, que es para los botones del cuerpo de una tableta
Wacom, no para el lápiz. No hay forma de mapear un gesto desde GNOME.

**Ajustes no admite secciones de terceros.** Los paneles se registran en
`cc-panel-loader.c`, compilados dentro del binario; no hay directorio de
paneles externos ni API de plugins en 46.7. Añadir una sección exigiría
bifurcar `gnome-control-center` y recompilarlo en cada actualización de Ubuntu,
lo que además nos dejaría atrás en seguridad. Descartado para este port.

**Forma recomendada, si se retoma.** Demonio en la sesión (`systemd --user`)
que abra el GATT y escriba en `/dev/uinput`, esquema GSettings propio en el
paquete de dispositivo, y app GTK4/libadwaita aparte. En Wayland una aplicación
normal no puede sintetizar pulsaciones: uinput es la salida que no depende de
portales ni de consentimiento por sesión, y el acceso al nodo se resuelve con
una regla udev — el mismo patrón que ya usa `10-fastrpc.rules` para el usuario
`fastrpc`.

**Y el orden.** El botón lateral ya es visible como `BTN_STYLUS` en `event2`,
así que clic, doble clic y pulsación larga se pueden implementar **sin BLE**.
Esa porción valida el camino entero —demonio, uinput, GSettings, app— contra
hardware que ya funciona, antes de entrar en el GATT, que es la parte de coste
no acotable. La UI es el último 10 %, y la lista de gestos la dicta el
protocolo: diseñarla antes de conocerlo es inventarse la mitad.

## Lo que no hay que repetir

Heredado de postmarketOS; cada punto costó al menos una iteración física.

### Kernel y configuración

- **[pmOS]** No dejar en `=m` un proveedor crítico. Este port no autocarga un
  árbol general de módulos: un símbolo en `=m` normalmente hace que el
  subsistema no aparezca. `HID_GENERIC`, `INPUT_EVDEV`, `QCOM_FASTRPC`,
  `POWER_RESET_QCOM_PON` y los pinctrl LPASS-LPI deben ser built-in.
- **[pmOS]** `CONFIG_GPUCC_SM8550` no existe; el símbolo real es
  `CONFIG_SM_GPUCC_8550`. `DRM_MSM` no sube a `=y` con `QCOM_LLCC/OCMEM` en
  `=m`.
- **[pmOS]** `msm.separate_gpu_kms=1` en la cmdline es obligatorio para que
  Adreno cree su render node sin un component master del mdss.
- **[pmOS]** No reactivar `lpass_ag_noc`: provocó bloqueos y el audio funciona
  sin él.
- **[pmOS]** No añadir lecturas MMIO/ioremap improvisadas para diagnosticar
  probes, ni `dev_info` por evento en rutas de alta frecuencia como DWC3.

### Wi-Fi y Bluetooth

- **[pmOS]** No usar la BDF Samsung HMT.2.0 con el amss oficial HMT.1.1: crashea
  con MHI RDDM. La BDF QRD con envoltorio ELF es la definitiva, y no debe
  despojarse de ese envoltorio.
- **[pmOS]** El NVM Bluetooth genérico falla con `-52`; el válido es
  `hmtnv20.b21`. Su dirección es nula y hay que aplicar la de EFS montada
  `ro,noload`.

### Pantalla y sensores

- **[pmOS]** El panel necesita un ciclo `pm_test=platform` antes del display
  manager. `pm_test=devices` **no** lo recupera. No repetir `unbind`/`bind` de
  `msm_dsi`.
- **[pmOS]** No usar timers anónimos `systemd-run --on-active` para despertar el
  display ni para recuperar SSC: se retrasan entre 7 y 16 s y se solapan. Una
  sola unidad cancelable.
- **[pmOS]** La vía del ALS STK31610 está agotada: registry, rails, modos de
  streaming, petición Samsung exacta y comparación con `persist` no producen
  lux. No instanciarlo como `sensortek,stk3310` ni copiar la configuración del
  Xiaomi Pad 6. No habilitar los controladores I²C del AP para SE3/SE4: esos
  buses pertenecen al DSP.
- **[pmOS]** `ACCEL_MOUNT_MATRIX=0,1,0;-1,0,0;0,0,1` es una medida física
  validada; conservarla aunque los JSON stock sugieran otra cosa.

### USB, carga y DisplayPort

- **[pmOS]** No dar por resuelto el host USB porque TCPM publique un rol y xHCI
  cree sus root hubs. La prueba válida es enumeración downstream con `event*`
  o `hidraw*` reales.
- **[pmOS]** El MUIC del SM5714 debe encaminar D-/D+ **antes** del boost OTG.
- **[pmOS]** No forzar `CC_CNTL1=0x49/0x59` ni `CC_CNTL3=0x81` tras una conexión
  source/host natural: genera un `DETACH` inmediato.
- **[pmOS]** No resincronizar CC a 250 ms: TCPM sigue en `PORT_RESET_WAIT_OFF`.
  El valor validado es 1.500 ms.
- **[pmOS]** El hub `2d79:e001` declara `USB_COMM=false` sin alimentación
  externa; no seguir tocando VBUS, PTN3222 ni TCPM para ese caso, probar otro
  adaptador.
- **[pmOS]** El HPD DisplayPort de un dock presente al arrancar no puede activar
  el encoder antes del `pm_test=platform` del panel. Debe guardarse y
  reproducirse después de `PM_POST_SUSPEND`.

### Método

- **[pmOS]** No declarar un componente funcional porque su driver haya
  sondeado. Hace falta prueba real o confirmación física.
- **[pmOS]** No identificar un endpoint SSH solo por su IP: varios dispositivos
  comparten la subred USB `172.16.42.0/24`. Comparar la host key.
- **[pmOS]** No comparar solo configs y DTS entre builds: verificar también el
  release del kernel arrancado frente a `/lib/modules/`.
- **[pmOS]** No dejar montada la raíz de la microSD antes de flashear un ZIP con
  overlay.

## Seguridad

Reglas innegociables, idénticas a las del port postmarketOS:

- La usuaria flashea manualmente; las herramientas de build nunca escriben en la
  tablet ni en una tarjeta.
- Conservar TWRP, Download Mode y Odin.
- No tocar PIT, EFS, persist, modem/modemst ni calibraciones. EFS solo
  `ro,noload` cuando sea imprescindible.
- No reparticionar UFS ni `super` para el primer port Ubuntu.
- No publicar SSID, contraseñas, IPs, claves privadas, direcciones MAC/Bluetooth
  ni nombres personales en commits, logs o documentación.
- No publicar firmware propietario ni imágenes que lo contengan.

## Funda con teclado EF-DX920: cómo está cableada de verdad

Recuperado del DTBO original de Samsung (`port/firmware-extracted/ap/dtbo.img`,
entrada `board-id,00`, decompilada con `dtc`). La primera lectura del overlay
aislado confundió las propiedades GPIO de diagnóstico con el bus. La sección
`__fixups__` resuelve el padre sin ambigüedad:

```
qupv3_se15_i2c = "/fragment@70:target:0";
```

Por tanto `stm32@2a` vive en QUPv3 SE15, que mainline llama `i2c15`; su pinctrl
upstream ya asigna SDA/SCL a TLMM72/106.

### El teclado

```
stm32@2a {
        compatible = "stm,stm32_pogo";
        reg = <0x2a>;
        stm32,irq_gpio  = <&tlmm 75 0>;    /* datos listos */
        stm32,irq_conn  = <&tlmm 62 0>;    /* funda conectada */
        stm32,irq_type      = <0x2008>;
        stm32,irq_conn_type = <0x2003>;
        stm32,mcu_swclk = <&tlmm 12 0>;
        stm32,mcu_nrst  = <&tlmm 13 0>;
        stm32,sda_gpio  = <&tlmm 72 0>;
        stm32,scl_gpio  = <&tlmm 106 0>;
        stm32,fw_name   = "keyboard_stm/stm32_gts9family.bin";
        stm32,model_name = "EF-DX915","EF-DX910","EF-DX900","EF-DX925","EF-DX920";
        support_open_close;
};
```

Lo importante: **no se debe crear un segundo bus `i2c-gpio`**. `sda_gpio` y
`scl_gpio` repiten los pines del controlador GENI para diagnóstico y la ruta de
recuperación/bootloader del MCU. Un `i2c-gpio` sobre 72/106 competiría con SE15
por las mismas líneas.

Cuelgan de él dos nodos de función:

- `pogo_kpd`, `compatible = "stm,keypad"`, con la lista de nombres que incluye
  `Book Cover Keyboard Slim (EF-DX920)`;
- `pogo_touchpad`, `compatible = "stm,touchpad"`, con
  `touchpad,invert = <0 1 1>`.

Y un regulador de refuerzo aparte: `kbd_boost@18`, `max77816,kbd_boost`, en el
bus distinto `qupv3_hub_i2c4`. La lista `stm32,booster_power_models` contiene
`0xf9` y `0xd3`, mientras que EF-DX920 es `0xd6`, pero esa lista **solo**
selecciona el ajuste posterior de tensión. El driver Samsung llama siempre a
`kbd_max77816_control_init()` al encender VDDO cuando la lista no está vacía;
esa rutina activa la salida (`0x03 = 0x70`) y fija el límite a 3,1 A
(`0x02 = 0x8e`). Por tanto el MAX77816 no se puede omitir en EF-DX920.

`stm,stm32_pogo` no existe en mainline. Sí existe en la publicación de fuentes
de Samsung para el SM-X910, que es GPL, así que la vía realista es portarlo, no
reinventar el protocolo.

### Secuencia de conexión que exige el driver

La implementación stock no deja VDDO encendido desde `probe`. Solicita la IRQ
de conexión GPIO62 en ambos flancos y mantiene deshabilitada la IRQ de datos
GPIO75. Cuando GPIO62 sube, enciende VDDO, espera 50 ms, habilita GPIO75 y arma
el timeout de inicialización; cuando baja, deshabilita datos, libera el estado
y apaga VDDO. GPIO75 es activa baja y se solicita como nivel bajo + oneshot.

La v0.8 todavía no reproduce esta máquina de estados: mantiene VDDO encendido y
solo escucha el flanco de bajada de GPIO75. En la prueba física GPIO62 detectó
la conexión y reintentó aproximadamente cada dos segundos, pero GPIO75 quedó
siempre alto. El siguiente driver debe implementar las dos IRQ y habilitar
también el MAX77816 antes de esperar datos.

### Secuencia validada del STM32 en v0.9

El bootloader ROM está en `0x51`, responde con PID `0x0460` y permite leer el
flash aunque la aplicación `0x2a` esté muda. El X910 probado contenía
`00 34 00 34`; el blob oficial `stm32_gts9family.bin` es `00 37 00 37`, mide
52.132 bytes y tiene SHA-256
`1b48d88c23523ae205cd960e6d42725268638a15a47d8a5e52854eb01108caa3`.
Tras programarlo se comparó todo el rango byte a byte. Los option bytes
`aa fe ff fe` ya tienen borrado el bit 24 que comprueba Samsung.

La secuencia funcional es estricta: entrar en bootloader, validar/actualizar,
poner BOOT0 bajo, pulsar NRST y esperar 150 ms; después, al detectar GPIO62,
activar VDDO y MAX77816, esperar 50 ms y habilitar GPIO75. **No resetear el
STM32 después de activar VDDO**: ese reset extra mantiene muda la aplicación,
aunque firmware, option bytes y alimentación sean correctos. Sin él, el MCU
anuncia `0xd6` y crea el input EF-DX920.

El input no debe existir desde `probe`. Solo se registra tras el anuncio de
modelo y se destruye al desconectar; de lo contrario GNOME interpreta que hay
un teclado externo permanente y oculta la autorrotación. El valor inicial
`0x7fff` está fuera del rango Linux y se ignora. Una tecla mantenida desde antes
de alimentar la funda no genera una transición retrospectiva en `evtest`.

Después del anuncio de modelo, Samsung todavía ejecuta una inicialización de la
aplicación: versión MCU (`ID_MCU`, comando `0x02`), modo (`0x01`), espera de
200 ms, CRC (`0x03`) y versión del accesorio (`ID_TOUCHPAD`, `0x18`). En el
EF-DX920 real devuelve versión `04 01 05 01`, modo 1, CRC `cd 0b f7 cf` y
accesorio `09 00 ff 00 00 00`. La pareja `ff 00` es el caso stock sin
controlador táctil, normal para la funda Slim. Esta secuencia ya funciona y no
es la causa de que falten teclas.

La inicialización de aplicación no puede ejecutarse entera dentro de la IRQ de
datos. Samsung lee VERSION de inmediato, libera la IRQ y difiere 10 ms MODE,
la espera de 200 ms, CRC y accesorio. Mantener los 200 ms dentro del handler
deja GPIO75 afirmado y termina en `-ETIMEDOUT`. Con la división asíncrona,
`evtest` recibió presiones y liberaciones reales de letras, espacio y retroceso.

GPIO62 puede rebotar al teclear. Cortar VDDO durante una tecla hace que el STM32
olvide su liberación, por lo que Linux debe liberar todo `keys_down` antes de
apagarlo. Tras cada reanuncio `0xd6` se repite VERSION + inicialización aunque
el input ya exista. `0xff` es basura de bus durante un rebote y nunca debe
sustituir el modelo válido. Si se agotan los reintentos I²C y DATA queda
afirmada, se liberan las teclas y se pulsa NRST durante 3 ms, igual que hace el
driver Samsung en su ruta de error; sin esa recuperación la IRQ repetía un
timeout cada ~4,4 s para siempre.

Una traza conjunta de `i2c_transfer` e IRQ aclaró que esa recuperación estaba
tratando un síntoma creado por nuestra selección de IRQ. Con
`IRQF_TRIGGER_FALLING`, después de entregar varios paquetes válidos quedaba un
último handler con GPIO75 ya desactivado. El envío de la cabecera de sondeo
tenía éxito, pero la lectura de una cola vacía expiraba tras ~1 s; acto seguido
el STM32 pulsaba GPIO62 y empezaba el ciclo de alimentación. El stock comprueba
el nivel de GPIO75 al entrar en su ISR y retorna si ya está alto. Mainline debe
mantener el flanco descendente —el nivel bajo perdió pulsos cortos— y combinarlo
con esa guarda: si el descriptor activo-bajo devuelve 0, se contabiliza
`data_irq_deasserted` y no se toca I²C. En la primera prueba de seis minutos el
resultado fue un descarte, cero timeouts, cero pulsos GPIO62 y cero resets.

Esa ventana estable a 400 kHz no era reproducible tras reiniciar. En el arranque
siguiente las lecturas volvían a sufrir NACK `-6`, `-EPROTO`, timeouts GENI y
decenas de ciclos GPIO62; `event3` se destruía cuando el nivel permanecía bajo
más de 250 ms. Mantener `89c000.i2c/power/control=on` y reinicializar el cliente
no lo corrigió, así que no atribuirlo al autosuspend de 250 ms. El downstream
usa 400 kHz, pero su generador GENI y sus parches de temporización no son los de
mainline. En esta placa, 100 kHz dio tres arranques y un rebind consecutivos sin
timeouts ni resets en reposo, pero la escritura sostenida volvió a provocar
`-110`, NACK y GPIO62. Para un teclado la pérdida de ancho de banda es
irrelevante, pero 100 kHz no es por sí solo la solución.

La guarda de DATA tampoco puede ejecutarse por primera vez en el handler
threaded: un pulso corto válido puede haber regresado a alto aunque su paquete
siga en la cola, y descartarlo pierde sobre todo releases. Moverla al hard-IRQ
de TLMM produjo más de 2.000 transiciones físicas limpias y una reconexión, pero
esa estabilidad no sobrevivió al reinicio posterior con imágenes y DT
idénticos. No llamar definitiva a esa combinación ni atribuir la regresión a
que una partición haya cambiado.

El DT stock pide `IRQF_TRIGGER_LOW | IRQF_ONESHOT`; esa variante permite que el
controlador vuelva a disparar mientras queden varios paquetes con DATA bajo. El
GENI downstream usa en 100 kHz los contadores `{div=7, cycle=10, high=11,
low=26}`, frente a `high=12` de mainline, y en un timeout envía `M_CMD_CANCEL`
antes de recurrir a `M_CMD_ABORT`. Son diferencias reales del producto que se
están probando juntas, no resultados todavía validados.

El driver Samsung también emite su notifier RESET —que libera todas las
teclas— en **cada** intento de lectura fallido, no solo al agotar tres
reintentos. Replicar esa semántica evita conservar una pulsación durante varios
timeouts; el reset físico del STM32 permanece reservado para el agotamiento de
los reintentos. Esto es distinto de un watchdog por duración de tecla.

No usar un watchdog basado únicamente en el tiempo durante el que una tecla
permanece pulsada. Una tecla real puede mantenerse indefinidamente; el
temporizador experimental de 3 s la confundía con una liberación perdida y
reiniciaba un STM32 sano. Las liberaciones sintéticas se conservan en las rutas
objetivas de desconexión y error de transporte.

No consultar
`0x2a` con `i2ctransfer` mientras el driver está enlazado: compite con su
transacción de dos fases, provoca NACK/`-EPROTO` y puede forzar un falso ciclo
de desconexión. Un sondeo periódico dentro del driver sí llegó al sistema real,
pero el Wi-Fi no asoció hasta un reinicio y el journal demostró además
`i2c i2c-6: Transfer while suspended` desde el trabajo de sondeo. Se retiró: no
se debe reintroducir ninguna consulta periódica que pueda sobrevivir a la
suspensión. Un control `event_poll` manual, serializado y ejecutado solo a
petición mientras el sistema está despierto es una herramienta distinta.

La misma unidad física se probó después en One UI: las teclas funcionaron y el
cierre de la funda apagó la pantalla. Eso descarta un defecto de teclado,
contactos o cableado como explicación general del silencio bajo mainline.

El MAX77816 está en hub SE4 y ese SE debe usar GPI DMA. PIO reclama TLMM4/5 y
bloquea el probe del ADSP. Liberar SE4 en caliente no recuperó SSC, y un control
con v0.8 tampoco tuvo sensores en ese arranque: no atribuir esa intermitencia
preexistente al teclado sin una comparación A/B.

### El apagado al cerrar

El nodo `hall_ic` de Samsung tiene **dos** sensores de efecto Hall, y nuestro
DTS solo cablea el primero:

| | GPIO | evento Samsung | en nuestro DTS |
|---|---|---|---|
| `hall` | TLMM 107, activo bajo | `0x15` | sí, como `SW_LID` |
| `hall_wacom` | TLMM 203, activo bajo | `0x1e` | **no** |

Que la funda normal apague la pantalla y la del teclado no encaja con que cada
una accione un imán distinto. Antes de tocar el DTS hay que medirlo: leer TLMM
203 con la funda de teclado abierta y cerrada.

### Medido: los pines del conector pogo están muertos sin alimentar

Dos grabaciones de 280 s cada una, con la dueña accionando la funda EF-DX920:
cerrarla y abrirla tres veces, engancharla a los pines, teclear, desengancharla
y volver a cerrarla. TLMM 203 (`hall_wacom`), 62 (`irq_conn`) y 75 (`irq_gpio`)
**no cambiaron ni una vez**, ni con pull-up ni con pull-down, y `SW_LID` tampoco.

Leer los pines desde userspace no sirve para atribuir la funda a ninguno: el
nodo de Samsung declara un `stm32_vddo-supply` y un regulador de refuerzo
`max77816,kbd_boost@18`, y sin encenderlos el MCU no arranca y el detector de
presencia no conduce. La medida no dice «no hay señal», dice «no hay
alimentación».

Dato aportado por la dueña que cierra el razonamiento: **esta funda hay que
desengancharla de los pines para cerrarla**. Con la funda cerrada el enlace
pogo está muerto por definición, así que el estado «cerrada» no puede llegar
por ahí. Y como el imán no mueve ni el Hall que ya usamos (TLMM 107, que sí
funciona con la funda normal) ni el segundo (TLMM 203), lo más probable es que
esta funda no lleve imán en esa posición y que en stock sea el propio driver
del teclado quien apague la pantalla al ver que el conector se ha soltado.

Consecuencia para la planificación: el apagado automático con la funda de
teclado **no es independiente del teclado**. Las dos mitades son un solo
trabajo: portar el protocolo `stm,stm32_pogo` desde la publicación GPL de
Samsung, habilitar SE15 y VDDO, y traducir el evento Hall que envía el MCU a
`SW_LID`. El booster se pospone salvo que una medida del EF-DX920 demuestre que
también lo necesita.

### Medido con el MCU alimentado

Una prueba transitoria con GPIO chardev v2 aplicó exactamente los niveles del
DT stock: TLMM10=1 (VDDO), TLMM12=0 (BOOT0) y TLMM13=1 (NRST). TLMM62 empezó a
mostrar actividad periódica y TLMM75 produjo una transición. Al cerrar los
descriptores todos los GPIO quedaron liberados. Esto prueba que la alimentación
y el cableado de control son correctos; no prueba todavía que el teclado
registre pulsaciones, que requiere arrancar el driver sobre SE15.

### `CONFIG_GPIO_CDEV_V1` hace falta para las herramientas de Ubuntu

Ubuntu 24.04 trae libgpiod 1.6, que solo habla la ABI v1 del chardev de GPIO.
El kernel mainline la trae desactivada, así que `gpioget` devolvía
`Invalid argument` en **todas** las líneas, incluso las que están en uso. El
síntoma parece un pin reservado y no lo es. Resuelto: `CONFIG_GPIO_CDEV_V1=y`
está en `config-ubuntu-desktop.fragment`. Queda como aviso porque el fallo es
mudo y muy fácil de confundir con un problema de hardware.

## Una tablet que no enciende puede ser modo emergencia

El 2026-08-03 la tablet «no arrancaba»: pantalla negra tras reiniciar. No era
el panel ni GDM. El sistema arrancaba entero y se paraba aquí:

```
systemd-fsck-root.service: Failed with result 'exit-code'
Reached target emergency.target - Emergency Mode
```

`emergency.target` abre una consola de root en la tty. En un portátil eso se
ve; aquí el panel sigue oscuro hasta que la recuperación de arranque en frío lo
reinicia, y sin gestor de sesión no hay nada que dibujar. El resultado es
indistinguible de un dispositivo muerto.

Cómo diagnosticarlo sin pantalla: montar la raíz desde TWRP en solo lectura,
sacar **todos** los `system*.journal` —no solo el activo— y leerlos con
`journalctl -D`. Con un único fichero se ve el tramo final del arranque y es
fácil concluir que systemd se colgó a mitad, cuando en realidad lo que falta es
el principio. Aquí pasó exactamente eso y costó una hipótesis equivocada.

La reparación es `e2fsck -fy` sobre la partición desmontada. Antes conviene
`e2fsck -fn`, que no escribe nada, para ver el alcance: si los pases 2 y 3
salen limpios la estructura de directorios está intacta y la reparación es
rutinaria.

### La causa: la raíz se creaba sin journal

`build-sd-image.sh` formateaba la raíz con `-O ^has_journal` para ahorrar
escrituras a la microSD. Es el intercambio equivocado para la raíz de una
tablet que se apaga a lo bruto: sin journal, cada apagado sucio puede dejar
inodos sueltos y bitmaps descuadrados, y eso se acumula. Con
`Errors behavior: Continue` —el defecto— ext4 además sigue funcionando después
de detectar corrupción, así que el daño crece en silencio hasta el día en que
`e2fsck` se planta y el arranque cae a emergencia.

Ahora la raíz lleva journal y `-e remount-ro`. El primer error real deja la
raíz en solo lectura: molesto, pero visible y reparable antes de componerse.

## No reiniciar `systemd-logind` con una sesión gráfica viva

Al instalar el manejador del botón de encendido se hizo
`systemctl restart systemd-logind` para que cogiera su drop-in. Con el
escritorio abierto, eso le rompe a GDM el seguimiento de sesiones: abrió dos
greeters nuevos sin cerrar el anterior y, al iniciar sesión la dueña, su
`gnome-shell` y el greeter zombi se disputaron el DRM master. El perdedor
repetía

```
[atomic] Failed to disable device '/dev/dri/card1': drmModeAtomicCommit: Permiso denegado
```

y la pantalla se quedaba negra con el cursor del greeter parpadeando. Se
recupera terminando las sesiones de `seat0` y reiniciando `gdm3`, hasta dejar
un único compositor.

El reinicio no hacía ninguna falta: un drop-in de `logind.conf.d` se aplica
solo en el siguiente arranque, y eso bastaba. Si hay que aplicarlo en caliente,
reiniciar también el gestor de sesión, no solo logind.

## El botón de encendido necesita un solo dueño

Lo que se pedía —toque corto suspende, pulsación larga saca el diálogo de
sesenta segundos— no lo puede dar ninguna de las dos piezas por separado:

- **logind** distingue la pulsación larga (`HandlePowerKeyLongPress`) pero solo
  ejecuta acciones fijas suyas, y «mostrar el diálogo de GNOME» no es una;
- **gnome-settings-daemon** muestra ese diálogo con
  `power-button-action='interactive'`, pero trata igual todas las pulsaciones.

Repartir la tecla entre ambos produce carreras, porque los dos actúan sobre la
misma pulsación. `ubuntu-gts9u-powerkey.service` se queda con el evdev del
`pmic_pwrkey` y decide por duración; a los otros dos se les aparta
explícitamente (`HandlePowerKey=ignore` y `power-button-action='nothing'`).

La pulsación larga invoca `org.gnome.SessionManager.Shutdown` en la sesión
activa, que es lo mismo que hace `gnome-session-quit --power-off`.

### La pulsación que despierta no es una orden

Sin tratarla aparte, un solo toque suspendía, la pulsación de despertar se leía
como otro toque y la tablet volvía a dormirse. `CLOCK_MONOTONIC` no avanza
durante la suspensión, así que esa pulsación llega —para ese reloj— apenas unos
segundos después de haberse emitido la suspensión, por mucho que el equipo haya
dormido horas. Descartar las pulsaciones dentro de esa ventana resuelve el caso
sin necesidad de escuchar `PrepareForSleep`.

## El build del kernel es incremental, y por eso las releases no eran reproducibles

`build-mainline-kernel.sh` reutiliza `$build_dir` entre ejecuciones. Eso hace
rápida una recompilación normal, pero también hace que la imagen dependa de lo
que hubiera antes en el árbol.

Se descubrió al cerrar v0.11. La tablet arrancaba un `boot.img` `df98bc12…`
construido en la sesión 14 que no correspondía a ninguna release. Al construir
v0.11 desde el repositorio —con **todo** el código de las sesiones 13 y 14
commiteado y `kernel/` limpio— salió `e7d65812…`. Fuentes idénticas, binario
distinto.

No era `SOURCE_DATE_EPOCH`: se deriva del commit del kernel, que está fijado.
Era el estado previo del directorio de compilación.

`KERNEL_CLEAN=1` lo descarta antes de empezar. Es lento, así que es opcional,
pero **una release debe construirse así**: sin eso, comparar hashes entre dos
builds no significa nada y no se puede demostrar que lo que arranca el
dispositivo salga del árbol que dice el manifiesto.

## La versión V34 del teclado es contenido real, no una lectura marginal

La diferencia `00 37 00 37` frente a `00 34 00 34` se interpretó primero como
posible corrupción de lectura o de flash. Un volcado completo, repetible y de
solo lectura de los 64 KiB del STM32 cerró esa hipótesis: SHA-256
`8937281d2efa08400390f9a2b02e40ca914b634e646d6dd544980c38464533ef`, versión
V34 en `0x200`, ninguna copia V37 y tabla de vectores ARM coherente. Las cadenas
del binario nombran expresamente `TabS9(STM32G0) Series -> V34`.

De ahí se concluyó que One UI usa V34 y que el fallo era nuestro, de estado
frío. **La conclusión no se sostenía.** Una imagen válida no dice quién la
escribió, y en este proyecto no existe ningún V34: el blob oficial del X910 —el
mismo de pmOS— es V37, y es el que la sesión 8 programó para obtener las
primeras pulsaciones reales. La regla útil es más simple: *el driver mainline
solo habla V37*. Con V34 la aplicación pulsa CONN y calla; devolver V37 al MCU
recuperó el teclado en el acto y a través de un arranque en frío.

El comando reversible del bootloader ROM `GO 0x08000000` fue aceptado tanto sin
como con los raíles ya estabilizados, pero no cambió el bucle de CONN de ~2,126
s ni produjo DATA/modelo. Era la aplicación V34 arrancando bien y hablando otro
protocolo. No repetir ese salto esperando que por sí solo sea la inicialización
que falta.

Queda sin medir qué devuelve el MCU a V34. Ningún blob del árbol lo hace, así
que el sospechoso es el `stm32_pogo_v3.ko` de Samsung con los blobs de su propio
vendor, bajo One UI o bajo el port de Ubuntu Touch. Si el teclado vuelve a
callar, lo primero que hay que mirar es `flash version` en el `dmesg` del pogo.

El updater no puede escribir el accesorio por accidente: además de sus
condiciones de seguridad exige `GTS9U_ALLOW_POGO_FLASH=YES`. No se debe definir
esa guarda ni programar el STM32 sin autorización explícita y separada de las
particiones de arranque.

## La build limpia no es reproducible, y ya se sabe exactamente por qué

Medido el 2026-08-07 con dos builds limpias de un árbol idéntico (se verificó
antes que desde `f078c39`, el `port_revision` de la v0.16, no había cambiado
nada en `kernel/`, `scripts/`, `configs/` ni `packaging/`).

Coinciden el DTB, `vendor_boot`, `init_boot` y `dtbo`. **No coinciden `Image.gz`
ni, por arrastre, `boot.img`.** Hay dos causas, y conviene no confundirlas:

**1. La clave de firma de módulos.** `CONFIG_MODULE_SIG_KEY` apunta a
`certs/signing_key.pem`, *dentro* del directorio de objetos. Cuando falta,
kbuild la fabrica con `openssl req`, y el certificado se enlaza en la imagen.
`KERNEL_CLEAN=1` borra ese directorio, así que acuña una clave nueva cada vez.

**2. BTF, que es la de verdad.** Con la clave fijada fuera del directorio de
objetos, `config` sí pasó a coincidir, pero `Image.gz` seguía difiriendo. La
diferencia se aisló en un módulo de 1 MB en lugar de en una imagen de 67 MB:

| Región | Bytes distintos |
|---|---|
| Todo lo anterior a `.BTF` | **0** |
| Dentro de `.BTF` | 184.688 |
| Después de `.BTF` | 255 |

El código compilado ya es determinista. Los 255 bytes finales son la firma
PKCS#7 del módulo, calculada sobre un contenido que cambió: consecuencia, no
causa. El mecanismo está en `scripts/Makefile.btf` del propio kernel, que con
pahole v1.25 pasa `--btf_gen_floats -j$(JOBS)`; el codificador BTF paralelo
produce una salida distinta en cada ejecución.

### Qué haría falta, si algún día importa

Un envoltorio de `pahole` que reescriba `-jN` a `-j1`, sin tocar el paralelismo
del resto de la compilación. Envoltorio y no `PAHOLE_FLAGS` sobrescrito: el
kernel elige esos flags según la versión de pahole, y fijar hoy el conjunto se
pudriría en cuanto se actualice. No puede ir por el entorno, porque el Makefile
raíz asigna `PAHOLE` con `=`, que gana a una variable exportada; tiene que ir en
cada línea de `make`.

**Nada de esto está aplicado.** Se probó y se revirtió: el árbol se mantiene
igual al que construyó la v0.16, que es la que funciona en la tablet. Aplicarlo
cambia el kernel, y por tanto obliga a una release nueva y a reflashear, que es
un precio que hoy no compra nada — el teclado y el resto funcionan. Queda aquí
medido para el día que se quiera cobrar.

Si se aplica, la reproducibilidad seguiría siendo **por máquina**: la clave de
firma es privada y no puede entrar en Git, y una clave publicada no sería una
firma.

## Las cuatro cámaras no son cuatro pipelines independientes

En el SM-X910, CAMSS expone diecisiete nodos de vídeo porque cada RDI del VFE es
un destino posible. Eso no significa que `/dev/video0` sea una lente concreta.
La identificación estable está en el subdispositivo del sensor y su enlace
físico:

| módulo | bus | subdispositivo observado | CSIPHY |
|---|---|---|---|
| HI1337 trasero principal | CCI0 master 1, `0x21` | `/dev/v4l-subdev32` | 1 |
| HI847 trasero angular | CCI0 master 0, `0x21` | `/dev/v4l-subdev34` | 2 |
| HI1337 frontal principal | CCI1 master 1, `0x20` | `/dev/v4l-subdev31` | 4 |
| HI1337 frontal angular | QUP I²C9, `0x21` | `/dev/v4l-subdev30` | 5 |

Cada prueba deshabilita los enlaces anteriores y conduce **un** sensor por
`csiphyN → csid0 → vfe0_rdi0 → /dev/video0`. Juzgar el objetivo por el número
de `/dev/video*` es incorrecto y dejar varios enlaces activos hace que una
captura aparentemente válida pueda venir del sensor anterior.

### Los `slaveAddress` de CamX son de ocho bits

El frontal principal fue la excepción que destapó la regla. Su descriptor stock
da `slaveAddress = 0x40`; usarlo literalmente como dirección Linux no encuentra
nada. Es la dirección de ocho bits: en el DT corresponde a `reg = <0x20>`. Los
otros tres módulos declaran `0x42`, que se convierte en `0x21`.

CCI1 master 1 tampoco usa los pines CCI ordinarios: el stock lo lleva por el par
AON GPIO208/209. Sin ese pinmux el controlador enumera, pero cada lectura de
identidad falla; no es un problema del registro de chip.

### Los tres HI1337 necesitan tablas distintas, no una inicialización genérica

Los blobs de Samsung usan Parameter Parser V3. Decodificarlos dio una tabla
global exacta de 1.476 escrituras y un modo exacto para cada módulo: 4128×3096,
3408×2556 y 4000×3000. Con una secuencia aproximada el sensor puede contestar
por I²C y aun así no emitir CSI-2: leer `0x0716 = 0x1337` solo prueba identidad,
no streaming.

Las secuencias de alimentación stock también importan. VIO y VDIG reciben sus
retardos, después se habilita el módulo, MCLK se estabiliza 10 ms y solo entonces
sale de reset. PM8550VS-C L1 no representa 1.100 V exactamente; 1.104 V es el
paso NLDO más cercano. PM8550B L11 es el raíl compartido de 1,1 V para display y
cámaras frontales, también votado a 1.104 V, no el antiguo nombre de 1,2 V.

Los dos frontales comparten MCLK4/GPIO104. El principal, que sonda primero,
mantiene la propiedad del pinctrl y el angular reutiliza el reloj; intentar que
los dos reclamen el mismo grupo deja al segundo bloqueado antes de leer su ID.
Los GPIO de enable/reset se solicitan solo mientras el sensor está alimentado y
se liberan al terminar el stream.

### De RAW10 a cámara de escritorio: las seis capas que faltaban

RAW10 había cerrado sensor, reloj, alimentación, CSI-2, CSIPHY, CSID, VFE y
DMA, pero no era una interfaz de aplicación. La ruta terminada añade seis
capas reproducibles:

1. los drivers exportan selección, orientación y ubicación V4L2 para que
   `libcamera` distinga frontal/trasera y no tenga que adivinar el recorte;
2. `libcamera` 0.7.2 usa pipeline `simple` y software ISP con ayudantes HI1337 y
   HI847. Ambos codifican ganancia como `(code + 16) / 16` y tienen pedestal 64
   en RAW10 (`4096` al normalizar a 16 bits);
3. los tuning YAML activan AE, AWB gris, pedestal, ajuste y CCM. El arranque
   parte de ganancias `[1, 4]`; el AWB converge sobre estadísticas reales;
4. el SPA libcamera de PipeWire 1.0.5 lleva los backports imprescindibles para
   libcamera 0.7 y para el orden de bytes RGB. Sin saltar `ColourGains` (array),
   WirePlumber aborta; con el mapa RGB antiguo, la imagen sale magenta;
5. un `v4l2loopback` parcheado y firmado crea `/dev/video20`–`23`, mientras
   cuatro relés bajo demanda traducen las fuentes PipeWire a YUYV 1280×960;
6. OBS conserva su fuente V4L2 estándar, pero su lista omite los nodos RAW
   `Qualcomm Camera Subsystem` que no son cámaras listas para aplicaciones.

`/dev/udmabuf` debe ser `root:video 0660` y llevar `uaccess`; de otro modo el
ISP funciona como root y falla justamente en las aplicaciones. La validación
final exigió dos rondas consecutivas de 12 aperturas sobre los cuatro nodos,
240 frames en total, cuatro aperturas WebRTC en Chrome y las cuatro selecciones
de la fuente V4L2 estándar de OBS. PipeWire y el servicio de relés conservaron
sus PID y el sistema mantuvo exactamente cuatro relés.

El software ISP ya no usa un escalado *cover* que recortaba los laterales al
pedir una relación distinta. Calcula el menor factor, centra la imagen y limpia
el resto a negro; de este modo una salida 4:3 conserva todo el sensor y una
salida 16:9 puede mostrar barras en vez de fingir zoom. Esto no amplía el campo
óptico de la trasera principal, que físicamente es más estrecho.

### La compatibilidad V4L2 necesita serializar el único ISP

Los cuatro nombres no representan cuatro pipelines físicos. Todos terminan en
el mismo CAMSS/ISP y abrir dos entradas libcamera durante la cola asíncrona de
liberación puede hacer caer PipeWire. Cada relé toma por ello un `flock` común,
agrupa durante 500 ms los cierres breves de negociación y conserva el bloqueo
dos segundos después de llevar su pipeline a `NULL`. La misma guarda se aplica
a la ruta de error: soltar inmediatamente un input fallido dejó callbacks
CAMSS en vuelo y reprodujo un `SIGSEGV` en la duodécima conmutación.

OBS añadió otro fallo independiente. En Noble, si `/dev/v4l/by-id` o
`/dev/v4l/by-path` no existen, `v4l2-input.c` libera un `namelist` sin
inicializar; además, la ruta de deduplicación asumía una lista no vacía. El
parche inicializa el puntero a `NULL`, recorre la lista con condición nula y
filtra por el nombre de tarjeta exacto de CAMSS. El diálogo probado contiene
sólo las cuatro GTS9U y sigue permitiendo resoluciones, formatos y controles
V4L2 normales.

### Los relés de sistema necesitan un PipeWire persistente

Los nodos `/dev/video20`–`23` pertenecen a un servicio de sistema, pero sus
fuentes viven en el grafo PipeWire de la cuenta que creó OOBE. No existe un
usuario ni un UID conocidos al construir la imagen. En un arranque sin sesión
gráfica, una conexión SSH podía iniciar temporalmente ese gestor de usuario y
PipeWire; al cerrar SSH desaparecía el servidor mientras los cuatro relés
seguían vivos, unidos al socket antiguo y entregando frames negros.

`ubuntu-gts9u-desktop-user` encuentra las cuentas humanas por el intervalo
`UID_MIN`–`UID_MAX`, habilita *linger* y escribe en `/run` un drop-in con el
nombre, UID, runtime y bus reales. La unidad de relés sólo arranca si existe ese
drop-in y nunca contiene `User=ubuntu` ni `/run/user/1000`. El lanzador no
considera listo un socket por sí solo: espera un `MainPID` vivo de
`pipewire.service`, conserva ese PID y vigila tanto PipeWire como cada relé.
Cualquier cambio reinicia el conjunto completo mediante systemd.

La versión 2.17 de la imagen llevaba por error todavía la variante construida
con `PathExistsGlob=/home/*`. Al ser una condición por nivel, relanzaba el
oneshot hasta el límite de systemd y podía bloquear la dependencia de cámaras.
No bastaba corregir el fichero con el mismo número de versión: apt no tenía
motivo para reemplazarlo. La 2.18 sube versión y su `postinst` hace
`daemon-reload`, limpia los tres estados fallidos, reinicia el watcher por
flanco y vuelve a resolver la cuenta. Si los relés estaban activos, los
reinicia después de la actualización para ejecutar el binario recién instalado
en vez del inode antiguo.

### Dos carreras pequeñas explicaban el negro al cambiar

La preempción se pide con `SIGUSR1`. Si la señal llegaba justo después de cerrar
el consumidor anterior, marcar siempre `input_preempted = TRUE` dejaba aquel
relé en splash negro aunque ya no hubiese cliente que preemptar. La marca se
aplica ahora sólo cuando `input_client_active` sigue siendo cierto; un error del
input recrea además la tubería mientras el consumidor permanezca abierto.

La segunda carrera estaba en un fichero de siete bytes. Cada dueño hacía
`ftruncate()` y `dprintf()` sobre el descriptor común, pero truncar no devuelve
el offset a cero. Tras varios cambios los PID quedaban precedidos por huecos NUL,
`g_ascii_strtoll()` leía dueño cero y el siguiente relé no enviaba la señal. Se
hace `lseek(..., SEEK_SET)` antes de cada escritura. Es una buena prueba de por
qué el nombre visible, el nodo abierto y un proceso vivo no demuestran que el
relevo esté ocurriendo.

Al diagnosticar un `v4l2loopback` con buffers duplicados hay que consumir a
ritmo de vídeo. Un `v4l2-ctl` sin pausa puede leer 75 veces el último buffer
antes de que venza incluso el debounce de 250 ms y producir una congelación
falsa. La validación WebRTC mantiene un único consumidor, espera imagen no
negra, compara muestras separadas dos segundos y exige tiempo multimedia,
brillo y cambio de píxeles. Tres rondas seguidas y el primer consumidor tras un
arranque en frío obtuvieron 4/4; OBS se verificó con dos capturas separadas tres
segundos por cada fuente estándar.

La revisión de color no justificó cambiar el CCM global. Las frontales quedaron
próximas a neutro y las traseras mostraron un sesgo verde moderado bajo flash en
una escena fuertemente roja/marrón, precisamente un caso adverso para el AWB de
mundo gris. Una corrección reproducible necesita una carta gris/color y varias
temperaturas de luz; hasta entonces se conserva el tuning actual.

### El DW9808 necesita un canal separado de los controles del sensor

El firmware stock identifica el actuador de la trasera principal como DW9808,
en CCI1 master 0 con dirección Linux `0x0c`. Su secuencia de arranque exacta es
`02=01, 02=00, 06=60, 07=05`, las posiciones de preparación de Samsung y
`02=02`; una prueba I²C recorrió 0–1023 y confirmó que óptica y motor responden.
El DTS comparte GPIO15 mediante un regulador fijo entre VIO del HI1337 y VCC de
la lente, y enlaza ambos con `lens-focus`.

No se pueden fusionar sin más los `ControlInfoMap` V4L2 del sensor y la lente:
cada subdispositivo crea su propio mapa de identificadores y libcamera aborta
si un control pertenece al mapa ajeno. La solución reproducible añade a la IPA
software un booleano `hasFocus` y un evento IPC `setLensPosition`; exposición y
ganancia siguen viajando al sensor, mientras la posición llega solo a
`CameraLens`.

Las estadísticas del ISP acumulan una derivada segunda horizontal de
luminancia. La IPA normaliza esa medida por luz, barre 128–896, afina alrededor
del mejor punto en pasos de 48 y publica `AfMode`, `AfTrigger`, `AfState` y
`FocusFoM`. El modo continuo vuelve a explorar si el mérito cae de forma
sostenida, con una comprobación de seguridad espaciada para evitar respiración
en vídeo. En hardware, una captura de 41 fotogramas registró el recorrido real
de la lente y terminó con el texto del billete legible; GNOME Cámara y OBS
confirmaron después el mismo resultado por la ruta de aplicaciones.

### El APM de audio puede fallar en un arranque sin que lo cause la cámara

Durante la regresión, dos arranques mostraron `APM_CMD_GET_SPF_STATE` agotado,
el pinctrl LPASS en `-EACCES` y micrófonos con todos los samples a cero. No se
reinició el ADSP en caliente. Tras un arranque completo desde TWRP, la misma
imagen de cámara produjo 729.285 muestras no nulas antes de usar CAMSS y
733.706 después de capturar con los cuatro sensores. Por tanto, tomar un único
buffer silencioso como regresión de cámara habría sido otro falso positivo; hay
que exigir además los mensajes del APM y repetir desde arranque completo.

### Los números de adaptador I²C no son una ABI

Al habilitar los controladores CCI de cámara, el STM32 pogo siguió siendo el
mismo dispositivo físico a `0x2a`, pero Linux pasó a enumerarlo como
`11-002a` en lugar de `6-002a`. El restaurador de V37 tenía la segunda ruta
codificada y, tras volver el MCU a V34, terminó correctamente diciendo que no
había controlador. La ruta estable es el enlace del dispositivo bajo
`/sys/bus/i2c/drivers/samsung-gts9u-stm32-pogo/`, no el número de adaptador.
Servicios, diagnósticos y documentación deben buscar allí `*-002a`; añadir un
bus no puede convertir un accesorio existente en ausente.

### La linterna de escritorio no necesita conceder el flash a todo el sistema

El LED combinado aparece como `/sys/class/leds/white:flash`. El mosaico de
GNOME solo necesita la luz continua, por lo que udev cambia exclusivamente
`brightness` a `root:video 0660`; `flash_strobe`, intensidad de estrobo,
timeout y fallos permanecen `root:root`. El comando `gts9u-flashlight` valida
0–255 y usa 128 por defecto. No se instaló ningún helper setuid ni una regla de
sudo genérica.

La extensión de sistema `flashlight@ubuntu-gts9u` usa la API Quick Settings de
GNOME 46. Lee el estado físico, ejecuta el helper sin bloquear Shell, muestra
un indicador mientras está encendida y fuerza apagado al descargarse. El
paquete preserva la lista existente de extensiones al añadir su UUID, y el
constructor de rootfs hace lo mismo después de crear el usuario. Un hook
`system-sleep` escribe cero antes de suspender.

Esto resuelve linterna y luz continua durante una foto. Un flash fotográfico
automático es otro trabajo: necesita que libcamera exponga controles de flash
y coordine el estrobo con el request y la exposición. No se debe simular esa
sincronización dando a Snapshot acceso directo a todos los atributos sysfs.

Las comprobaciones de orientación deben usar contenido físico, no solo
`camera_sensor_rotation`. Las dos frontales con el monitor y las dos traseras
con un billete legible salieron derechas a través de GNOME Cámara y OBS. El
autofoco de la principal permite ya usar también esa lente como patrón físico.

## Instalar en la UFS no exigía tocar la tabla de particiones

Durante todo el port se dio por hecho que llevar la raíz a la UFS obligaba a
reparticionar o a rehacer `super`, y por eso se pospuso. No era cierto. La
partición `userdata` de este dispositivo mide 939 GiB, ya existe, y no hace
falta nada más: se escribe dentro un sistema de ficheros ext4 con `dd` y se
redimensiona con `resize2fs` en el primer arranque. La GPT que trae Samsung se
queda intacta, que es justo lo que mantiene la vuelta atrás en un solo flasheo
de Odin.

Lo que sí se pierde son los datos de usuario de Android, porque son
literalmente lo que ocupa esa partición. `super` sigue intacto, así que la
imagen de sistema de Android continúa ahí; esto no es un dual boot y no lo
aparenta.

`super` se descartó como destino: 11,2 GiB no dan para un escritorio, y usarlo
obligaría además a reconstruir sus particiones lógicas, que es exactamente la
clase de operación que este diseño evita.

Tres detalles que no son evidentes hasta que se implementa:

- **El ZIP no puede leerse desde el destino.** El «almacenamiento interno» de
  TWRP *es* `userdata`. Un ZIP guardado ahí se destruiría a sí mismo a mitad de
  la escritura. El instalador aborta si su propia ruta está en `/data` o
  `/sdcard`, y la instalación se hace desde microSD o USB-OTG.
- **La etiqueta tiene que cambiar.** `root=LABEL=` resuelve a lo primero que
  encuentre. Con `UBTS9U_ROOT` en ambos sitios, una microSD vieja en la ranura
  arrancaría en lugar de la instalación interna, y el síntoma sería «el
  flasheo no ha hecho nada». La raíz interna es `UBTS9U_UFS`.
- **El orden de escritura importa.** Primero la raíz, después las imágenes de
  arranque. Al revés, un fallo a mitad deja un kernel nuevo sin sistema que
  arrancar; así deja el dispositivo donde estaba, a un reintento.

La comprobación de `validate-bundle.sh` que prohibía nombrar `userdata` en el
instalador se ha convertido en dos: `userdata` ya se puede nombrar, pero ningún
`mkfs`, `parted`, `sgdisk`, `sfdisk` ni `wipefs` puede aparecer. La garantía
que importa no era «no tocar esa partición», era «no tocar la tabla».

## El shell de TWRP hace aritmética de 32 bits, y una imagen de 3 GiB no cabe

El primer flasheo de la v0.18 abortó con «malformed rootfs image size» sobre un
ZIP correcto. La imagen mide 3 271 557 120 bytes; el instalador comprobaba
`[ "$ROOTFS_SIZE" -gt 0 ]` y esa comparación era falsa.

TWRP ejecuta `update-binary` con `/sbin/sh`, que es un enlace a
`/system/bin/sh`: **mksh**. El binario es ELF de 64 bits para aarch64 —lo cual
despista— pero el tipo aritmético de mksh es `int32_t`. 3 271 557 120 supera
2³¹, así que se interpreta como −1 023 410 176 y cualquier `-gt 0` falla. Todas
las comprobaciones anteriores habían pasado porque los tamaños de las
particiones de arranque (100 663 296 y menores) sí caben en 32 bits: el primer
número que pasaba de 2 GiB fue el primero que falló.

Reglas que se derivan:

- **Ningún valor manejado por el instalador puede pasar de 2 GiB.** Los tamaños
  se cuentan en MiB. El manifiesto `ROOTFS-IMAGE` publica los bytes para las
  personas y para las comprobaciones de este repositorio, y **además** los MiB,
  que es el campo que lee el instalador.
- **`blockdev --getsize64` sobre `userdata` no se puede comparar en el shell**:
  son ~1,008 × 10¹². La capacidad se comprueba leyendo con `dd` el último MiB
  que ocupará la imagen y contando los bytes devueltos; una partición que se
  queda corta devuelve menos, o nada.
- **Probar el instalador con `bash` no sirve.** El primer banco de pruebas con
  particiones loopback pasó en verde justo antes de que el flasheo real
  fallase, porque `bash` tiene aritmética de 64 bits. El banco ahora lo ejecuta
  con `mksh`, y `validate-bundle.sh` rechaza cualquier literal de diez cifras
  o más en el instalador.

No es un problema de TWRP ni de este dispositivo: es lo que hay en cualquier
recovery con el shell de Android, y volverá a morder a la primera imagen que
crezca por encima de 2 GiB.

## En TWRP, `unzip -l ZIP MIEMBRO` no falla nunca

El `unzip` de TWRP es un enlace a **ziptool**, el de AOSP. Preguntado por un
miembro que no existe imprime «0 files» y **sale 0**:

```
$ unzip -l paquete.zip NO-EXISTE ; echo $?
0
```

`unzip -p` con un miembro ausente hace lo mismo: no imprime nada y sale 0.

El instalador usaba ese idioma para decidir qué llevaba el ZIP. Todas esas
comprobaciones eran verdaderas siempre, así que un ZIP sin overlay se
consideraba portador de uno y abortaba con «the ZIP carries both a rootfs image
and an overlay». Las comprobaciones de que las cinco imágenes de arranque
estaban presentes tampoco comprobaban nada.

La forma correcta es leer el listado una vez y preguntarle:

```sh
unzip -l "$ZIPFILE" > "$ZIP_LISTING"
zip_has() {
    awk -v name="$1" '$NF == name { found = 1 } END { exit !found }' "$ZIP_LISTING"
}
```

Verificado en el dispositivo contra un ZIP real: distingue `boot.img`,
`META-INF/com/google/android/update-binary` y un nombre inventado.

La lección general, que ya ha costado dos flasheos: **una comprobación que no
puede fallar es peor que no comprobar nada**, porque además da confianza. Y el
banco de pruebas en WSL usa el `unzip` de Debian, que sí devuelve 11: para que
el banco valga hay que imitar el comportamiento de ziptool, y ahora lo hace con
un envoltorio en el `PATH` de prueba. `validate-bundle.sh` exige además que el
instalador ejecute `unzip -l` exactamente una vez.

## La cuenta la crea la usuaria, no el build

Hasta la v0.18 la imagen traía un usuario `ubuntu` creado en el
`--customize-hook`, con la contraseña que llegara en `GTS9U_PW`. Dos problemas,
y el segundo es el grave:

1. Cualquiera que instalase heredaba la cuenta de otra persona.
2. **`GTS9U_PW` era obligatorio y no puede estar en el repositorio.** Una build
   limpia era literalmente imposible para quien no supiera esa contraseña. Se
   descubrió al construir la v0.18: hubo que reutilizar el rootfs de la v0.17 e
   instalarle los paquetes por encima, en lugar de reconstruirlo.

Desde v0.19 la imagen no lleva cuenta y GDM lanza `gnome-initial-setup`, que
pregunta nombre, contraseña, idioma, teclado y zona horaria. GDM toma ese
camino cuando **no hay ninguna cuenta ordinaria** —el estado exacto del rootfs
recién construido— y `InitialSetupEnable=true` está en `/etc/gdm3/custom.conf`.
Ubuntu distribuye ese fichero con todas las claves comentadas, así que hay que
**escribir** la línea, no descomentarla.

Comprobado antes de adoptarlo, en lugar de suponerlo: `gnome-initial-setup`
46.3 de noble arm64 conserva `gis-account-page.ui` y `gis-password-page.ui`, o
sea que su página de creación de cuenta sigue ahí. `ubuntu-desktop-bootstrap`,
el asistente Flutter de las imágenes de Raspberry Pi, **no está en el archivo
de noble**; `oem-config`/`ubiquity` sí, pero son el camino pesado y basado en
X.

Lo que esto obliga a cambiar: nada del port puede nombrar a un usuario.

- La extensión de la linterna se activa con un *gschema override*, no
  escribiendo en el `gsettings` de una cuenta. Ningún otro fichero de la imagen
  toca `enabled-extensions` —las extensiones de Ubuntu vienen del modo de
  sesión de gnome-shell—, así que poner el valor por defecto ahí añade la
  nuestra sin desplazar las suyas.
- El *linger* lo aplica `ubuntu-gts9u-user-linger.service` en cada arranque,
  para todo UID entre `UID_MIN` y `UID_MAX`, porque la cuenta no existe cuando
  se construye la imagen.
- La clave SSH, si se da, va a `/etc/skel`, que es lo que se copia a la cuenta
  que cree el asistente.

Si el asistente no llegara a salir, la vía de vuelta es TWRP: la raíz es ext4 y
se monta desde ahí para crear una cuenta a mano, o se reflashea. Merece la pena
tenerlo presente porque, sin cuenta y sin asistente, no hay forma de entrar.

## Lo que el asistente no le da a la cuenta que crea

`gnome-initial-setup` crea un administrador, y en Ubuntu eso significa `sudo`,
`adm`, `plugdev` y `users`. Nada más. La cuenta que creaba el build antes
estaba además en `video`, `render`, `input`, `audio`, `dialout`, `cdrom` y
`netdev`, y esa diferencia no es cosmética: la regla udev de este port hace
`chgrp video` sobre el `brightness` del LED de flash, así que sin ese grupo el
mosaico de la linterna se apaga solo al pulsarlo y no enciende nada. Fue el
primer fallo de la primera imagen sin cuenta, y se veía exactamente así.

Lo aplica ahora `ubuntu-gts9u-desktop-user`, junto al *linger* y al drop-in de
los relés. Con dos disparadores, porque uno solo no basta:

- el servicio, en cada arranque;
- una unidad `.path` sobre `/etc/passwd`, para el arranque en el que el
  asistente crea la cuenta. Sin ella, todo lo que la cuenta necesita llegaría
  en el arranque *siguiente*: la usuaria terminaría la configuración y se
  encontraría sin cámaras y con una linterna que no hace nada, sin ninguna
  pista de que reiniciar lo arregla.

Queda una carrera conocida: los grupos de un proceso se fijan al iniciar sesión,
así que si el asistente entra en la sesión antes de que la unidad `.path`
termine, esa primera sesión sigue sin los grupos. Un reinicio lo resuelve.
Cambiar el LED a un mecanismo por ACL evitaría la carrera, pero `uaccess` de
logind sólo actúa sobre nodos de `/dev`, y un LED sólo tiene atributos en
`/sys`.

## El asistente sólo ofrece los idiomas que el sistema tiene generados

La imagen generaba un único locale, `es_ES.UTF-8`, así que el asistente ofrecía
exactamente un idioma. Se resuelve con `locales-all`, que trae los 327
pregenerados y de paso evita ejecutar `locale-gen` bajo emulación.

`locales-all` por sí solo permite **elegir** cualquier idioma, con sus
formatos, su orden alfabético y su teclado, pero deja el escritorio en inglés:
un GNOME traducido necesita su `language-pack-XX`.

Aquí se tomó una decisión equivocada y se corrigió: se descartó incluirlos
todos por pesar cerca de 1 GiB. El criterio estaba mal calibrado. Este
dispositivo tiene 256 GB en su versión más pequeña y la raíz ocupa la partición
entera de 939 GiB; el gigabyte no es el recurso escaso. Lo que sí molesta es
una tablet que te ofrece japonés en el asistente y después te habla en inglés.
Desde v0.21 viajan todos los paquetes de idioma.

La lección general: el tamaño de la imagen sólo importa por lo que tarda en
descargarse y flashearse, no por lo que ocupa instalada, y conviene decir cuál
de las dos cosas se está optimizando antes de recortar.

## Actualizar sin perder datos no cabe en el instalador de TWRP

Conservar los datos significa sustituir el sistema fichero a fichero en vez de
escribir la imagen sobre la partición. TWRP no tiene `rsync`, y su `tar` es el
de toybox, sin soporte de xattrs ni ACLs —comprobado en el dispositivo—. Copiar
una raíz de Ubuntu con esas herramientas **pierde silenciosamente todas las
capabilities de fichero**: `ping`, `dumpcap` y compañía dejarían de funcionar
sin que nada lo dijera, y el síntoma aparecería semanas después.

Por eso la actualización vive en `gts9u-upgrade`, que se ejecuta en el sistema
ya arrancado, donde sí está `rsync -aAX`. Lee el ZIP de la release, verifica la
imagen contra su manifiesto, la monta por *loop* y sincroniza sobre la raíz
viva excluyendo lo que es de la usuaria: `/home`, `/root`, las cuentas y sus
grupos, las conexiones de red, las claves de host, el `machine-id`, el journal
y la configuración de idioma y teclado. Después escribe las cuatro imágenes de
arranque y las relee para comprobarlas, porque el kernel y los módulos que
acaba de instalar tienen que ser el mismo conjunto firmado.

No reinicia. Y **no está probado todavía**: se estrenará en la primera
actualización real que haya datos que conservar.

## OBS viaja de prestado

`obs-studio` está en la imagen porque `obs-v4l2-gts9u` —el complemento V4L2
parcheado con el que se validan las cuatro cámaras— depende de él. No está
porque el port quiera distribuir un estudio de streaming: son 21 MiB y una
aplicación que la mayoría de la gente no usará.

**Es temporal, y sale cuando el trabajo de cámaras esté cerrado.** Se queda
mientras el relevo entre cámaras siga sin pulir, porque es la herramienta con
la que se reproduce ese fallo. Al quitarlo hay que quitar también
`obs-plugins`, y comprobar antes que ninguna verificación de cámaras del
proyecto dependa de él.

## El puerto USB-C pierde conexiones, y el chip no siempre avisa

Medido en el dispositivo, no deducido. Con un hub enchufado y sin enumerar:

| Medida | Valor |
|---|---|
| `CC_STATUS` (0x28) | `0x22` — `ATTACH=SINK`, hay algo conectado |
| `INT1`…`INT5` | `00` — ninguna interrupción pendiente |
| Máscaras (0x06…0x0a) | `e6 cf ff 08 ff`, las que programa el driver |
| IRQ 166 (`8-0033`) | congelada desde el desenchufe anterior |

O sea: **el chip detecta el accesorio en `CC_STATUS` y no genera el ATTACH**.
TCPM se queda desconectado indefinidamente. Un `unbind`/`bind` del driver lo
recupera al instante, porque su reprobado programa la resincronización.

No es determinista: en la misma sesión, un enchufe posterior sí se detectó
solo. Por eso el arreglo es una **red de seguridad**, no un valor de registro
adivinado: un trabajo diferido que cada 4 s compara `CC_STATUS` con lo que la
ruta de interrupción ha reportado, y solo llama a `tcpm_cc_change()` cuando el
hardware dice que hay algo y la interrupción **no** lo ha anunciado.

Esa condición es estrecha a propósito. Ya hay un comentario en el driver que
avisa de lo contrario: re-armar la resincronización sin condiciones hacía
**oscilar TCPM entre host y desconectado**, porque tocarlo mientras está
legítimamente ocioso realimenta `start_toggling()`. El trabajo es *deferrable*,
así que una tablet ociosa y sin nada enchufado no se despierta por él.

## Lo que sabemos y lo que no del hub que no enumera

Un hub USB-C bus-powered con 3 USB y Ethernet no enumera en la tablet. Lo que
está **descartado con evidencia**:

- **No está roto**: el mismo hub, con un pendrive, funciona en un PC por USB-C.
- **No es el camino de datos OTG**: en t=369 la tablet tenía un dispositivo
  enumerado *mientras ella entregaba VBUS*, antes de un PR_SWAP a sink.
- **No es la máscara de interrupciones**: Samsung escribe `~ENABLED_INT`, o sea
  1 = enmascarado, y nuestro `0xe6` sí habilita VBUSPOK, ATTACH y DETACH.
- **No es una suspensión que se comiera el evento**: el único ciclo de
  suspensión del arranque es el del panel.

Queda en pie una hipótesis: **el Rp que anunciamos**. En una conexión natural
de sink el driver pone los bits 5:4 de `CC_CNTL1` a cero, el mínimo, y el
puerto reporta `power_operation_mode = default`; un PC anuncia 1,5 A o 3 A.
Escribir ese registro con el hub ya conectado no cambió nada, pero eso **no
prueba nada**: un sink lee el Rp al conectarse, y además el driver lo fuerza al
mínimo justo en el instante del attach.

Por eso se añade `otg_rp` como parámetro de módulo, **con el comportamiento
actual por defecto**. Subirlo a ciegas no es seguro: el puerto entrega 900 mA
de verdad, y un dispositivo que crea otra cosa puede hundir el raíl. Y hay
precedente de romper algo al tocarlo: el propio driver bajó el Rp porque con
`0x59` «se caía repetidamente un dongle OTG pasivo».

## Las imágenes se han distribuido siempre sin capabilities de fichero

`tar --xattrs` copia **solo el espacio `user.*`**. `security.capability` se
descarta sin decir nada, así que todas las imágenes de este port —microSD y
UFS— han salido con `ping` sin `cap_net_raw`, `snap-confine` sin su conjunto de
capabilities y `gst-ptp-helper` sin las suyas. Hace falta
`--xattrs-include='*'` en los dos extremos del `tar`.

Se descubrió por accidente, buscando otra cosa: al comprobar si
`gts9u-upgrade` conservaba las capabilities, el recorrido de la imagen encontró
**cero** ficheros con ellas, mientras el árbol del que se construye tiene tres.
O sea, no se perdían al actualizar; nunca habían llegado.

Es el peor tipo de fallo: silencioso y de efecto diferido. Un binario sin su
capability sigue funcionando para root y deja de funcionar para todo el mundo
más, semanas después, sin nada en ningún log.

`gts9u-upgrade` reaplica además las capabilities explícitamente tras el rsync.
No es redundante: el kernel borra `security.capability` cuando cambia el dueño
de un fichero, así que conservarlas depende del orden en que rsync haga las
cosas.

## Dónde guarda Ubuntu la configuración de red, que no es donde parece

La primera actualización en sitio perdió el wifi pese a proteger
`/etc/NetworkManager/system-connections`. Ese directorio estaba vacío: `nmcli
-f NAME,FILENAME` reveló que el perfil vive en
`/run/NetworkManager/system-connections/netplan-NM-<uuid>.nmconnection`, es
decir, **generado por netplan**. El almacén persistente es `/etc/netplan`.

Y el brillo lo guarda `systemd-backlight` en `/var/lib/systemd/backlight`.

La regla que sale de esto: al preservar estado, **conservar directorios de
estado enteros, no el fichero concreto que uno recuerda**. La lista de
`gts9u-upgrade` pasa a incluir `/etc/netplan`, `/var/lib/systemd`,
`/var/lib/NetworkManager` y compañía.

## El Rp no era: queda la corriente

Barrido completo con reconexión forzada en cada paso, que es la única forma
válida de probarlo —un sink lee el Rp al conectarse—: `CC_CNTL1` a `0x40`,
`0x50`, `0x60` y `0x70`, verificado por lectura tras cada *attach*. El hub no
enumera con ninguno. **La hipótesis del Rp está descartada.**

De las diferencias entre el PC que sí lo levanta y esta tablet queda la
corriente. El SM5714 define `OTG_CURRENT_500/900/1200/1500mA` en los bits 7:6
de `BSTCNTL1` —de ahí que 900 mA a 5,1 V sea `0x46`— y **la tabla de modos de
Samsung elige 900 mA en todas las filas OTG** de esta placa. Conviene no
confundirse con el `POWER_SUPPLY_PROP_VOLTAGE_MAX` de su driver, que imprime
«set otg current limit 1500mA» y **no escribe ningún registro**: es un log, no
una configuración.

Así que subirlo se aparta de lo que hace el fabricante, aunque el chip lo
admita. Por eso `otg_ma` es un parámetro con 900 mA por defecto, igual que hoy.

## Era la corriente, y el pico de arranque no aparece en ningún log

El hub bus-powered con 3 USB y Ethernet arranca con `otg_ma=3` (1500 mA) y no
con 900 mA. Medido: `BSTCNTL1=0xc6`, y en `lsusb` aparecen el hub Genesys Logic
y su RTL8153, que engancha `r8152` y presenta interfaz.

Lo revelador es lo que declaran una vez enumerados: **el hub pide 100 mA y el
Ethernet 180 mA**. Nada. Lo que necesitaba el margen era el **pico de arranque**
de sus reguladores y del PHY. Con el techo en 900 mA la protección del cargador
cortaba antes de que el hub llegase a señalizar el *attach*, y como el corte
ocurre en el cargador y no en el host, **no aparece nada en ningún log**: ni
over-current, ni error de enumeración, ni un intento fallido. Desde el host,
sencillamente no hay nada enchufado.

Esa es la razón de que costara tanto: el síntoma de «le falta corriente» y el
de «no hay nada conectado» son idénticos vistos desde Linux.

Lo que hace seguro subirlo es que **el techo y el anuncio son independientes**.
`otg_ma` sube el límite de la protección; `otg_rp` deja el anuncio en el valor
de fábrica, así que a ningún dispositivo se le dice que puede tirar 1,5 A de
forma continua. Se le da margen para encender, no permiso para consumir.

Orden de las pruebas, que costó aprenderlo: **el límite hay que subirlo antes
de enchufar**. Igual que el Rp, esto se decide al conectar.
