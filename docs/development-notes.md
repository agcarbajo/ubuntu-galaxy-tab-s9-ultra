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
