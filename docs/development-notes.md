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
mismo hardware validado por postmarketOS v1.71, con rootfs en microSD. A largo
plazo, compatibilidad con software de escritorio ARM64 y, después,
Vulkan/Turnip, FEX, Box64 y Proton/Steam **evaluados por separado y con
evidencia**. Steam no es requisito para aceptar el primer Ubuntu funcional.

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
entrada `board-id,00`, decompilada con `dtc`). Nada de esto es visible desde el
sistema en marcha: el teclado no está en ninguno de los siete buses GENI, y por
eso `i2cdetect` no encuentra nada en 0x2a.

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

Lo importante: **`sda_gpio` y `scl_gpio` son pines TLMM sueltos**, no un
controlador GENI. El bus del conector pogo es I²C por GPIO, así que hace falta
un nodo `i2c-gpio` sobre TLMM 72/106 antes de que ningún driver pueda hablar
con el MCU.

Cuelgan de él dos nodos de función:

- `pogo_kpd`, `compatible = "stm,keypad"`, con la lista de nombres que incluye
  `Book Cover Keyboard Slim (EF-DX920)`;
- `pogo_touchpad`, `compatible = "stm,touchpad"`, con
  `touchpad,invert = <0 1 1>`.

Y un regulador de refuerzo aparte: `kbd_boost@18`, `max77816,kbd_boost`.

`stm,stm32_pogo` no existe en mainline. Sí existe en la publicación de fuentes
de Samsung para el SM-X910, que es GPL, así que la vía realista es portarlo, no
reinventar el protocolo.

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
