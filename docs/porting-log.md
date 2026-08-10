# Bitácora del port Ubuntu 24.04

Una sesión por iteración, incluyendo los fallos. El estado vigente está en
[`hardware-status.md`](hardware-status.md) y las conclusiones duraderas en
[`development-notes.md`](development-notes.md).

---

## Sesión 1 — relevo desde postmarketOS v1.71 y build de rollback

Fecha: 2026-07-31. No se tocó la tablet física.

### Contexto

Se recibe el relevo del port postmarketOS `gts9uwifi` en el commit `b1dcca0`,
con la baseline v1.71 congelada y físicamente validada. El objetivo del nuevo
proyecto es conservar esa paridad de hardware con un userspace Ubuntu 24.04
LTS. Se leyó la documentación completa del port anterior antes de escribir
código: README, `hardware-status.md`, `boot-strategy.md`,
`development-notes.md`, `panel-ana38407-bringup.md` y las sesiones relevantes
de `porting-log.md`, además de las fuentes de los tres paquetes de dispositivo,
`configs/` y `scripts/`.

### Build de rollback: ZIP TWRP v1.71

Antes de crear nada nuevo se regeneró la última build de postmarketOS, para
disponer de una vía de vuelta antes de que Ubuntu toque la microSD.

El ZIP se reconstruyó con `REUSE_BUILD_OUTPUTS=1` sobre los outputs de kernel
cacheados de v1.71 (`out/kernel-gts9uwifi-v171`, kernel package r114). El
resultado **no** coincide con el hash registrado del release, y la causa quedó
identificada con precisión:

| Imagen | Resultado |
|---|---|
| `boot.img` | `cb13c0fa…` — **idéntica** a v1.71 |
| `init_boot.img` | `6fab6d38…` — **idéntica** a v1.71 |
| `dtbo.img` | `c17418be…` — **idéntica** a v1.71 |
| `vbmeta.img` | `b95e5ef9…` — **idéntica** a v1.71 |
| `vendor_boot.img` | `55d9d94a…` frente a `c4b93f02…` registrado |

Se descompuso el `vendor_boot.img` regenerado para acotar la diferencia:

- DTB empaquetado: `952688174c…`, **idéntico** al DTB de la build v1.71;
- `vendor_cmdline`: idéntica byte a byte a `configs/vendor_boot/cmdline.txt`;
- bootconfig: idéntico a `configs/vendor_boot/bootconfig.txt`;
- fragmento vendor: contiene exactamente `usr/lib/firmware/qca/hmtbtfw20.tlv`
  (`b91f0af7…`) y `usr/lib/firmware/qca/hmtnv20.b21` (`864476ed…`), ambos
  idénticos a las copias del repositorio.

La única diferencia real son los `mtime` de las cabeceras CPIO: `cpio
--reproducible` normaliza device e inode pero **no** el tiempo de
modificación, y el overlay se copia con `install`, que sella la hora del build.
Es una laguna de reproducibilidad preexistente del pipeline pmOS, no una
divergencia de contenido. Queda anotada en `development-notes.md` y el
pipeline Ubuntu fijará `mtime=0` en el overlay antes de empaquetar.

### Build de rollback: imagen de microSD

El primer intento de regenerar la imagen del rootfs reveló un desajuste que
habría producido un artefacto engañoso: el `pmaports` de la base de build WSL
estaba en **kernel r103**, mientras que la baseline congelada del repositorio
es **r114** (device r44, firmware r10). La imagen resultante se descartó y se
repitió el proceso ejecutando antes `scripts/sync-pmaports.sh`.

El segundo intento falló en `apk add`:

```
breaks: device-samsung-gts9uwifi-1-r44[hexagonrpcd=0.4.0-r4]
```

La causa no estaba en las fuentes: el repositorio congela `hexagonrpcd` en r4 y
el paquete de dispositivo r44 lo fija exactamente. Lo que sobraba era un
`hexagonrpcd 0.4.0-r5` **construido localmente** en un experimento posterior y
todavía presente en `pmbootstrap-work/packages/edge`, que apk prefería por ser
más reciente. Se movió a cuarentena, se reindexó el repositorio local y la
build completó.

El rootfs resultante instala exactamente el conjunto de la baseline: kernel
r114, device r44, firmware r10, `hexagonrpcd` r4, `iio-sensor-proxy` r3 y
Mutter r6.

Dos conclusiones reutilizables:

1. la base de build en WSL no es una fuente de verdad; el repositorio lo es, y
   `sync-pmaports.sh` debe ejecutarse antes de cualquier build entregable;
2. un paquete construido localmente puede ganar a la versión fijada aunque las
   fuentes sean correctas. Ante un `breaks:` de este tipo hay que mirar el
   repositorio local de paquetes antes que los APKBUILD.

### Artefactos de rollback entregados

Quedan en `PostmarketOS/artifacts/`, fuera de Git, con
`MANIFEST-v1.71-rollback.txt`:

| Artefacto | SHA-256 |
|---|---|
| `postmarketos-edge-gnome-mainline-v1.71-dp-dock-coldboot-sm-x910-twrp.zip` | `3270afa0…` |
| `postmarketos-v1.71-rollback-sd-gts9uwifi.img.xz` | `05ccca69…` |

La imagen sin comprimir mide 5.941.231.616 bytes y su SHA-256 es
`fb346a78…`. La imagen del rootfs es una build nueva sobre Alpine edge actual,
no un clon byte a byte del userspace validado en su día; lo que sí se conserva
byte a byte es la parte de arranque, que es donde vive el soporte de hardware.

### Repositorio Ubuntu

Se creó `Ubuntu-24.04/` al mismo nivel que `PostmarketOS/`, con Git local, sin
remoto público, y con `artifacts/`, `work/`, imágenes, firmware y productos de
build ignorados. Se escribió la documentación de partida: README breve, matriz
de hardware con niveles de evidencia explícitos, cadena de arranque heredada,
arquitectura del rootfs y esta bitácora.

### Estado al cerrar la sesión

- Vía de vuelta a postmarketOS v1.71 disponible fuera de Git, con manifiesto
  de hashes.
- Repositorio Ubuntu inicializado y documentado.
- Kernel, DTS, cinco drivers, 17 parches, fragmento de configuración, cmdline,
  bootconfig y DTBO no-op importados con procedencia y hash de origen.
- Dependencias del pipeline instaladas en la base de build WSL y comprobadas
  con `scripts/check-build-deps.sh`.
- `scripts/build-ubuntu-rootfs.sh` escrito: `mmdebstrap` arm64 con perfiles
  `minimal` y `desktop`, configuración aplicada dentro de la propia invocación
  y ningún paso manual posterior.
- Ninguna partición, tarjeta ni instalación física modificada.

### Siguiente paso

Ejecutar el primer rootfs `minimal`, adaptar el build de kernel y el
empaquetado Android v4 a este repositorio, y generar la primera imagen de
microSD y su ZIP TWRP con manifiesto de hashes.

---

## Sesión 2 — kernel propio, pipeline de imagen y primera release

Fecha: 2026-07-31. No se tocó la tablet física.

### El kernel validado no es el kernel del paquete Alpine

Al portar el build de kernel apareció una discrepancia que habría producido un
kernel distinto del validado si se hubiera copiado la lista de parches del
sitio equivocado:

| | build directa | APKBUILD |
|---|---|---|
| `ignore-console-null.patch` | **no** | sí |
| `set-mi2s-codec-dai-format.patch` | **sí** | no |

El `boot.img` que se flasheó y validó sale de la build directa. Es decir, el
kernel que arranca tiene el arreglo de formato/sysclk de los CS35L45 —por eso
suena el audio— y **no** tiene el parche de consola. Este port reproduce el
conjunto de la build directa y deja `ignore-console-null` tras
`APPLY_IGNORE_CONSOLE_NULL=1`, como build de diagnóstico explícita.

### Verificación contra la baseline

Construido desde este repositorio, con el checkout fijado en `a13c140c`:

| Salida | Resultado |
|---|---|
| `sm8550-samsung-gts9uwifi.dtb` | `952688174c…` — **idéntico** a v1.71 |
| `config` | `2c1eaeee…` — **idéntico** a v1.71 |
| `Image.gz` | distinto |

El DTB y la config son exactamente los validados, que es lo que fija la
descripción del hardware y el conjunto de funciones. `Image.gz` no coincide, y
la causa se midió en lugar de suponerse: mismo tamaño sin comprimir
(65.903.104 bytes), mismo release, mismo compilador y mismo banner, pero
7.003.750 bytes distintos. El desencadenante es `UTS_VERSION`: la baseline
llevaba `#18` y la nuestra `#1`, y ese carácter de más desplaza el enlazado.
Además, cada árbol de build genera su propia clave de firma de módulos.

### Identidad de build: un problema de privacidad, no solo de reproducibilidad

El banner del kernel empotraba `root@PC-ARTURO`, el nombre de la máquina de la
usuaria, y ese literal habría viajado dentro de cada `boot.img` publicado. El
build fija ahora `KBUILD_BUILD_USER=ubuntu`, `KBUILD_BUILD_HOST=gts9uwifi` y
un `SOURCE_DATE_EPOCH` derivado de la fecha del commit del kernel, y reinicia
`.version` en cada ejecución. Verificado sobre la imagen resultante: el banner
es `ubuntu@gts9uwifi` y no queda ningún identificador personal.

### Pipeline de imagen

Se escribieron los siete pasos descritos en `ubuntu-userspace.md`. Tres
decisiones merecen registro:

- `build-sd-image.sh` **falla la build** si el initramfs no es LZ4 legacy o no
  cabe en `init_boot` menos su footer AVB. Los dos son fallos que el port
  anterior descubrió en la tablet; aquí se descubren en el host.
- El instalador TWRP localiza el rootfs **por etiqueta**, no por
  `mmcblk1p2`, y exige `ID=ubuntu`. Activa unidades systemd con symlinks reales
  desde un manifiesto empaquetado, porque systemd ignora un fichero regular
  dentro de un directorio `.wants`.
- El fragmento vendor se normaliza a `mtime=0` antes de empaquetarlo, cerrando
  la laguna de reproducibilidad detectada en la sesión 1.

### Fin de línea

Los scripts sin extensión —el instalador TWRP y los de `packaging/`— quedaban
fuera de cualquier regla `.gitattributes` por extensión y se habrían escrito
con CRLF en el checkout de Windows, lo que hace que `#!/sbin/sh` no ejecute. El
repositorio fuerza ahora `eol=lf` para todo.

### Primera release: v0.1-minimal

El pipeline completo produjo su primer artefacto instalable. Cinco defectos
salieron a la luz al ejecutarlo, todos corregidos en los scripts y ninguno
parcheado a mano sobre el artefacto.

**1. Firmware Wi-Fi mal mapeado.** El overlay pedía `amss.bin` y `board-2.bin`,
nombres que no existen. Los ficheros reales son `official-amss.bin` y, para los
datos de placa, `official-board-2.bin` como contenedor más `qrd-board.bin` como
`board.bin`. El contenedor oficial no tiene entrada para la X910, así que
ath12k cae deliberadamente al ELF QRD — y `board.bin` faltaba por completo. El
overlay valida ahora todos los blobs por adelantado.

**2. `MODULES=dep` mira el host equivocado.** Hace que `initramfs-tools`
inspeccione el dispositivo raíz de la máquina que compila, que aquí es WSL, y
falla con «failed to determine device for /». `MODULES=most` es lo correcto y
sigue siendo diminuto: los únicos módulos instalados son los dos ath12k.
Faltaba además `/boot/config-<release>`, sin el cual `initramfs-tools` no puede
verificar el soporte de LZ4 — precisamente el único compresor admisible aquí.

**3. El initramfs no cabía.** 9,4 MiB frente a un presupuesto de 8,0 MiB. El
guardián de `build-sd-image.sh` lo detuvo en el host, que es su razón de ser.
Se midió antes de recortar: **cero módulos** en el initramfs, y 12 MiB de los
29,6 MiB sin comprimir eran `udev/hwdb.bin`, una base de datos de propiedades
de dispositivos que nunca se lee mientras se busca la raíz. El compresor no era
negociable, así que se recortó contenido: 25.212 KiB → 13.204 KiB en staging y
**7.123.964 bytes comprimidos, con 1,2 MB de margen**. Descubierto de paso:
`initramfs-tools` **omite en silencio** un hook que no sea ejecutable.

**4. Los nodos de partición del loop no aparecen solos.** En este entorno no
hay udev, así que `losetup --partscan` no garantiza `/dev/loopNpM`. El script
empuja al kernel, espera y cae a `kpartx`.

**5. El validador mentía.** Sin `unzip` instalado, todas las comprobaciones del
ZIP fallaban salvo la negativa —«el instalador nunca menciona particiones
prohibidas»—, que **pasaba** porque `grep` no encontraba nada en una entrada
vacía. Es el mismo patrón de mentira silenciosa que ya costó una comprobación
de dependencias falsa. Ahora una herramienta ausente aborta la validación. Las
otras dos comprobaciones también estaban mal planteadas: identificaban el
instalador por su prosa y hacían `grep` sobre los comentarios que documentan
justamente las particiones que promete no tocar. Se sustituyeron por una línea
de contrato explícita y por un análisis del código con los comentarios
eliminados, más una comprobación nueva de que solo escribe con `dd` y no
contiene ninguna orden de formateo.

Resultado, con las 21 comprobaciones estáticas en verde:

| Artefacto | SHA-256 |
|---|---|
| `ubuntu-24.04-gts9uwifi-v0.1-minimal-sd.img.xz` | `c68f2bb9…` |
| `ubuntu-24.04-gts9uwifi-v0.1-minimal-sm-x910-twrp.zip` | `f534a5a5…` |
| `boot.img` | `4b99e90e…` |
| `init_boot.img` | `cbeb5716…` |
| `vendor_boot.img` | `678a5ebb…` |
| `dtbo.img` | `c17418be…` |
| `vbmeta.img` | `b95e5ef9…` |

`dtbo.img` y `vbmeta.img` coinciden byte a byte con los de postmarketOS v1.71,
como debe ser: su contenido no depende de la distribución.

Imagen de microSD: 2.367.684.608 bytes sin comprimir
(`f399d509…`), 110 MB comprimida, con `UBTS9U_BOOT` de 256 MiB y `UBTS9U_ROOT`
de 2 GiB.

**Laguna conocida:** `init_boot.img` cambia de hash entre ejecuciones porque
`update-initramfs` no produce un CPIO reproducible. El resto del bundle sí lo
es. Queda pendiente normalizarlo, igual que se hizo con el fragmento vendor.

### v0.1 desktop y el fallo que habría arruinado la primera prueba

El perfil `desktop` construye 948 paquetes en 1,8 GiB. Comprobado dentro del
rootfs, no supuesto: GDM3 46.2, GNOME Shell 46.0, Mutter 46.2, PipeWire 1.0.5,
WirePlumber, Mesa 25.2.8 con `mesa-vulkan-drivers`, BlueZ 5.72, NetworkManager,
OpenSSH y el paquete de dispositivo. El pin de apt funcionó: **no** se coló
ningún `linux-image-*` de la distribución. `ssh`, `NetworkManager` y
`ubuntu-gts9u-grow-rootfs` quedan habilitados; `/etc/fstab` monta por etiqueta y
el usuario `ubuntu` está en `sudo`.

Antes de proponer una prueba física apareció un fallo que la habría hecho
fracasar por un motivo ajeno al hardware: **la cmdline heredada no lleva
`root=`**. El initramfs de postmarketOS localiza su partición por sí mismo, así
que su cmdline nunca lo necesitó. `initramfs-tools` no hace eso: habría
esperado a un dispositivo que no llega y habría caído a la shell de emergencia.

La cmdline de Ubuntu añade `root=LABEL=UBTS9U_ROOT rootfstype=ext4` —por
etiqueta, porque el orden de enumeración entre microSD y UFS no está
garantizado— y elimina dos parámetros arrastrados sin sentido aquí:
`pmos.nosplash` y `ignore_console_null`, cuyo parche este build no aplica. El
validador falla ahora si `root=` falta o si reaparece cualquiera de los dos.

Los artefactos construidos con la cmdline antigua se borraron en lugar de
dejarlos: no arrancan y su nombre no los distingue.

Release v0.1 (desktop), con todas las comprobaciones estáticas en verde:

| Artefacto | SHA-256 |
|---|---|
| `ubuntu-24.04-gts9uwifi-v0.1-sd.img.xz` | `5af2a7d2…` |
| `ubuntu-24.04-gts9uwifi-v0.1-sm-x910-twrp.zip` | `3a55399e…` |
| `boot.img` | `4b99e90e…` |
| `init_boot.img` | `a8252f1e…` |
| `vendor_boot.img` | `59a2e5c8…` |
| `dtbo.img` | `c17418be…` |
| `vbmeta.img` | `b95e5ef9…` |

Imagen sin comprimir: 3.588.227.072 bytes, `27a4f469…`.

`boot.img` es idéntico al del perfil mínimo, como debe ser: mismo kernel y mismo
DTS. `dtbo.img` y `vbmeta.img` coinciden byte a byte con los de postmarketOS
v1.71.

### v0.2: recuperación del panel y escritura de la microSD por TWRP

Se portó la recuperación cold-boot del ANA38407 antes de proponer la primera
prueba física, para que exista alguna posibilidad de imagen al primer intento.
El mecanismo no cambia respecto al port de referencia porque es propiedad del
hardware: el DDIC queda inalcanzable tras el hand-off de Samsung y solo el
ciclo `pm_test=platform` lo recupera. Se verificó que `CONFIG_PM_DEBUG=y` está
en el kernel construido, de modo que `/sys/power/pm_test` existirá.

Una diferencia deliberada: la unidad se activa en `multi-user.target`, no en
`graphical.target`. Aquel port siempre alcanzaba un display manager; aquí este
ciclo es también lo que hace visible la consola de texto, así que si GDM falla
conviene tener el panel vivo para poder ver por qué.

Comprobado en el rootfs construido, no supuesto: paquete `ubuntu-gts9u-device`
0.2 instalado, script ejecutable, unidad presente y **symlink de activación**
en `/etc/systemd/system/multi-user.target.wants/`.

La usuaria indicó que este PC no tiene lector de tarjetas, pero que la tablet
puede dejarse en TWRP con la microSD puesta. `scripts/twrp-write-sd.sh` escribe
la tarjeta por ADB: por defecto solo inspecciona, y escribir exige `--write`
más un `--device` explícito tras cinco guardas —dispositivo mmc completo,
`removable=1`, tipo `SD`, capacidad suficiente y nada montado— además de
confirmar que el aparato es un SM-X910 **en recovery**. Al terminar relee la
tarjeta y compara SHA-256 contra la imagen.

Release v0.2 (desktop), todas las comprobaciones estáticas en verde:

| Artefacto | SHA-256 |
|---|---|
| `ubuntu-24.04-gts9uwifi-v0.2-sd.img.xz` | `aebe0193…` |
| `ubuntu-24.04-gts9uwifi-v0.2-sm-x910-twrp.zip` | `8a1c37bf…` |
| `boot.img` | `4b99e90e…` |
| `init_boot.img` | `fa787e86…` |
| `vendor_boot.img` | `59a2e5c8…` |
| `dtbo.img` | `c17418be…` |
| `vbmeta.img` | `b95e5ef9…` |

Imagen sin comprimir: 3.588.227.072 bytes, `6e14f383…`. Los artefactos de v0.1
se retiraron para que no quede ambigüedad sobre cuál flashear.

### Siguiente paso

Primera prueba física. El objetivo es el Hito 2: systemd hasta
`multi-user.target`, journal persistente, Wi-Fi y SSH. La imagen y el panel
todavía no están validados bajo Ubuntu y no se declararán funcionales hasta
observarlos.

---

## Sesión 3 — primer arranque físico: Hitos 2 y 3 cumplidos

Fecha: 2026-07-31. Primera ejecución de Ubuntu en la tablet.

### Escribir la microSD sin lector de tarjetas

El PC de la usuaria no tiene lector, pero la tablet puede quedarse en TWRP con
la tarjeta puesta. `scripts/twrp-write-sd.sh` la escribe por ADB. Cuatro
defectos aparecieron solo contra el hardware real, y merecen quedar escritos:

1. **CRLF.** El `adb.exe` de Windows termina cada línea con CRLF, así que la
   detección de dispositivo anclada a fin de línea nunca casaba y el script
   informaba de que no había ninguno mientras estaba conectado.
2. **Desbordamiento a 32 bits.** Los tamaños se calculaban en la tablet, cuyo
   busybox hace aritmética de 32 bits: `sectores*512` daba la vuelta y una
   tarjeta de 29,7 GiB se mostraba como 1,72 GiB.
3. **`removable=0`.** El SD host de esta placa marca la tarjeta como no
   extraíble. Mi guarda exigía `removable=1` y habría rechazado el único
   destino válido. La señal decisiva es `device/type == SD`, más la
   comprobación de que la UFS interna existe aparte como `sda`.
4. **`dd` leyendo de una tubería perdió 42.688 bytes.** La tarjeta quedaba
   engañosamente convincente —GPT correcto, nombres de partición correctos,
   primer MiB idéntico— pero todo lo posterior al punto de pérdida había caído
   42.688 bytes antes de su sitio. Se localizó buscando una firma de la imagen
   dentro de la tarjeta. Solo la verificación de lectura lo detectó.

Se descartaron las hipótesis fáciles con pruebas: `adb exec-in` y `exec-out`
resultaron **binario-seguros** (4 MiB con 16.507 bytes LF llegaron idénticos),
así que el transporte estaba limpio. La escritura ahora prepara la imagen como
fichero en el disco RAM de la tablet, verifica esa copia contra el hash origen
y solo entonces ejecuta `dd` desde un fichero regular.

### El instalador TWRP, dos veces

El ZIP abortó con «no encontré `UBTS9U_ROOT`» sobre una tarjeta que la tenía.
Dos causas independientes:

- este TWRP **no tiene `blkid` ni `findfs`** ni `/dev/disk/by-label`. Sí tiene
  `tune2fs`, que lee el nombre de volumen ext4 directamente;
- el kernel seguía con la tabla de particiones anterior, así que los nodos `pN`
  apuntaban a los offsets de postmarketOS y cualquier filesystem sobre ellos
  parecía corrupto.

La corrección de eso introdujo un tercer fallo, más sutil: el instalador releía
la tabla y buscaba **inmediatamente después**. Releer borra y recrea los nodos
de partición, así que la búsqueda caía en esa ventana y no encontraba nada,
mientras el mensaje de error impreso instantes después listaba la partición que
acababa de no encontrar. Código idéntico, resultados opuestos, solo el momento
cambiaba. Ahora busca primero y solo relee si hace falta.

Desde entonces, el script de reconstrucción **extrae las funciones reales del
ZIP empaquetado y las ejecuta en la tablet** antes de pedir un flasheo.

### Primer arranque

Funcionó. Confirmado por la usuaria: pantalla, GPU, táctil, botones, batería,
suspensión con la funda, USB host y salida de vídeo por USB-C, con y sin
alimentación externa.

**La recuperación del panel quedó validada bajo Ubuntu**, con la firma exacta
del port de referencia en el journal:

```
ana38407 panel id: 00 00 00
  -> ciclo pm_test=platform ->
ana38407 panel id: 80 00 04
```

No funcionaban: sonido, Bluetooth ni rotación automática.

### Una sola causa raíz para sonido y sensores

El ADSP estaba `offline`. `qcom_q6v5_pas` tiene `auto_boot=true` y pide
`qcom/sm8550/adsp.mdt` a los ~3 s, cuando la microSD que lo contiene todavía no
está montada: falla con `-ENOENT` y se queda apagado para siempre.

Arrancarlo después de `local-fs.target` funciona, PAS acepta la imagen firmada
de Samsung, y aparecen dos cosas a la vez: la tarjeta ALSA y `/dev/fastrpc-adsp`,
que es el prerequisito de los sensores.

Ubuntu ya empaqueta pd-mapper como **`protection-domain-mapper`**, así que no
hubo que compilarlo; solo ordenarlo tras el arranque tardío del DSP, o no
encuentra remoteproc y systemd se rinde.

Con el perfil UCM del port de referencia, **PipeWire expone «Built-in speakers
(4x CS35L45)» y los micrófonos digitales de forma nativa, sin PulseAudio**.
Eso responde una de las preguntas abiertas del diseño de userspace. La usuaria
confirmó audio audible tras un reinicio, sin intervención.

### Bluetooth: mi servicio colgó el arranque

La dirección de la NVM del WCN7850 es nula, así que `hci0` arranca como
`00:00:00:00:5A:AD` y queda `DOWN`. Leerla de EFS (`ro,noload`) y aplicarla con
`btmgmt` la levanta — verificado en vivo, el controlador pasó a `UP RUNNING`.

Pero como servicio de arranque falló, y el fallo fue mío: **`btmgmt` de BlueZ
5.72 se bloquea indefinidamente si corre antes de que el controlador esté
registrado en la interfaz de gestión**, que es exactamente cuando corre este
servicio. Se midió: `btmgmt info` estuvo más de cuatro minutos parado y, al
estar el servicio ordenado antes de `bluetooth.service`, se llevó por delante
toda la pila. El mismo comando responde en menos de un segundo una vez el
controlador está registrado. `hciconfig` en cambio es un ioctl y responde en
3 ms.

El servicio acota ahora cada llamada con `timeout` y sondea con `hciconfig`.
Pero al reintentarlo apareció un problema distinto y más profundo.

### Bluetooth: el firmware no se descarga tras un reinicio en caliente

```
QCA Product ID   :0x00000019
QCA SOC Version  :0x40170200
QCA ROM Version  :0x00000200
QCA Patch Version:0x000043fb
QCA controller version 0x02000200
QCA Downloading qca/hmtbtfw20.tlv
command 0xfc00 tx timeout
QCA Failed to send TLV segment (-110)
```

El controlador **responde correctamente** a todas las consultas de versión y
solo se atasca en la descarga masiva del firmware. Es decir: el UART funciona,
el fichero se encuentra, y aun así el TLV no pasa. El driver reintenta tres
veces y se rinde.

Lo que distingue los arranques observados:

| Arranque | Tipo | Resultado |
|---|---|---|
| 1º | en frío, tras flashear desde TWRP | firmware cargado, `hci0` alcanzó `5A:AD` y subió |
| 2º–4º | `systemctl reboot` en caliente | `tx timeout` a los 3,6 s, tres reintentos, se rinde |

La recuperación por software está descartada con evidencia: `rfkill`
block/unblock no cambia nada, y un unbind/rebind del serdev deja el
controlador aún peor —tras él falla incluso la lectura de versión.

Hipótesis actual, pendiente de confirmar con un apagado completo: el lado
Bluetooth del WCN7850 compartido necesita un ciclo de alimentación real, que un
reinicio en caliente no proporciona. No se declara nada hasta medirlo.

### Estado al cerrar la sesión

Suben solos desde arranque en frío, verificado sin tocar nada: recuperación del
panel, ADSP, pd-mapper y audio. Bluetooth queda intermitente y la rotación
automática sin abordar, porque necesita `hexagonrpcd` y `libssc`, que no
existen en Ubuntu.

---

## Sesión 4 — Bluetooth cerrado, rotación empaquetada, y un kernel de escritorio

Fecha: 2026-08-01.

### Bluetooth: dos comportamientos de `btmgmt`, ninguno documentado

El servicio funcionaba a mano y fallaba como servicio. Fueron dos trampas
encadenadas de BlueZ 5.72, ambas medidas:

1. **Ordenado antes de `bluetoothd`, `btmgmt` se bloquea en `epoll_wait`**
   durante minutos. Como la unidad estaba `Before=bluetooth.service` —copiando
   al port de referencia— se llevó por delante toda la pila: 90 s de timeout
   por arranque. Con el demonio ya arriba, la misma llamada tarda 0 s. Este
   port ordena el servicio **después**, al revés que la referencia.
2. **Con stdin en `/dev/null`, `btmgmt` no imprime nada y sale con 0.** Es lo
   que systemd da por defecto a un servicio. No falla: miente. El `grep` sobre
   su salida vacía no casaba nunca y el bucle de espera se agotaba. Con una
   tubería vacía se comporta con normalidad.

Un tercer detalle: el servicio informaba de fallo cuando había funcionado.
Aplicar la dirección reinicializa el controlador, así que releerla un segundo
después mostraba la antigua. Ahora sondea.

Resultado verificado desde arranque en frío: `48:BC:…`, `UP RUNNING`,
`Powered: yes`, servicio completado en 1,3 s. Escaneo de 10 s: 20 dispositivos.
A2DP sigue sin probar.

También quedó **refutada** la hipótesis del ciclo de alimentación: un apagado
completo no cambia nada. El `command 0xfc00 tx timeout` del primer intento de
descarga de firmware es intermitente y el propio driver se recupera en el
reintento. No era el problema.

### `apt install firefox`, `chromium` y `fastfetch`

Tres síntomas, dos causas.

La grande es sistémica: **este port no instala árbol de módulos**, así que todo
lo que quede en `=m` está ausente. `CONFIG_SQUASHFS=m` significa que ningún
snap puede montarse, y en Ubuntu `chromium` y `firefox` son paquetes de
transición cuyo único trabajo es instalar un snap. Lo mismo explicaba
`systemd-binfmt.service` y `proc-sys-fs-binfmt_misc.mount` fallando en cada
arranque y dejando el sistema en `degraded`: `CONFIG_BINFMT_MISC=m`.

Se añadió un fragmento de configuración propio, separado del heredado para que
ese siga siendo comparable con su origen: `SQUASHFS` y sus cinco
descompresores, `OVERLAY_FS`, `FUSE_FS`, `BINFMT_MISC`, exFAT, NTFS3, y
AppArmor con `apparmor` en `CONFIG_LSM` **conservando `lockdown`**, del que
depende el emparejamiento kernel/módulos firmados.

El guard del build rechazó tres errores antes de compilar:
`SQUASHFS_DECOMP_MULTI_PERCPU` vive dentro de un `choice` y no se fija
directamente; `NTFS3_FS` solo puede ser módulo mientras el driver NTFS antiguo
esté habilitado; y la lista de fragmentos era una cadena separada por espacios
en un repositorio cuya ruta **contiene espacios**.

`fastfetch` es distinto: simplemente **no existe en el archivo de Ubuntu
24.04**. No es un fallo de configuración.

### Rotación: tres paquetes que Ubuntu no tiene

Los sensores viven dentro del ADSP y se alcanzan por FastRPC, así que
`iio-sensor-proxy` de Ubuntu no tiene nada que leer. Se compilan `libssc`
0.4.4, `hexagonrpcd` 0.4.0 y `iio-sensor-proxy` 3.9 con `-Dssc-support`.

Dos cosas que Ubuntu impuso y que la lista de dependencias de Alpine no
anticipaba: `libssc` exige meson ≥ 1.4 y noble trae 1.3.2, y el `pkg-config`
de `qmi-glib` arrastra `mbim-glib` y `protoc`.

Un error de diseño corregido a tiempo: la primera versión compilaba **dentro
del rootfs que se distribuye**, lo que habría puesto `build-essential`, meson y
las cabeceras de desarrollo en la tablet. Ahora usa un chroot arm64 desechable.

Y un hueco que solo apareció al inspeccionar el `.deb`: **upstream hexagonrpc
no trae ninguna unidad systemd** —Alpine las añade con un parche de
distribución— así que el drop-in del port apuntaba a un servicio inexistente.
La unidad se escribe aquí, con `Conflicts=suspend.target` y el usuario
`fastrpc` que su propia regla udev necesita.

### Un falso negativo propio

Al comprobar si `snapd` estaba en el rootfs usé una variable en un comando en
línea. Este entorno se las come, así que estaba inspeccionando el **host de
build, no el rootfs**, y concluí erróneamente que sí estaba. La comprobación
desde un fichero de script confirmó lo contrario. `snapd` y el userspace de
AppArmor se declaran ahora explícitamente en lugar de depender de
`Recommends`.

### Release v0.6

Verificado sobre el rootfs construido, no supuesto: los cuatro paquetes locales
instalados, **`iio-sensor-proxy` enlazando contra `libssc.so.2`** según `ldd`,
el usuario `fastrpc` creado, las seis unidades con sus symlinks de activación,
y `snapd`, `squashfs-tools` y AppArmor 4.0.1 presentes.

| Artefacto | SHA-256 |
|---|---|
| `ubuntu-24.04-gts9uwifi-v0.6-sd.img.xz` | `f3c8a6c5…` |
| `ubuntu-24.04-gts9uwifi-v0.6-sm-x910-twrp.zip` | `d061a856…` |
| `boot.img` | `744aab41…` |
| `init_boot.img` | `a27a5370…` |
| `vendor_boot.img` | `59a2e5c8…` |

Imagen sin comprimir: 3.721.396.224 bytes, `3f92ddda…`.

**Este ZIP hay que flashearlo**: el kernel cambió, y `boot` y los módulos
ath12k forman un conjunto firmado bajo lockdown.

### Pendiente de comprobar en hardware

Que la cadena compile e instale no prueba que la rotación funcione. Falta ver
si Mutter 46 de Ubuntu sufre las dos carreras del bloqueo de rotación que el
port de referencia corrigió con un parche propio; se dejó fuera a propósito,
para portarlo solo con evidencia.

---

## Sesión 5 — la cadena de sensores, eslabón a eslabón

Fecha: 2026-08-01. `apt install chromium` y `firefox` quedaron confirmados por
la usuaria: el arreglo de `CONFIG_SQUASHFS=y` era la causa.

La rotación se recorrió midiendo cada eslabón —ADSP → `/dev/fastrpc-adsp` →
`hexagonrpcd` → SSC → `libssc` → `iio-sensor-proxy` → Mutter— en lugar de
suponer dónde fallaba. Aparecieron cuatro problemas distintos.

### 1. Falta una dependencia de ejecución

`ssccli` e `iio-sensor-proxy` morían con
`error while loading shared libraries: libqmi-glib.so.5`. El paquete `libssc`
no declaraba `libqmi-glib5`. Añadida, todos los símbolos resuelven.

### 2. El árbol HexagonFS quedaba un nivel demasiado profundo

El tarball anida todo bajo `sensor-hexagonfs/` y el port de referencia lo
extrae con `--strip-components=1`. Este port lo omitía, y `hexagonrpcd`
reportaba `Could not open /../sns_reg_version: No such file`.

Esto importa además porque el parche de Samsung reasigna el mapeo de
`/sensors/registry/` a `/sensors/`, de modo que el árbol debe tener `dsp`,
`sensors` y `socinfo` en su raíz.

### 3. La aridad declarada de `apps_std_fwrite` no coincide con este firmware

Al hacer el árbol escribible apareció:

```
Invalid number of input numbers: 8 (expected 12)
```

El listener exige `4 * (in_nums + in_bufs + out_bufs)`. El parche declara
`fwrite` como `(2, 1, 2, 0)` → 12 bytes; el firmware envía 8, que son dos
palabras: `in_nums=1` más la palabra de tamaño que aporta el único búfer de
entrada. Eso coincide además con el manejador, que lee
`struct { uint32_t fd; uint32_t buf_size; }`, porque con `in_bufs=1` la palabra
siguiente a `fd` **es** el tamaño de ese búfer.

Corregido a `(1, 1, 2, 0)` en `packaging/sensors/fix-fwrite-arity.patch`.
Verificado en hardware: desaparecen tanto el error de aridad como los de
permiso, y `sns_reg_version` **se escribe** —su fecha pasa de 1970 a la hora
actual conservando sus 10 bytes—. La ruta de escritura funciona.

### 4. Frente abierto: el DSP pide una interfaz que no existe

Con todo lo anterior corregido, el daemon vive **104 ms** y sale con estado 0.
El intercambio completo es:

```
Starting hexagonrpcd (INIT_ATTACH_SNS) on /dev/fastrpc-adsp
Could not find local interface sns_registry
Unsupported handle: 4294967295
```

El firmware de sensores pide al AP una interfaz local llamada `sns_registry`.
`hexagonrpcd` solo ofrece tres —`apps_mem`, `apps_std` y `remotectl`— y la
palabra `sns_registry` no aparece en ninguna parte de su código, ni siquiera
con el parche de Samsung. Al no encontrarla, el DSP invoca sobre el handle de
error `0xFFFFFFFF` y cierra la sesión.

Hechos establecidos, para no repetir el trabajo:

- **No es un problema de permisos.** Ejecutado como root desaparecen los
  `Permission denied` y el comportamiento final es idéntico.
- **No es fatal por sí mismo.** Tanto `Unsupported handle` como
  `Could not find local interface` devuelven un error al DSP y el listener
  continúa; lo que termina la sesión es que el DSP la cierra.
- **El ADSP y el audio sobreviven.** El intento no provoca SSR: la tarjeta
  ALSA sigue presente después.
- El árbol correcto hace que el DSP llegue **más lejos**, no menos: con el
  árbol mal extraído el daemon vivía indefinidamente porque nunca alcanzaba
  este punto.

### Un aviso

Durante el diagnóstico se ejecutó el daemon como root y truncó
`sns_reg_version` a 0 bytes al abrirlo para escritura. Se detectó y el árbol se
restauró desde la copia limpia del overlay de build, verificando que recupera
sus 10 bytes. Conviene no ejecutar ese daemon como root sobre un árbol que
importe.

### Estado

Rotación: sigue sin funcionar. Tres defectos reales corregidos y el cuarto
caracterizado con precisión. Todo lo demás del dispositivo sigue igual.

## Autorrotación: resuelta

La traza completa de FastRPC cerró el caso. Se compiló un `hexagonrpcd` de
diagnóstico con la opción de meson `hexagonrpcd_verbose`, que registra cada
llamada que el firmware de sensores hace contra el sistema de ficheros. El
binario no se instala: es solo para depurar.

### Lo que se vio

Con el árbol HexagonFS bien extraído, escribible por el usuario `fastrpc` y con
la aridad de `fwrite` corregida, la traza pasó de 3 líneas a **757**:

```
openat($ADSP_LIBRARY_PATH, /vendor/etc/sensors/sns_reg_config) -> 2
read(2, 512) -> 329
...
openat(..., /mnt/vendor/persist/sensors/registry/registry/../sns_reg_version) -> 3
write(3, 10) -> 10
opendir(/mnt/vendor/persist/sensors/registry/registry) -> 3
readdir(3) -> lsm6dso_0_platform.ff.config
readdir(3) -> lsm6dso_0.gyro
...
```

El `write(3, 10) -> 10` es la prueba directa de que el parche de aridad
funciona: el DSP consigue por fin actualizar la versión del registro, y a
partir de ahí recorre entero el directorio de configuración de sensores. La
petición de `sns_registry` que cerraba la sesión no vuelve a aparecer: era
consecuencia de que el DSP nunca completaba la carga del registro, no una
interfaz que hiciera falta implementar.

`ssccli --sensor accelerometer` devuelve entonces medidas reales:

```
Accelerometer sensor measurement: X=0.440279 Y=-0.062213 Z=9.757931 m/s²
```

9,76 m/s² en Z con la tablet en horizontal: es la gravedad.

### El cuarto obstáculo: una etiqueta udev que upstream no pone

Con el acelerómetro leyéndose, `iio-sensor-proxy` seguía diciendo
`No accelerometer` mientras sí reconocía la brújula y la luz ambiental. La
causa está en la regla que trae el propio `iio-sensor-proxy`:

```
SUBSYSTEM=="misc", KERNEL=="fastrpc-adsp*", ENV{IIO_SENSOR_PROXY_TYPE}+="ssc-light ssc-compass"
```

Los cuatro drivers SSC (`ssc-accel`, `ssc-light`, `ssc-compass`,
`ssc-proximity`) están compilados, pero cada uno solo mira dispositivos que
lleven su etiqueta. `ssc-accel` no aparece en ninguna regla, así que
`drv-ssc-accel` nunca recibe un dispositivo que examinar. No es un problema del
X910 ni de Ubuntu: le pasa a cualquier dispositivo cuyo acelerómetro viva
detrás del DSP.

La corrección va en `61-gts9u-sensor-mount-matrix.rules`, junto a la matriz de
montaje que ya tocaba ese mismo nodo. `IIO_SENSOR_PROXY_TYPE` es una lista
separada por espacios construida con `+=`, de modo que el orden respecto a la
regla `80-` de upstream es indiferente.

Tras aplicarla:

```
IIO_SENSOR_PROXY_TYPE=ssc-accel ssc-light ssc-compass
Found SSC accelerometer at /sys/devices/virtual/misc/fastrpc-adsp
=== Has accelerometer (orientation: undefined, tilt: undefined)
{'HasAccelerometer': <true>, ...}
```

La orientación sale `undefined` con la tablet en horizontal, que es la
respuesta correcta: con la gravedad en Z no hay orientación de pantalla que
deducir.

### Verificación desde arranque en frío

Reiniciada la tablet, sin ninguna intervención manual:

| | |
|---|---|
| `pd-mapper` | active |
| `hexagonrpcd-adsp-sensorspd` | active, 1 proceso vivo |
| `iio-sensor-proxy` | active |
| etiqueta udev | `ssc-accel ssc-light ssc-compass` |
| acelerómetro | 9,76 m/s² en Z |
| tarjeta ALSA | presente |

El daemon ya no muere a los 104 ms: se mantiene sirviendo el árbol.

### Los cuatro obstáculos, en orden

1. **Árbol HexagonFS extraído un nivel de más** — faltaba
   `--strip-components=1`. El DSP no encontraba nada.
2. **Árbol de solo lectura para el daemon** — el firmware necesita escribir la
   caché del registro; sin eso abandona.
3. **Aridad de `apps_std_fwrite` mal declarada** — `(2,1,2,0)` exige 12 bytes de
   entrada y este firmware envía 8. Corregido a `(1,1,2,0)`.
4. **Etiqueta udev `ssc-accel` inexistente** — `iio-sensor-proxy` nunca
   consideraba el nodo FastRPC como acelerómetro.

Ninguno era específico de Ubuntu; los cuatro son defectos reales del camino
genérico, y las cuatro correcciones viven en el repositorio.

### Efecto colateral que conviene conocer

Reiniciar el ADSP por `remoteproc` con el sistema arrancado deja el sistema
**sin tarjeta de sonido**: los servicios de audio no vuelven a registrarse
solos. Un reinicio del sistema la recupera. Durante el diagnóstico se reinició
el ADSP varias veces; se comprobó después del reinicio que la tarjeta
`Samsung-Galaxy-Tab-S9-Ultra` vuelve a estar presente.

## Autorrotación: la causa raíz, y por qué el port de referencia no la sufría

Los parches de `rename` y del búfer del listener son correctos y necesarios
para que el DSP *pueda* reconstruir el registro. Pero la pregunta buena era
otra: por qué lo reconstruye, si postmarketOS usa el mismo `hexagonrpcd` 0.4.0
con un único parche y allí la rotación funciona.

La respuesta estaba escrita en el propio generador del árbol del port de
referencia, `stage-stock-sensor-hexagonfs.sh`:

> Samsung's registry service uses this zero-length file as the completion
> marker and the companion JSON as a per-input timestamp cache. Omitting either
> makes the DSP rebuild the registry through a temp.json + rename sequence.

Dos ficheros gobiernan todo:

- `sensors/registry/sensors_registry`, de longitud cero, marca el registro como
  completo;
- `sensors/registry/sns_reg_config` es un caché que guarda, para cada JSON de
  `sensors/config`, la fecha que tenía cuando se generó el registro.

El árbol se construye con **todas las fechas normalizadas a la época**, así que
el caché guarda `"data": "0"`. El DSP compara ese valor contra el `stat()` de
cada JSON: si no coincide, reconstruye.

Nuestro overlay era correcto —los dos ficheros presentes, fechas a cero—, pero
el instalador TWRP escribe cada fichero con `unzip -p > destino`, que no
conserva ninguna fecha. En la tablet los JSON acababan con la hora del reloj de
la recovery, julio de 2025, y el caché decía cero. De ahí la reconstrucción en
cada arranque, y con ella la petición de `sns_registry` que cerraba la sesión.

### La corrección

`ubuntu-gts9u-sensor-registry.service`, un `oneshot` ordenado antes de
`hexagonrpcd`, normaliza las fechas del árbol a la época y le devuelve la
propiedad al usuario `fastrpc`. Se hace en el lado Ubuntu y no en el
instalador a propósito: aquí hay `coreutils` de GNU y `touch -d @0` se comporta
igual siempre, mientras que el `busybox` de TWRP varía; y además repara un
árbol que haya quedado a medio reconstruir por un intento anterior.

### Verificación desde arranque en frío

| | |
|---|---|
| `hexagonrpcd-adsp-sensorspd` | active, 1 proceso |
| acelerómetro | X=8.55 Y=0.00 Z=4.84 m/s², módulo 9.82 con la tablet inclinada |
| `AccelerometerOrientation` | `normal` |
| `AccelerometerTilt` | `tilted-up` |
| tarjeta ALSA | presente |

Sin intervención manual y sin reconstruir el registro.

### Qué queda de los dos parches

Siguen en el repositorio y siguen siendo correctos: sin ellos, cualquier
reconstrucción del registro —por un árbol recién generado, por una fecha que se
descuadre, por un JSON nuevo— muere en la primera entrada. Con ellos, la
reconstrucción se completa entera. Lo que no arreglan es la etapa siguiente,
`sns_registry`, y por eso conviene no llegar a necesitarla.

---

## Sesión 6 — el STM32 de la funda EF-DX920 responde al alimentarlo

Fecha: 2026-08-02.

### Corrección de una conclusión anterior: no es `i2c-gpio`

La primera lectura del fragmento `stm32@2a` vio las propiedades
`stm32,sda_gpio = <&tlmm 72 ...>` y `stm32,scl_gpio = <&tlmm 106 ...>` y dedujo
que el MCU usaba un bus bit-bang. Era incorrecto. La tabla `__fixups__` del
mismo DTBO contiene la asociación decisiva:

```
qupv3_se15_i2c = "/fragment@70:target:0";
```

El fragmento 70 es `stm32@2a`. En mainline el controlador es `i2c15`, y su
pinctrl upstream ya asigna exactamente GPIO72/106 a `qup2_se7`. Crear además
un `i2c-gpio` habría hecho competir dos maestros por las mismas líneas.

El DT stock también separa el booster: `kbd_boost@18` está en
`qupv3_hub_i2c4`, no en SE15, y `stm32,booster_power_models` solo contiene
`0xf9` y `0xd3`. EF-DX920 aparece como modelo `0xd6`, de modo que el primer
bring-up puede omitir el MAX77816 con respaldo documental.

### Prueba física reversible de alimentación

El kernel arrancado expone GPIO chardev v2, aunque las herramientas de Ubuntu
24.04 solo hablan v1. Se escribió una sonda temporal que usa directamente los
ioctl v2, sin modificar el rootfs ni ninguna partición. Sobre el TLMM principal
aplicó la secuencia del DT Samsung:

- GPIO10=1: VDDO;
- GPIO12=0: BOOT0/SWCLK;
- GPIO13=1: reset liberado.

Al cabo de 100 ms GPIO62 (`irq_conn`) empezó a mostrar actividad periódica y
GPIO75 (`irq_gpio`) produjo también una transición. Al cerrar los descriptores
los GPIO quedaron liberados. La prueba anterior con los tres pines muertos no
refutaba el cableado: el MCU estaba sin alimentar. Esta medida confirma VDDO y
las líneas de control, pero todavía no confirma teclas; eso exige SE15.

### Fuentes GPL y primer driver mainline

Se importaron 19 ficheros de la implementación V3 desde la publicación oficial
`SM-X910_EUR_16_Opensource.zip`, verificando primero el SHA-256 del archivo.
Quedan intactos bajo `kernel/vendor/samsung-stm32-pogo/` con un
`SHA256SUMS`. No se importó firmware binario.

Portar sin cambios las 11.652 líneas downstream arrastraría `sec_class`, MUIC,
notificadores Android, `msm-bus` y la ruta FOTA. Para el modelo real se escribió
un subconjunto mainline pequeño que conserva el protocolo observado en las
fuentes Samsung:

- cabecera de tres bytes y eventos por IRQ activa baja;
- modelo `0xd6` / EF-DX920;
- eventos de teclado de 16 bits: keycode Linux en bits 0..14 y press en bit 15;
- estado del LED Caps Lock en la siguiente cabecera;
- evento Hall del MCU traducido a `SW_LID` (`2` abierto, cualquier otro valor
  cerrado).

El DTS nuevo habilita QUPv3 SE15 a 400 kHz, el regulador con GPIO10 y las cuatro
líneas de control/IRQ exactas. El controlador queda built-in, como todos los
proveedores de este port. También se añade `CONFIG_GPIO_CDEV_V1=y` para que las
herramientas libgpiod 1.6 de Noble dejen de dar falsos `Invalid argument`.

### Estado al terminar esta entrada

El kernel compiló correctamente con el driver built-in y el DTB resultante
contiene `keyboard@2a` bajo `i2c15`, el regulador VDDO y los cuatro GPIO
esperados. `llvm-nm` confirmó también el registro estático del driver.

Al empaquetar v0.8 apareció una regresión del entorno: `sgdisk --zap-all`
escribía el archivo y quedaba bloqueado para siempre dentro de `sync(2)`, en
`super_lock`. Se reprodujo con una imagen nueva de solo 16 MiB y se localizó la
syscall exacta con `strace`; no era un fallo del layout. La creación de la GPT
del archivo recién recreado se cambió a `sfdisk`, manteniendo los offsets,
tipos y etiquetas. La regla de limpiar una microSD física con
`sgdisk --zap-all` antes de escribirla permanece intacta.

La release v0.8 terminó con todas las validaciones estáticas aprobadas:

- ZIP TWRP: SHA-256
  `35a48756961bb5c72eb207af6a3a5981a868add3c49108fe74a98b936ba17652`;
- imagen SD comprimida: SHA-256
  `a24ce5f3fbc1b246311af046ad4e8876f9d87ffe34ffb4ab72a26a6febe1e093`.

Nada se ha flasheado y el driver todavía no puede marcarse funcional. La
siguiente evidencia exigida es que `i2c15` sondee `0x2a`, aparezca el
dispositivo de entrada y las pulsaciones físicas generen eventos correctos sin
regresiones en audio, Wi-Fi, rotación ni suspensión.

Como línea base previa a la instalación se consultó la v0.7 por SSH: kernel
`7.2.0-rc3-dirty`, GDM activo, ninguna unidad fallida y, como era esperable en
esa versión, ni `i2c-15` ni `15-002a` presentes en sysfs.

---

## Sesión 7 — v0.8 en hardware: recuperación del rootfs y diagnóstico del pogo

Fecha: 2026-08-02.

### La pantalla negra no era una regresión de arranque

El ZIP v0.8 se instaló desde TWRP con todos sus hashes correctos, pero el primer
reinicio quedó con el panel negro y sin red. Se descartó expresamente un gadget
USB llamado `postmarketos`: pertenecía a otro dispositivo conectado al PC, no
a la X910 que ejecuta Ubuntu.

`/proc/last_kmsg` solo alcanzaba `ExitBootServices`; no contenía panic. El
journal persistente de la microSD dio la causa exacta: `systemd-fsck-root`
terminó con código 4 por una inconsistencia inesperada y varios inodos sin
enlazar, y systemd entró en `emergency.target`. El panel negro ocultó el prompt
y simuló un fallo anterior al kernel.

Desde TWRP se ejecutó una reparación explícita sobre la partición Ubuntu:
`e2fsck -f -y` recuperó tres inodos pequeños en `lost+found` y corrigió los
bitmaps y contadores. Una segunda pasada `e2fsck -f -n` terminó con código 0.
Tras reiniciar, la tablet arrancó v0.8 con GNOME y Wi-Fi activos. El rootfs está
montado desde la microSD como ext4 `rw,noatime,errors=remount-ro`.

Para que un rootfs sucio no vuelva a presentarse como una regresión del kernel,
el instalador TWRP pasa ahora `e2fsck -p` **antes** de montarlo en lectura y
escritura. Solo continúa si el sistema estaba limpio o si se corrigieron errores
seguros automáticamente; cualquier código más grave aborta antes de escribir
las particiones y pide una reparación manual. La validación estática del ZIP
comprueba que esta guarda siga empaquetada.

### Lo que v0.8 demuestra y lo que no

El driver sondea en el controlador dinámico `i2c-5` (`89c000.i2c`; el número no
es el alias de hardware), registra `Book Cover Keyboard Slim (EF-DX920)` como
dispositivo I²C de entrada y anuncia `connected=0, data-ready=0`. Eso prueba el
enlace del driver, no teclas funcionales. Una captura de `evtest` no recibió
eventos y el contador de la IRQ de datos GPIO75 permaneció a cero.

Una sonda reversible, con el driver y el regulador liberados y restaurados al
salir, aplicó VDDO=1, BOOT0=0 y NRST=1. GPIO62 pasó a detectar la funda y a
oscilar en reintentos de aproximadamente dos segundos; GPIO75 se mantuvo alto.
El MCU ve la conexión física pero nunca anuncia un paquete.

La relectura completa del driver GPL de Samsung encontró dos omisiones en la
v0.8. Primero, el stock usa GPIO62 en ambos flancos como máquina de estados:
enciende VDDO al conectar, espera 50 ms, habilita GPIO75 activa baja y revierte
todo al desconectar. Segundo, el MAX77816 de `qupv3_hub_i2c4` sí es necesario:
la lista de modelos solo controla un ajuste posterior, mientras que la rutina
de encendido de la salida se ejecuta siempre. Escribe `0x03 = 0x70` y
`0x02 = 0x8e`. En v0.8 dicho bus está deshabilitado, por lo que la lógica del
STM32 arranca pero la alimentación reforzada de la funda no.

### Siguiente iteración

La v0.9 debe implementar la IRQ de conexión y la secuencia de potencia del
stock, habilitar `i2c_hub_4` y programar el MAX77816 con un driver built-in.
Solo se considerará funcional tras observar pulsaciones reales en `evtest`;
la mera aparición del dispositivo de entrada no basta.

---

## Sesión 8 — v0.9: el STM32 arranca y aparece el input real del EF-DX920

Fecha: 2026-08-02.

### Una primera regresión real y su corrección

La primera v0.9 habilitó `i2c_hub_4` en PIO. Ese controlador reclamó TLMM4/5 y
el ADSP dejó de sondear porque `6800000.remoteproc` usa las mismas líneas en su
pinctrl. Se restauró inmediatamente el `boot` v0.8 y se rehízo SE4 con GPI DMA,
igual que el SE3 ya validado para el SM5440. También se retiró del nodo ADSP la
propiedad de pinctrl que no debe poseer un bus delegado a GPI. En el siguiente
arranque el ADSP volvió a `running` y desapareció el conflicto de GPIO.

SSC no apareció en ese arranque. Para no atribuirlo al teclado se hicieron dos
controles negativos. Primero se desregistraron en vivo tanto `6-002a` como
`990000.i2c`, se reinició el ADSP y se sondeó SSC doce veces: siguió devolviendo
`SSC QMI Service not found`. Después se arrancó de nuevo el `boot` v0.8 limpio
y se esperó la ventana completa del servicio: tampoco aparecieron sensorspd ni
el acelerómetro. Por tanto es la intermitencia ya conocida de SSC, no una
regresión de SE4; al terminar se restauró la v0.9.

### Alimentación correcta, aplicación muda

El driver pasó a gestionar GPIO62 en ambos flancos con 250 ms de debounce,
GPIO75 como nivel bajo, VDDO y el MAX77816. En vivo se leyeron sus registros:
`CONFIG1=0x8e`, `CONFIG2=0x70` y tensión por defecto `0x23`; las escrituras sí
llegaban. Aun así, la dirección de aplicación `0x2a` seguía en NACK y GPIO75 no
generaba IRQ. El input dejó de registrarse en `probe`: ahora solo se crea tras
recibir el modelo exacto `0xd6`, evitando que GNOME desactive la autorrotación
por un teclado fantasma.

El código Samsung aportó la siguiente prueba decisiva. Antes de usar la
aplicación siempre entra en el bootloader I²C del STM32, valida el firmware y
vuelve al flash principal. Se reprodujo solo la parte de lectura:

- bootloader ROM en `0x51`: accesible;
- product ID: `0x0460`, el esperado por Samsung;
- versión en `0x08000200`: `00 34 00 34`;
- imagen oficial `keyboard_stm/stm32_gts9family.bin`: `00 37 00 37`, 52.132
  bytes, SHA-256
  `1b48d88c23523ae205cd960e6d42725268638a15a47d8a5e52854eb01108caa3`.

Se añadió un actualizador explícito, accesible solo por root. Rechaza cualquier
tamaño o versión inesperados, borra solo las 31 páginas que borra Samsung
(conserva la última), programa en bloques de 256 bytes y relee/compara el blob
completo. Con la tablet cargando y al 89 %, la actualización terminó sin un
solo byte distinto. Un reinicio confirmó la versión `00 37 00 37`. Los option
bytes leídos después fueron `aa fe ff fe`: RDP nivel 0 y bit 24 ya borrado, de
modo que no hizo falta escribirlos.

### Causa final del silencio

El firmware nuevo todavía quedaba mudo porque nuestro driver hacía un segundo
reset justo después de activar VDDO/MAX77816. Esa hipótesis procedía de una
lectura incompleta: Samsung resetea al salir del bootloader, **antes** de la
conexión, pero su `stm32_keyboard_start()` solo alimenta, espera 50 ms y
habilita la IRQ; no vuelve a resetear. Al eliminar ese reset adicional, el
primer arranque produjo:

```
STM32 bootloader reachable, product id 0x460, flash version 00 37 00 37
keyboard attached, model 0xd6 (EF-DX920)
EF-DX920 protocol confirmed; input enabled
```

`/proc/bus/input/devices` y `evtest` muestran el dispositivo I²C Samsung
`04e8:a035` con `EV_KEY`, `EV_LED/LED_CAPSL` y `EV_SW/SW_LID`. Desconectar la
funda lo elimina y reconectarla lo vuelve a registrar. El paquete inicial
`0x7fff` queda fuera del rango de keycodes, igual que en el parser bypass de
Samsung; se ignora. La tecla se había dejado pulsada antes de alimentar el
teclado y el firmware no reporta transiciones anteriores, así que falta una
pulsación física nueva para elevar la fila a soporte completo.

### Reproducibilidad

El firmware propietario no entra en Git. `stage-stock-pogo-firmware.sh` lo
toma del vendor oficial ya extraído y comprueba el SHA-256 fijado; el overlay
lo instala bajo `/lib/firmware/keyboard_stm/`. El paquete
`ubuntu-gts9u-device` 1.2 añade una unidad oneshot que solicita la actualización
solo con el blob exacto, al menos 50 % de batería y alimentación externa. Si la
versión ya es `00 37 00 37`, el driver no escribe nada. La imagen instalada en
vivo quedó de nuevo en la v0.9 y Wi-Fi/SSH, audio, GPU, táctil y DSI se
comprobaron presentes.

La release completa v0.9 también se construyó desde cero: 985 paquetes, paquete
de dispositivo 1.2 y unidad pogo habilitada dentro de la imagen SD. Se montó la
imagen terminada en solo lectura para comprobar esos tres datos. El ZIP superó
todas las validaciones estáticas y contiene el firmware STM32 de 52.132 bytes
con el hash fijado. Artefactos finales:

- imagen SD comprimida: SHA-256
  `fdeaf00cd5d64f9e0b16d39f9a9f1914a4e8a4fa59824e80fef680e6d1186eab`;
- ZIP TWRP: SHA-256
  `5477e23cd9c1884237b7171c6dafbd4271eca1e7c39ad06f150f7ab2a1187c16`;
- `boot.img` ejecutado en la tablet: SHA-256
  `f77de14e484b83bb31ead3e557e10d441b87e8c92e5f05c84d48600ba24e4ffe`.

---

## Sesión 9 — inicialización completa de la aplicación y sondeo descartado

Fecha: 2026-08-02.

### La capa de aplicación sí queda inicializada

Las pulsaciones físicas nuevas se observaron simultáneamente con `evtest`, el
contador de la IRQ GPIO75 y el journal. No apareció ningún `EV_KEY` y el
contador permaneció inmóvil. Esto corrige la conclusión provisional de la
sesión anterior: el input es real y dinámico, pero las teclas aún no funcionan.

La comparación con `stm32_check_ic_work()` de Samsung reveló la fase que
faltaba después del anuncio `0xd6`. Se portaron sus lecturas de versión, modo,
CRC y versión del accesorio, junto con los tres reintentos I²C del stock. En un
arranque limpio el hardware respondió exactamente:

```
application initialized: version 04 01 05 01, mode 1,
  CRC cd 0b f7 cf, accessory 09 00 ff 00 00 00
```

El valor `ff 00` indica que no hay controlador de touchpad, como corresponde a
la funda Slim. Aun con esta inicialización correcta, nuevas pulsaciones no
activaron GPIO75 ni entregaron eventos. Una consulta manual devolvió la
cabecera de keypad con payload `ff ff`, marcador de que no había tecla
pendiente. Consultas posteriores compitieron con el driver y causaron
NACK/`-EPROTO`; no deben repetirse con el cliente enlazado.

### Sondeo periódico: regresión y retirada inmediata

Para separar una IRQ ausente de una cola de eventos válida se construyó un
sondeo de 20 ms dentro del propio driver, protegido por el mismo mutex. Solo se
escribió `boot`; copia, backup y partición se verificaron por SHA-256. El nuevo
boot sí alcanzó el sistema real, aunque el Wi-Fi no asoció hasta que se reinició
una vez. El journal posterior aportó la causa para retirar el experimento:
`i2c i2c-6: Transfer while suspended`, con la pila apuntando al trabajo de
sondeo. Una tarea de 20 ms no puede tocar SE15 mientras el sistema suspende.

Se retiró de inmediato y se recompiló un kernel que conserva solo la
inicialización probada.
El `boot.img` de recuperación resultante tiene SHA-256
`17e7feaaca18cddbdd39c41bb2f477c0164482af26a40f0c86fdeb236d722f58`.
Tras un reinicio manual, la tablet recuperó Wi-Fi/SSH y se escribió únicamente
ese `boot` por UFS. No fue necesario TWRP.

Como control externo, la misma funda EF-DX920 se probó en One UI: las teclas
funcionaron correctamente y cerrar la tapa apagó la pantalla. El hardware y los
contactos quedan descartados como causa general; el bloqueo es propio de la
secuencia mainline.

---

## Sesión 10 — primeras teclas reales y recuperación de rebotes del STM32

Fecha: 2026-08-02.

### La temporización de Samsung era funcional, no cosmética

La comparación fina con `stm32_dev_int_proc()` y `stm32_check_ic_work()` mostró
que Samsung no mantiene la IRQ GPIO75 enmascarada durante toda la inicialización.
Lee VERSION de forma síncrona cuando recibe el anuncio `0xd6`, sale del handler
y programa el resto 10 ms después. La primera reproducción que dejó MODE, la
espera de 200 ms, CRC y accesorio dentro del handler atascó DATA y produjo
timeouts `-110`. Al separar ambos pasos como el stock, GPIO75 volvió a reposo y
la aplicación respondió de forma consistente.

Reproducir también el flanco de desconexión de Samsung —liberar estado y cortar
VDDO cuando GPIO62 baja, restaurarlo si vuelve a subir antes de los 250 ms—
desbloqueó por fin el teclado. Una captura física de `evtest` midió press y
release de `U`, `I`, `T`, `H`, `W`, `E`, `F`, espacio y retroceso. El contador de
GPIO75 subió a la vez. Esto descarta definitivamente GNOME, evdev, el mapa de
teclas y el firmware como causa del silencio anterior.

### Por qué alguna tecla quedaba pulsada y luego moría el teclado

La primera build con teclas utilizó `boot.img` SHA-256
`25e0b8f6a58f7104649f7eb16f0bede7de0b40aa3ebacbaf40a5105677702838`.
Durante escritura real GPIO62 rebotó en ambos sentidos y el STM32 reinició. Si
eso ocurría con una tecla baja, el micro perdía el estado y nunca enviaba su
release. Además el driver solo hacía VERSION/MODE/CRC en el primer anuncio;
después conservaba el input pero omitía el handshake en los reanuncios. El
resultado visible era una tecla pegada seguida de un teclado sin respuesta.

La iteración `f33516674b910b5853f9fc3a9aaa94ac67069242cdcbadb4af73c8ae0cfb2243`
liberó todas las teclas antes de cortar VDDO y repitió el handshake en cada
`0xd6`. Eliminó la retención, pero una prueba física acabó con un modelo espurio
`0xff`, DATA afirmada y un `-ETIMEDOUT` cada ~4,4 s sin recuperación. La captura
había usado antes `evtest --grab`; mientras estuvo activo GNOME no podía recibir
las teclas. Las capturas posteriores retiraron `--grab`.

El kernel actualmente instalado, `boot.img` SHA-256
`171d335e9609be33387c915e8c7997b4fb884f0842b34abcf7b888d4bb31da2e`, añade
la ruta de error del stock: ignora `0xff`, libera todo el bitmap y pulsa NRST
durante 3 ms tras agotar los reintentos I²C. En un arranque limpio superó un
rebote temprano, repitió el anuncio `0xd6` y terminó con versión
`04 01 05 01`, modo 1, CRC `cd 0b f7 cf`, DATA inactiva y sin nuevos timeouts.
Dos ventanas posteriores de 40 y 90 segundos no recibieron actividad física;
el estado permaneció estable, pero la validación final de escritura sostenida
sigue explícitamente pendiente y no se marca todavía como soporte completo.

### La traza conjunta reveló una lectura espuria de una cola vacía

Con una tecla mantenida físicamente se habilitaron únicamente los tracepoints
del adaptador I²C 6 y las IRQ 186/187. La secuencia fue determinista: anuncio
`0xd6`, VERSION y varios paquetes keypad válidos; después llegaba otra IRQ 186,
la escritura de la cabecera `[03 00 01]` tenía éxito, pero la lectura de la
cabecera expiraba con `-110` tras unos 0,9–1,0 s. Los reintentos devolvían `-6`,
GPIO62 generaba la IRQ 187 y VDDO entraba en un ciclo de alimentación. El patrón
reaparecía cada 2–3 s.

La causa era la adaptación a `IRQF_TRIGGER_FALLING`: solucionó la pérdida de
pulsos breves del modo level-low, pero el handler leía sin comprobar si DATA
seguía afirmada. El ISR de Samsung sí retorna cuando la línea activa-baja ya ha
subido. Se conservó el flanco descendente y se añadió esa comprobación antes de
cualquier transacción. También se retiró el watchdog experimental de 3 s: una
tecla legítimamente mantenida no demuestra un stream bloqueado y no debe
reiniciar la aplicación.

Se compiló y escribió solo `boot` con backup y verificación SHA-256. El nuevo
`boot.img` es
`5e3d577d81c6a74f11b55476555c3d4e37e387e332f6d50a21075900cdcc755b`;
el anterior
`4b1e3637781081fc5fae9e108422dbca8864713f48f97df577f3a26c45471640`
quedó como rollback temporal. En vivo, durante seis minutos con carga física,
los contadores permanecieron en `connection_high=0`, `connection_low=0`,
`recoveries=0`; una IRQ ya desactivada quedó registrada en
`data_irq_deasserted=1` y no produjo ningún timeout. Es evidencia fuerte de que
la tormenta de alimentación quedó corregida. Aún falta la prueba final de
escritura variada por la dueña, por lo que el estado continúa en amarillo.

---

## Sesión 11 — la estabilidad a 400 kHz no sobrevivía al reinicio

Fecha: 2026-08-02.

La usuaria confirmó que el teclado había funcionado con varias teclas a la vez
y también tras desconectarlo y conectarlo, pero al reiniciar volvió a ser
irregular. Era exactamente el mismo `boot.img`, por lo que se compararon los
arranques en vez de atribuirlo al filtro de IRQ.

En el arranque malo el driver recibió cientos de eventos reales, pero acumuló
decenas de flancos GPIO62, NACK `-6`, errores `-71`, timeouts GENI y varias
destrucciones/recreaciones de `event3`. Una captura pasiva terminó con
`No such device` justo cuando GPIO62 permaneció bajo más de 250 ms. El filtro
de IRQ vacía sí hacía su trabajo —los descartes crecían sin causar reset—, pero
había además fallos en transacciones con DATA realmente activa.

### Autosuspend descartado

El controlador `89c000.i2c` usa autosuspend de 250 ms y las fases fallidas
mostraban retardos del mismo orden. Se forzó temporalmente
`power/control=on`, se verificó el estado `active` y se reinicializó solo el
driver pogo. GPIO62 siguió pulsando y las teclas volvieron a detenerse. La
prueba fue reversible, se devolvió el controlador a `auto` y no se conservó
ningún parche de userspace.

### SE15 a 100 kHz

Se cambió únicamente `clock-frequency` de I2C15 de 400 kHz a 100 kHz. El driver
y `boot` permanecieron idénticos. Se construyó y escribió solo `vendor_boot`,
con copia y verificación SHA-256:

- nuevo: `1313836dd22c120f7c2bb82a7ec45fba0de1e057e2b6691cb2e453d1bbdef6ba`;
- anterior: `fb31f91ebb9959400a5110607353148e63f7017f7ba03616e21dcbbe6dc653ba`.

El árbol vivo confirmó `clock-frequency=100000`. En el primer arranque hubo un
ciclo inicial, el handshake terminó correctamente y una tecla física `ESC`
llegó al input. Los 36 muestreos siguientes durante tres minutos quedaron
idénticos, sin timeout ni recuperación. Se reinició de nuevo con el teclado
conectado y el resultado se repitió. Finalmente se hizo un unbind/bind solo del
driver: recreó `event3`, recibió de nuevo la tecla física y permaneció otros
tres minutos sin nuevos GPIO62 ni resets. La frecuencia queda como corrección
reproducible de v0.10; falta que la dueña valide escritura variada al volver.

Una tercera prueba de reinicio, ya con la corrección instalada de forma
persistente, fue todavía más limpia: el firmware anunció `0xd6`, completó
VERSION/MODE/CRC al primer intento y creó `event3` con
`connection_high=0`, `connection_low=0` y `recoveries=0`. Antes de ese reinicio,
57 muestras durante nueve minutos habían permanecido idénticas. El objeto sobre
el teclado produjo un `ESC` físico, pero no sustituye la prueba manual de varias
teclas y reconexión que sigue pendiente.

La release reproducible v0.10 se generó desde el commit `5403cd7`. Sus artefactos
son `ubuntu-24.04-gts9uwifi-v0.10-sd.img.xz` (SHA-256
`8380a22336e4a6b5c8a9e713e105fd1807fc3346930d87662d07f7753fb3aa40`)
y `ubuntu-24.04-gts9uwifi-v0.10-sm-x910-twrp.zip` (SHA-256
`895c2f8a526d0bc234490c917349f87d48f739367cc1e74ece634db7ade233fc`).

---

## Sesión 12 — los pulsos DATA deben clasificarse en el hard-IRQ

Fecha: 2026-08-03.

La prueba manual pendiente invalidó la conclusión fuerte de la sesión anterior:
las teclas seguían quedándose pulsadas aunque conectar/desconectar la funda y la
aparición de la autorrotación funcionasen correctamente. En nueve minutos de
escritura, los diagnósticos midieron 174 IRQ DATA, 104 transiciones de tecla,
17 IRQ descartadas por DATA inactiva, 18 flancos bajos GPIO62 y cuatro resets de
recuperación. El journal contenía `-110` y `-6`. Durante una captura pasiva
posterior de 60 segundos, ya sin actividad física, todos los contadores quedaron
inmóviles. Esto separa el fallo de la ruta de attach/detach y del userspace.

La guarda añadida en la sesión 10 se ejecutaba dentro del handler threaded. Ese
instante es demasiado tarde para un GPIO que emite pulsos cortos: un flanco
válido puede haber vuelto a alto mientras el paquete correspondiente permanece
en la cola, por lo que se perdía una transición —especialmente el release—. A
la vez, retirar la guarda por completo ya había demostrado que una IRQ pendiente
obsoleta sondea la cola vacía y provoca un timeout.

Se mantuvo `IRQF_TRIGGER_FALLING | IRQF_ONESHOT`, pero se añadió un handler
primario que lee GPIO75 con `gpiod_get_value()` en contexto hard-IRQ. Solo si el
nivel lógico activo sigue presente devuelve `IRQ_WAKE_THREAD`; las pendientes
ya inactivas se contabilizan y terminan sin I²C. El kernel compiló y se escribió
solo en `boot`, con SHA-256
`93e39902057b515017bb705fc6076fc9a35d212eafb35960afd5c054387d0d23` y rollback
verificado `5e3d577d81c6a74f11b55476555c3d4e37e387e332f6d50a21075900cdcc755b`.
El primer arranque y un unbind/bind recrearon `event3` con cero recuperaciones;
faltan transiciones físicas sostenidas para confirmar la corrección.

### Confirmación física y persistencia

La prueba manual sostenida confirmó la hipótesis. Durante más de ocho horas el
driver contabilizó 2.046 transiciones reales de tecla y terminó con
`keys_down=0`; la dueña pudo escribir con normalidad, usar varias teclas y
desconectar y reconectar físicamente la funda sin volver a dejar una tecla
pulsada ni perder el teclado. De 2.099 IRQ DATA, 12 pendientes ya inactivas se
descartaron en el hard-IRQ sin iniciar I²C. Hubo dos recuperaciones durante el
asentamiento inicial y una recuperación aislada de SE15 a los 16 minutos, pero
el driver rehízo el handshake por sí solo y las siguientes reconexiones fueron
limpias; no hubo degradación visible durante las horas posteriores.

Se reinició la tablet con la funda conectada para descartar que el éxito
dependiese del rebind de la sesión de prueba. El kernel volvió a crear
`Book Cover Keyboard Slim (EF-DX920)` desde el arranque, completó
VERSION/MODE/CRC y recibió otras 61 transiciones físicas con `keys_down=0`.
Una recuperación temprana por `-110` rehízo automáticamente la aplicación y no
impidió el funcionamiento. El árbol vivo siguió exponiendo SE15 a 100.000 Hz y
los hashes de las particiones coincidieron con los payloads reproducibles:

- `boot`: `93e39902057b515017bb705fc6076fc9a35d212eafb35960afd5c054387d0d23`;
- `vendor_boot`: `1313836dd22c120f7c2bb82a7ec45fba0de1e057e2b6691cb2e453d1bbdef6ba`.

En ese momento la evidencia parecía suficiente para pasar el teclado a soporte
completo. La sesión siguiente demostró que esa conclusión fue prematura: no se
publicó la v0.11.

---

## Sesión 13 — la estabilidad prolongada tampoco sobrevivió al reinicio

Fecha: 2026-08-03.

Tras la ventana de más de ocho horas y un primer reinicio correcto, la usuaria
reinició de nuevo y las teclas volvieron a quedar retenidas; después el teclado
dejaba de responder. Se compararon las particiones y el árbol vivo: `boot`,
`vendor_boot` y `clock-frequency=100000` eran idénticos. El arranque estable
había enlazado de nuevo el driver a los 272 s y se asentó hacia los 363 s; el
arranque malo lo hizo a los 3 s y acumuló NACK `-6`, timeouts `-110`, resets y
pulsos GPIO62. Un rebind aislado no garantizó reproducir el estado bueno. La
diferencia es de estado frío/temporal del STM32 o del transporte, no de una
imagen distinta.

Se revisó el controlador real de Samsung
`drivers/i2c/busses/i2c-msm-geni.c`, no solo el driver común más pequeño. Tres
diferencias están respaldadas por el fuente oficial del SM-X910:

- el DT usa DATA por nivel bajo + ONESHOT;
- el contador GENI de 100 kHz es `{7, 10, 11, 26}` y mainline usaba
  `{7, 10, 12, 26}`;
- ante timeout Samsung envía `M_CMD_CANCEL` y solo aborta si cancelar falla.

La primera prueba con nivel bajo, sin los otros cambios, recibió 109
transiciones en 60 s pero terminó con cuatro recuperaciones y errores
`-6/-110`. Añadir únicamente el contador Samsung mejoró otra captura a 57
transiciones y una recuperación, pero apareció el evento corrupto `0x6767` y
persistieron dos NACK y un timeout. Ninguna variante se declaró corregida.

Se construyó después una variante limpia que añade el cancel-before-abort. Su
`boot` tiene SHA-256
`f3c6a4235e7dcea8e82ce510861eae3eb145e04ff5594005a0e7a42d3ca158d8` y arrancó
correctamente; en reposo hizo el handshake completo, aunque registró dos NACK
tempranos. Una captura de 60 s sin pulsaciones físicas no cambió ningún contador
y, por tanto, no valida el teclado.

Finalmente se observó otra diferencia del driver oficial: cada intento de
lectura fallido notifica RESET a los consumidores y libera las teclas antes de
reintentar. El driver propio solo las liberaba tras agotar los tres intentos,
lo que explicaba que una pulsación quedase visible varios segundos. Se añadió
la liberación inmediata conservando el reset físico únicamente tras agotar los
reintentos. Esta última variante está compilándose y queda pendiente de
escritura sostenida, reinicio y reconexión; la release vigente continúa siendo
v0.10 y el teclado permanece en amarillo.

---

## Sesión 14 — la recuperación tardía era también una carrera SSC/GNOME

Fecha: 2026-08-03.

La variante final de la sesión anterior compiló correctamente. Su `boot.img`,
SHA-256
`df98bc12b74b84db65b2cb2c4bd669fb10d28b498773692e2e2db336be6f03fa`,
añade la liberación inmediata tras cada lectura fallida sobre el nivel bajo,
timing Samsung y cancel-before-abort ya descritos. Se escribió únicamente
`boot`, con copia y hash remoto verificados; el rollback es
`f3c6a4235e7dcea8e82ce510861eae3eb145e04ff5594005a0e7a42d3ca158d8`.

Antes de escribirlo se encontró una segunda anomalía independiente. El arranque
malo tenía `iio-sensor-proxy` cerca del 100 % de CPU y
`irq/16-smp2p-adsp` cerca del 90 %, mientras el kernel repetía
`Handover signaled, but it already happened` cada ~233 ms. Detener el proxy
necesitó el timeout completo de 90 s y SIGKILL. Tras un rebind seguro del pogo,
una captura física entregó 432 transiciones en 60 s, combinaciones incluidas,
con `keys_down=0`, cero recuperaciones y cero errores.

La primera interpretación —que la tormenta fuese la causa raíz del teclado—
era demasiado fuerte. El boot anterior que funcionó ocho horas también había
acumulado 139.497 handovers. Sí es una regresión real: ocupa dos núcleos y
coincide con timeouts del DPU y GENI, pero solo puede considerarse un agravante
del transporte pogo.

La cronología localizó la carrera. El helper arrancaba antes de LightDM/GDM,
consultaba SSC y creaba un proxy antes de que GNOME fuese consumidor. Las
pruebas de no reiniciar `hexagonrpcd`, esperar 75 s y observar ventanas fijas de
4 s fallaron: el periodo silencioso del cliente variaba y la tormenta aparecía
solo después de que el display manager quedara desbloqueado. No repetir esos
retardos ciegos.

La solución reproducible ordena `ubuntu-gts9u-sensors-resume.service` después
del display manager. Tras obtener una medida real de acelerómetro inicia un
cliente limpio y vigila el IRQ de handover cada dos segundos durante 30 s. En
el arranque limpio `55a9406e-d2e8-4d54-9a87-f75ecb7066b5` detectó 3 IRQ en 2 s,
mató solo el primer proxy y abrió otro. El segundo superó toda la vigilancia;
una medida posterior de 10 s dio delta 0, `iio-sensor-proxy` consumía 45 ms de
CPU y la carga bajó a 0,74. No se reinició el ADSP ni se perdió audio.

En ese mismo arranque el pogo se inicializó desde frío sin rebind manual,
errores ni recuperaciones y quedó en `keys_down=0`. Eso valida la reproducción
del estado de arranque, no la escritura: la dueña estaba ausente y aún debe
probar varias teclas, reconexión física y uso sostenido. La release pública
sigue siendo v0.10 hasta completar esa validación sobre la candidata v0.11.

---

## Sesión 15 — la pantalla negra era modo emergencia, no la pantalla

Fecha: 2026-08-03.

La dueña informó de que, tras un reinicio, la tablet se quedaba en negro y no
acababa de arrancar. La entregó en TWRP.

### El diagnóstico, y una lectura equivocada por el camino

Montada la raíz en solo lectura, el journal activo mostraba un arranque que
alcanzaba `time-set`, `network` y `nss-lookup` y después callaba dieciséis
minutos. Se concluyó que systemd se colgaba antes de `basic.target`. **Era
falso.** Ese fichero contenía solo el tramo final del arranque; el principio
estaba en un journal rotado, y la propia línea `Startup finished in 12.706s
(kernel) + 15.085s (userspace)` lo desmentía.

Con todos los `system*.journal` descargados y leídos con `journalctl -D`
apareció la secuencia real:

```
systemd-fsck-root.service: Failed with result 'exit-code'
Failed to start systemd-fsck-root.service
Reached target emergency.target - Emergency Mode
```

El sistema arrancaba bien y se detenía en modo emergencia porque el `fsck` de
la raíz encontraba errores que no podía corregir sin supervisión. Nunca se
alcanzaban `multi-user` ni `graphical`, de ahí que no hubiera GDM ni imagen.

Lección: no diagnosticar un arranque con un único fichero de journal.

### La reparación

`e2fsck -fn` mostró daño rutinario —dos inodos sueltos, diferencias de bitmap y
contadores libres— con los pases 2 y 3 limpios, es decir, estructura de
directorios intacta. `e2fsck -fy` lo corrigió: `Filesystem state: clean` y
arranque normal. Cinco ficheros acabaron en `lost+found`; los cinco resultaron
ser texto y bases GVariant de caché, nada del port.

### La causa raíz, en el repositorio

`build-sd-image.sh` creaba la raíz con `-O ^has_journal`. Sin journal, cada
apagado sucio deja daño, y con `Errors behavior: Continue` ext4 sigue adelante
en vez de remontar en solo lectura, así que el daño se acumula invisible. La
imagen ahora se crea con journal y `-e remount-ro`; en la tarjeta viva se
aplicó `tune2fs -e remount-ro`.

### El teclado, después de la reparación

La dueña avisó de que el teclado había dejado de funcionar. Se descartó primero
la hipótesis obvia y equivocada: `e2fsck` no se llevó el firmware, que sigue en
`/lib/firmware/keyboard_stm/stm32_gts9family.bin` con sus 52.132 bytes.

El estado real:

```
attached=1 model=0x00 connected=1 data_ready=0
connection_high=129 connection_low=130
cannot restore keyboard power: -108
```

El ID de protocolo no llega —`model=0x00` donde antes `0xd6`—, la línea de
conexión ha rebotado 259 veces y el elevador se reactiva cada 2,1 s
indefinidamente. El driver enlazó a los 3,7 s.

Esto **coincide con el patrón ya descrito en las sesiones 11 y 13**: los
arranques malos enlazan pronto y acumulan pulsos de GPIO62, los buenos enlazan
tarde. No es un fallo nuevo ni consecuencia de la reparación.

Como agravante, la batería estaba al 10 % y 3.716 mV, y el MAX77816 que
alimenta el teclado cuelga de ella; el propio servicio de firmware se aplazó
solo por ese motivo. Queda pendiente repetir la medida con carga suficiente
antes de tocar el driver.

### Defectos del driver anotados, no corregidos

- El reintento de alimentación no tiene freno: reactiva el elevador cada 2 s
  para siempre, sin espaciado ni rendición.
- `samsung_pogo_enable_power` emite un backtrace del kernel al fallar. Un fallo
  de alimentación previsible no debería generar un WARN.

### Cabo suelto: v0.11 no tiene artefactos

La tablet arranca un `boot.img` `df98bc12…` construido en la sesión 14 que no
corresponde a ninguna release empaquetada: `artifacts/` llega hasta v0.10. Hay
un kernel en el dispositivo que no es reproducible desde una release. Antes de
seguir con el teclado conviene cerrar v0.11 o volver a v0.10.

## Sesión 16 — qué cambió desde que el teclado funcionaba: nada nuestro

Fecha: 2026-08-04.

La dueña informó de que el teclado había dejado de funcionar y pidió comparar
con el estado bueno. Tres hipótesis se descartaron con evidencia, no por
opinión.

**La batería, no.** Se había apuntado que 10 % y 3.716 mV podían impedir que el
MAX77816 sostuviera el MCU. La dueña recordó que había funcionado al 15–20 %, y
un arranque limpio al 39 % reprodujo el fallo idéntico. Descartada.

**El firmware del MCU, no.** `ubuntu-gts9u-pogo-firmware.service` se aplazó en
**todos** los arranques registrados, incluido uno al 91 %. Nunca escribió en el
STM32, así que no pudo corromperlo.

**Los cambios de esta sesión, no.** La reparación del sistema de ficheros no
tocó nada del pogo —el firmware sigue en su sitio con sus 52.132 bytes— y el
manejador del botón de encendido solo lee `event0` del `pmic_pwrkey`.

### Lo que sí es

El patrón coincide con lo descrito en las sesiones 11 y 13: los arranques malos
enlazan el driver pronto —aquí a los 3,7 s— y acumulan pulsos de GPIO62 sin que
llegue el ID de protocolo. `model=0x00` donde el estado bueno da `0xd6`.

Novedad respecto a la sesión 14: **el rebind ya no recupera el estado bueno**.
Un ciclo completo unbind, 8 s de espera y bind volvió a dejar 12 activaciones
del elevador en 25 s y ningún dispositivo de entrada. La recuperación que allí
funcionó no es fiable.

### Una diferencia medida, de interpretación abierta

El driver lee cuatro bytes de la flash del STM32 por el comando de lectura del
bootloader. En el arranque que funcionó valían `00 37 00 37`; en todos los que
fallan, `00 34 00 34`, de forma consistente y reproducible.

No se afirma que sea la causa. Es una lectura de memoria por el mismo enlace
I²C que se sospecha marginal, y difieren en un solo nibble, lo que encaja igual
de bien con una lectura corrupta que con un contenido distinto. Queda anotado
como el único discriminante duro encontrado entre ambos estados, y merece
comprobarse leyendo varias veces seguidas antes de construir nada encima.

### Defectos confirmados y pendientes

El reintento del elevador sigue sin freno: en un arranque llegó a 788
activaciones. Se detuvo con un unbind reversible. La corrección —espera
creciente con tope, contador reiniciado al enganchar o al desconectar— está
especificada y **no aplicada**, porque tocar el driver obliga a compilar,
escribir `boot` y reiniciar, y antes hay que cerrar el cabo suelto de v0.11.

## Sesión 17 — v0.11 cerrada, y el teclado apunta a la flash del MCU

Fecha: 2026-08-04. Sesión desatendida, con autorización explícita de la dueña
para escribir `boot`, `init_boot`, `vendor_boot`, `dtbo` y `vbmeta`.

### v0.11 cerrada

Construida con `KERNEL_CLEAN=1`. Antes de sobrescribir nada se respaldaron las
cinco particiones en `artifacts/backup-preV011/`, incluido el `boot.img`
`df98bc12…` de la sesión 14, que no existía en ninguna release y es el kernel
con el que la dueña vio el teclado funcionar mejor.

Se escribieron con `dd` en vez de con el ZIP: `twrp install` derriba adb y no
volvió la vez anterior, lo que en una sesión desatendida dejaría el dispositivo
sin forma de reiniciarse. Cuatro particiones verificadas leyendo de vuelta.
`vbmeta` copió cero bytes —es de solo lectura en este TWRP, ya documentado— y
quedó intacta; la que hay es la que lleva arrancando siempre.

No se reescribió la microSD: la dueña tiene datos y snaps instalados, y v0.11
no necesitaba rootfs nuevo. Sí hubo que reemplazar a mano los dos módulos
`ath12k` firmados, que viven en la tarjeta y no en el ZIP; sin eso, kernel
nuevo con módulos viejos deja el Wi-Fi fuera y con él el acceso por SSH.

Arranque verificado: sistema `running`, cero unidades fallidas, Wi-Fi con los
módulos nuevos, audio, sensores y el manejador del botón activos.

Pendiente de honestidad: que el build limpio sea **reproducible** no está
demostrado. Haría falta una segunda build limpia idéntica. Lo que sí está
demostrado es que el incremental no lo era.

### El teclado: el bootloader responde, la aplicación no

`event_poll`, el gancho de diagnóstico del propio driver, provocó
`read_retry_releases=9` sobre `manual_polls=3`: tres reintentos por sondeo, y
ninguna respuesta. El MCU no contesta al protocolo del teclado ni preguntándole
directamente.

En cambio su bootloader contesta perfectamente en cada arranque, leyendo el
product id `0x460` y las option bytes sin un solo error.

Eso separa las dos mitades: **bootloader vivo, aplicación muda**, y reencuadra
la diferencia de flash ya observada. Donde el arranque bueno leía
`00 37 00 37`, todos los malos leen `00 34 00 34`, de forma consistente. Si
esos bytes son contenido real y no una lectura corrupta, la aplicación del
teclado está dañada en la flash del STM32.

Encaja con todo lo observado: el bootloader responde, la aplicación no; ningún
reinicio ni rebind lo recupera; y la dueña describe que antes **sí enganchaba**
y solo fallaba a medias con teclas pegadas, mientras que ahora no engancha en
absoluto. Son fallos distintos, no el mismo agravado.

### Lo que no se ha hecho, y por qué

El driver expone `firmware_update` y el blob de Samsung está en la tarjeta con
sus 52.132 bytes, así que reprogramar el MCU es posible. **No se ha hecho.** La
autorización de la dueña cubría las particiones de arranque de la tablet,
enumeradas una a una; reescribir la flash de un accesorio es otra cosa,
potencialmente irreversible, y el propio servicio de firmware está escrito para
aplazarse solo salvo condiciones seguras. Queda como la acción recomendada,
pendiente de que ella la autorice.

Antes de reprogramar conviene confirmar que los cuatro bytes de versión son
estables: leerlos varias veces seguidas y comprobar que siempre dan
`00 34 00 34`. Si bailan, son lecturas corruptas y la hipótesis cae.

## Sesión 18 — autorrotación estable y auditoría completa de V34

Fecha: 2026-08-04.

### Sensores: dos carreras distintas

Se hizo reproducible el arreglo que la dueña confirmó físicamente para la
autorrotación. `iio-sensor-proxy` ya no reclama SSC demasiado pronto y el
servicio `hexagonrpcd` queda ordenado después de la recuperación cold-boot del
panel. Además, el parche de `qcom_q6v5` enmascara la IRQ de handover una vez
completada: una medida de diez segundos quedó en `1 -> 1`, sin la tormenta que
antes ocupaba CPU y contendía con display e I2C. El sensor de luz SSC roto se
excluye del proxy; no se presenta como brillo automático funcional.

### Se volvió exactamente al último driver pogo conocido bueno

Se retiraron los experimentos de las sesiones posteriores y
`kernel/drivers/samsung_stm32_pogo.c` quedó idéntico al commit `504ff29`. El
estado bueno histórico `df98bc12…` no pudo compararse limpiamente en vivo
porque no levantó ninguno de los canales de control; no se convirtió esa
ausencia de red en una conclusión sobre el teclado.

El journal downstream de Samsung mostró que su propio driver también observa
el ciclo CONN alto, VDD/MAX activos durante unos dos segundos, CONN bajo y
apagado. Por tanto el periodo de ~2,126 s no nace del debounce mainline: es el
estado de fallo que comunica la aplicación del accesorio.

### El salto ROM no era la inicialización que faltaba

Sin escribir la flash se añadió temporalmente el comando STM32 ROM
`GO 0x08000000`. El bootloader lo aceptó. Se repitió con VDDO y MAX77816 ya
activos y 100 ms de estabilización; también lo aceptó. En ambos casos la
aplicación mantuvo `model=0x00`, DATA bajo y el mismo pulso de CONN. El
experimento se eliminó por completo y no forma parte de la fuente final.

### Volcado de solo lectura: V34 es una aplicación real

Una herramienta temporal reclamó exclusivamente BOOT0/NRST, entró al ROM y
usó únicamente `READ MEMORY` sobre I2C6. Leyó los 64 KiB y restauró el arranque
normal sin enviar ERASE, WRITE ni UNPROTECT. Resultado:

```
bytes=65536
sha256=8937281d2efa08400390f9a2b02e40ca914b634e646d6dd544980c38464533ef
version_0x200=00 34 00 34
0037_offsets=
```

La imagen tiene vectores ARM coherentes y cadenas que dicen
`TabS9(STM32G0) Series -> V34`. No existe una segunda V37 escondida. La
conclusión de la sesión 17 —flash posiblemente dañada— queda refutada: One UI
usa V34, y Ubuntu todavía no reproduce alguna parte de su inicialización fría.

Como defensa adicional, el updater exige ahora la guarda explícita
`GTS9U_ALLOW_POGO_FLASH=YES`. No se ha escrito el MCU y no se escribirá sin una
autorización específica.

El `boot.img` final de esta iteración, con el driver pogo devuelto a `504ff29`
y la corrección q6v5, tiene SHA-256
`9c4590600d410ca4e68f68a0f51abb9177df438c46ee42dded6bb651b7be956e`. La
escritura en `boot` se verificó leyendo de vuelta. Tras reiniciar, Ubuntu no
reapareció en dos barridos completos de la LAN y el gadget USB siguió en Code
43, así que ese arranque todavía no tiene validación remota. La siguiente
prueba física debe hacerse sin una tecla mantenida, desconectando y conectando
la funda una vez, porque V34 contiene rutas de protección por tecla atascada.

## Sesión 19 — el teclado vuelve: el STM32 había vuelto a V34

Fecha: 2026-08-06.

### El discriminante ya estaba medido; lo que faltaba era leerlo al derecho

Desde la sesión 16 constaba, arranque tras arranque, la misma diferencia dura:
el estado bueno leía `flash version 00 37 00 37` y **todos** los malos leían
`00 34 00 34`. La sesión 18 volcó los 64 KiB en solo lectura, comprobó que V34
es una aplicación ARM coherente y de ahí dedujo que One UI usa V34 y que el
hueco estaba en nuestra inicialización fría.

Esa deducción tenía un salto. Que V34 sea una imagen válida no dice quién la
puso. El único blob que existe en este proyecto —el de la firmware oficial
X910 `X910XXS5CYG1`, el mismo que empaqueta pmOS en
`firmware-samsung-gts9uwifi`— es V37, 52.132 bytes, SHA-256
`1b48d88c23523ae205cd960e6d42725268638a15a47d8a5e52854eb01108caa3`. La sesión 8
lo programó en el MCU y **ese** fue el arranque en el que aparecieron las
primeras pulsaciones reales. El MCU había vuelto a V34 por su cuenta; nunca se
demostró que el driver mainline hablara con V34.

### La reparación

Con la tablet al 64 % y cargando —las dos condiciones que el propio actualizador
exige— se invocó el actualizador del driver. El registro es completo:

```
erasing STM32 application pages
STM32 programmed 256/52132 bytes
...
STM32 firmware programmed and fully verified (52132 bytes, version 00 37 00 37)
keyboard attached, model 0xd6 (EF-DX920)
EF-DX920 protocol confirmed; input enabled
application initialized: version 04 01 05 01, mode 1,
  CRC cd 0b f7 cf, accessory 09 00 ff 00 00 00
```

`Book Cover Keyboard Slim (EF-DX920)` volvió a `/proc/bus/input/devices` en el
acto. La tormenta de CONN se detuvo en seco: `connection_high` quedó congelado
durante los 30 s siguientes, donde antes acumulaba una activación del elevador
cada dos segundos.

### Verificado desde arranque en frío y con la dueña escribiendo

Un reinicio completo lo confirmó sin tocar nada más. El driver leyó
`00 37 00 37` a los 3,8 s, anunció `0xd6` a los 4,5 s y completó la
inicialización de aplicación a los 7,6 s. En una ventana de 20 s de uso real el
contador pasó de 1.063 a 1.174 pulsaciones, con `keys_down=1` en mitad de una
tecla y `last_key=0x0017`. `recoveries=0`, `read_retry_releases=3` y cinco
líneas de error en todo el arranque. Además la funda se desconectó y reconectó
físicamente: el driver la soltó y la volvió a enganchar con la inicialización
completa. La dueña lo dio por funcionando.

### Lo que sigue sin saberse

**Quién devolvió el MCU a V34.** No hay ningún V34 en este árbol, así que no
salió de aquí. Las dos fuentes plausibles son One UI y el port de Ubuntu Touch,
que cargan el `stm32_pogo_v3.ko` de Samsung con los blobs de su propio vendor.
Encaja con la cronología —el fallo apareció tras arrancar otros sistemas— y con
que la funda funcione en ambos: el driver de Samsung sí habla V34. Mientras no
se mida, **arrancar One UI o Ubuntu Touch puede volver a degradar el MCU**.

La recuperación es de un solo comando, y está pensada para eso:

```
sudo env GTS9U_ALLOW_POGO_FLASH=YES \
  /usr/libexec/ubuntu-gts9u-pogo-firmware-update
```

El actualizador con esa guarda quedó instalado en la tablet (SHA-256
`854599b3bb89142fdaae6f6af4e4849f1485554540dd6d9c4790498618d96e53`), y
`ubuntu-gts9u-pogo-firmware.service` sigue **enmascarado**: ninguna escritura
del accesorio ocurre en el arranque, que es justo el escenario en el que un
reinicio forzado podría interrumpirla.

### Dos cabos que esta sesión no tocó a propósito

El `boot` que corre en la tablet es `8fb31817…`, que no figura en ningún
manifiesto de `artifacts/` y **no lleva** el parche de la IRQ de handover de
`qcom_q6v5`: el journal repite `Handover signaled, but it already happened`
varias veces por segundo. Reescribir `boot` para corregirlo habría arriesgado el
estado bueno recién recuperado, así que se dejó para una sesión con la dueña
presente.

Los cambios sin commitear del árbol —`samsung,restore-output-on-resume` en el
DTS con su parche de `i2c-qcom-geni`, el `KERNEL_CLEAN` que también recrea el
worktree y el `sgdisk --zap-all` de `twrp-write-sd.sh`— son de la sesión
anterior y **nunca llegaron a la tablet**: `/proc/device-tree` no tiene la
propiedad. Quedan en el árbol sin validar. La causa que se buscaba con ellos ya
no está en pie, así que conviene revalidarlos por su cuenta antes de adoptarlos.

## Sesión 20 — v0.16: una release que instala el teclado funcionando

Fecha: 2026-08-06.

### Se descartó el experimento GENI antes de construir nada

`samsung,restore-output-on-resume` y su parche de `i2c-qcom-geni` perseguían la
hipótesis de que al MCU le faltaba que se le restauraran los drivers de salida
del serial engine tras cada runtime resume. Se comprobó primero que nunca
llegaron a la tablet —`/proc/device-tree` no tenía la propiedad— y después se
retiraron junto con el interruptor A/B `GTS9U_DISABLE_Q6_HANDOVER_PATCH`, que
solo existía para esa comparación, y con el `sgdisk --zap-all` sin probar de
`twrp-write-sd.sh`, que además aborta si el recovery no trae `sgdisk` y está
justo en el camino de reinstalar desde cero.

Se conservó una sola cosa de ese lote, porque una release la necesita:
`KERNEL_CLEAN=1` recrea también el worktree de fuentes. `apply_unless()` deja el
árbol acumulando todo parche probado alguna vez, así que borrar solo los objetos
no da una build limpia.

### La guarda estaba puesta al revés

Restaurar V37 exigía `GTS9U_ALLOW_POGO_FLASH=YES`. Eso, en una instalación
nueva, significa un sistema recién puesto con el teclado mudo y sin pista de por
qué: exactamente el problema que se acababa de diagnosticar, servido de fábrica.
La guarda pasa a ser opt-out.

Lo que hace segura la escritura no es elegir el momento, sino dónde puede caer.
El bootloader ROM del STM32 vive en memoria de sistema, no se puede borrar y
responde en todos los arranques; el driver relee los 52 KiB antes de darla por
buena. Una escritura interrumpida se completa en el arranque siguiente, así que
el servicio es autorreparable. Lo único que no puede pasar es escribir algo que
no sea el blob de Samsung, y de eso sigue encargándose el hash fijado.

Se retiró también la exigencia de alimentación externa. Programar y verificar
lleva unos dieciséis segundos; medio depósito sobra, y pedir además el cargador
era justo lo que hacía que la restauración no se ejecutara nunca.

`flash_version` sale ahora en `diagnostics`, con `bootloader`. Es el campo que
separa un controlador con el que se puede hablar de uno con el que no, y hasta
ahora había que rescatarlo de una línea de `dmesg` del arranque.

### Verificación estática de la release, antes de tocar la tablet

La imagen SD terminada se montó en solo lectura: paquete de dispositivo **1.5**,
`ubuntu-gts9u-pogo-firmware.service` enlazado en `multi-user.target.wants` y sin
enmascarar, el helper idéntico byte a byte al del repositorio, y
`pogo-keyboard.md` instalado. El blob de Samsung no vive en la imagen sino en el
overlay del ZIP; se extrajo del ZIP y se comprobó: 52.132 bytes y el hash
fijado. El árbol de fuentes que compiló esta release lleva `flash_version`.

### En hardware

Se escribieron `boot`, `init_boot`, `vendor_boot` y `dtbo` con `dd`, con
respaldo previo de las cuatro y relectura de cada una. Los dos módulos `ath12k`
se sustituyeron **antes** que el kernel: viven en la tarjeta, no en el ZIP, y un
kernel nuevo con módulos viejos deja el Wi-Fi fuera y con él el acceso por SSH.

Tras el reinicio, sin que nadie ejecutara nada:

```
ubuntu-gts9u-pogo-firmware.service: controller already on V37   (status=0)
attached=1 model=0xd6 connected=1 connection_high=0 connection_low=0
  bootloader=1 flash_version=00370037
N: Name="Book Cover Keyboard Slim (EF-DX920)"
```

Cero pulsos de CONN desde el arranque, donde el estado malo acumulaba una
activación del elevador cada dos segundos. El servicio no retrasa el arranque:
`graphical.target` a los 54,5 s y la unidad no aparece en el `blame`.

Artefactos de la v0.16, construida con `KERNEL_CLEAN=1`:

- ZIP TWRP: `aa945ae57694df0056d1f06fc492a85e3291a8b07793e4c98451a3fc7c220397`
- imagen SD comprimida:
  `631c0f8be83b18fe50a771963fb8de0ba6212350e7e5d071a08c1350d5d02079`
- `boot.img`: `d57eb0994876a22aeaebfcc09e127a8b4a202f4ef9491209154caa9275374c31`

### Lo que esta sesión no demuestra

Que la build limpia sea **reproducible** sigue sin demostrarse: haría falta una
segunda build limpia idéntica. Y no se ha reinstalado desde cero de verdad —la
tarjeta lleva datos y snaps de la dueña—, así que la garantía del teclado en una
instalación nueva se apoya en la verificación estática de la imagen y del ZIP,
no en haberla ejecutado. Lo que sí se ejecutó, y funcionó solo, es el servicio
de restauración en un arranque real.

### Apostilla: qué se pudo comprobar sin un dedo delante

En la v0.16 quedó sin observarse una pulsación real: un vigilante de cinco
minutos sobre `key_events` no registró nada porque no había nadie tecleando.
No es un fallo, es ausencia de dato, y conviene no confundirlos.

Sí se ejercitó la mitad del enlace que no necesita un dedo. Conmutar el LED de
bloqueo de mayúsculas de la funda —`/sys/class/leds/input3::capslock`— envía un
comando I²C real a la aplicación del STM32: las cuatro conmutaciones llegaron,
el valor que el driver publica en `caps=` siguió a cada una, y el contador de
errores del pogo en todo el arranque siguió en **cero**. Queda pendiente la
dirección de lectura, que es la que necesita una tecla física.

### Cierre de la apostilla: la v0.16 sí teclea

Fecha: 2026-08-07.

El hueco de la apostilla anterior no era un problema del teclado: la dueña
estaba ausente y no había dejado nada encima. Con uso real quedó medido sobre
el mismo arranque, ya con más de siete horas de vida:

```
key_events=306 last_key=0x0042 keys_down=0
data_irq=318 connection_high=4 connection_low=4
recoveries=0 read_retry_releases=0 bootloader=1 flash_version=00370037
```

Cuatro transiciones de CONN en siete horas, ninguna recuperación y ningún
reintento de lectura. Es la ventana estable más larga registrada en este port,
y contrasta con las decenas de activaciones del elevador por minuto del estado
malo.

Se comprobó además que lo que corre es la release y no un `boot` suelto: las
cuatro particiones de arranque de la tablet coinciden byte a byte con el
manifiesto de la v0.16, y el paquete de dispositivo instalado es el 1.5.

## Sesión 21 — el teclado deja de pedir cosas, y los nombres comerciales

Fecha: 2026-08-07.

### El requisito de la funda era una suposición, y era falsa

El actualizador rechazaba escribir si la línea de conexión estaba baja. La
justificación asumida —que el controlador colgaba del mismo raíl que el
accesorio— nunca se había medido. La dueña preguntó lo obvio: si lo que se
programa está en la tablet, ¿para qué hace falta la funda?

Se midió. Con la funda fuera, `connected=0` y `pogo_vddo` en `disabled`:

```
STM32 bootloader reachable, product id 0x460, flash version 00 37 00 37
STM32 pogo controller ready (connected=0, data-ready=0)
```

El ROM contesta igual sin funda y sin raíl. Lo que se corta al desconectar
alimenta al teclado; el microcontrolador va por el I2C6 de la tablet y es
independiente. La comprobación se retira: escribir sin funda es incluso más
tranquilo, porque no hay pulsos de conexión compitiendo.

El umbral de batería baja de 50 % a 15 %. No defiende la flash —una escritura
interrumpida se completa en el arranque siguiente porque el bootloader ROM no
se puede borrar— solo evita empezar en una tablet a punto de apagarse. La
exigencia de cargador ya se había retirado antes, y era justo lo que impedía
que la restauración se ejecutara nunca.

Con eso, la sección del README que explicaba qué tenía que hacer el usuario
desaparece: no tiene que hacer nada.

### Los nombres comerciales: dos fuentes, una por capa

Cada herramienta preguntaba a un sitio distinto y ninguna daba un nombre.

**CPU.** La línea `model name` de `/proc/cpuinfo` es la convención universal en
Linux, y arm64 solo la emite para tareas compat. Rellenarla desde una tabla
indexada por el compatible de la máquina —no por una propiedad nueva del DTS,
que obligaría a reescribir `vendor_boot`— hace que GNOME y todo lo que lea ese
fichero reciba «Qualcomm Snapdragon 8 Gen 2». Se habilita además
`QCOM_SOCINFO`, que estaba en `=m` y por tanto no existía; ahora `soc0` publica
familia `Snapdragon` y máquina `SM8550`.

**GPU.** `force_gl_renderer` es una opción soportada de Mesa —su configuración
de fábrica la usa con otras Adreno— así que no hizo falta un Mesa propio.
OpenGL pasa de `FD740` a `Adreno (TM) 740`, que es lo que muestra el F3 de
Minecraft. Una trampa que costó una sesión: un `--` dentro de un comentario XML
es ilegal, y Mesa descarta el fichero entero sin decir nada.

Vulkan sigue diciendo `Turnip Adreno (TM) 740`: esa cadena sale de un formato
fijo dentro del driver, sin opción de configuración.

**fastfetch** no leía ninguna de las dos. Un `strace` lo mostró abriendo
`/sys/firmware/devicetree/base/compatible` y nunca `/proc/cpuinfo`: en ARM
rellena el nombre desde el device tree y, una vez puesto, se salta la lectura
entera. Como este port ya compila fastfetch desde fuente, se parchea el orden
de precedencia, que además es el correcto. El paquete pasa a `2.66.0-gts9u1`
para que una actualización del archivo no se lleve el parche por delante.

### La build limpia no es reproducible, y ya se sabe por qué

Dos builds limpias del mismo árbol dan el mismo DTB, `vendor_boot`, `init_boot`
y `dtbo`, pero distinto `Image.gz`. Aislada la diferencia en un módulo de 1 MB,
**todo lo anterior a `.BTF` coincide byte a byte**: el código compilado ya es
determinista y lo que baila es el codificador BTF paralelo que
`scripts/Makefile.btf` invoca con `-j$(JOBS)`. El detalle y el arreglo —sin
aplicar, porque cambiaría el kernel a cambio de nada que hoy haga falta— están
en las notas de desarrollo.

### Una carrera propia, que se comió el servicio entero

Al desplegar el kernel sin el requisito de funda, el servicio de restauración no
llegó a ejecutarse: `ConditionResult=no` y ni una línea en el journal.

La causa es un cambio de la sesión 20. La unidad llevaba
`After=multi-user.target` **y** `WantedBy=multi-user.target`, con la idea de que
corriera tarde para poder esperar a la funda sin retrasar el arranque. systemd
no puede ordenar una unidad detrás del propio target que la arrastra: ignora esa
ordenación sin avisar y la lanza junto a las demás, sobre los tres segundos. El
driver engancha a los 3,9 s, así que
`ConditionPathExists=/sys/bus/i2c/devices/6-002a/firmware_update` perdía la
carrera y la unidad quedaba marcada como no aplicable. En silencio: una
condición que falla no es un error.

En la v0.16 y la v0.17 sí corrió, pero por suerte de carrera, no por diseño. La
red de seguridad llevaba un día existiendo solo a ratos.

La reparación tiene dos partes. La ordenación vuelve a `After=local-fs.target`,
que además ya no cuesta nada: quitado el requisito de funda, el helper no tiene
que esperar a nada. Y la espera por el dispositivo baja al helper, acotada a
15 s y con mensaje, en vez de vivir como condición de systemd, donde perder una
carrera no deja rastro.

Verificado desde arranque en frío: `ConditionResult=yes`, la unidad arranca a
las 04:57:16 y termina un segundo después con «controller already on V37».

## Sesión 22 — el digitalizador del S Pen responde, pero todavía no habla

Fecha: 2026-08-07.

### Dónde estaba escondido

`vendor_boot` no menciona el digitalizador ni una vez, y por eso constaba como
«sin driver mainline» sin más detalle. Está en el **`dtbo` de Samsung**, que
nadie había abierto: se extrae del paquete AP del firmware oficial y contiene
dos overlays, ambos con el nodo.

```
wacom@56   compatible = "wacom,w90xx"   bus: qupv3_se3_i2c
  irq = gpio154   pdct = gpio137   fwe = gpio179
  avdd = pm_humu_l13              firmware = wez01_gts9u.bin
```

El bus es nuestro `i2c3`: Samsung numera los SE igual que mainline, como ya
demostraba el pogo en `qupv3_se15_i2c` = `i2c15`. `gpio40/41` (los pines del
bus) y `gpio154/137` estaban libres, y `gpi_dma1` ya habilitado.

### El chip está vivo

Habilitado `i2c3` con el nodo, `i2cdetect` ve **0x56** contestando. La consulta
estilo HID devuelve un registro estable, y decodificarlo confirma que es el
dispositivo correcto: el registro empieza en el offset **17** y es
**big-endian**.

| Campo | Leído | DT de Samsung |
|---|---|---|
| x_max | `0x4c85` = 19589 | — |
| y_max | `0x7a90` = 31376 | — |
| presión | `0x0fff` = 4095 | `max_pressure = 0xfff` |
| tilt | `0x3f 0x3f` | `max_tilt = <0x3f 0x3f>` |
| altura | `0xff` | `max_height = 0xff` |
| módulo | `0x02` | `module_ver = 0x02` |
| boot addr | `0x09` | `boot_addr = 0x09` |

La proporción 19589/31376 es 0,6243, exactamente 1848/2960 del panel. El
decodificado no es una casualidad.

### Por qué el driver de mainline no sirve, y por qué callaba

`wacom_i2c` lee **19 bytes en little-endian** desde offsets 3, 5 y 11. Este
chip pone su registro en el 17 y en big-endian, así que la consulta falla. Y
falla **en silencio**: el probe hace `error = wacom_query_device(); if (error)
return error;` sin un solo `dev_err`. De ahí que no hubiera ni una línea en
dmesg, lo que al principio parecía que ni siquiera había casado.

El driver de Samsung para esta pieza es `wez01.ko`, con `alias:
i2c:wacom_w90xx`. Sus cadenas dan dos requisitos que mainline no cumple:

- `fwe gpio is high, change low and reset device` — la línea de habilitación de
  flash debe estar baja.
- `failed to send wacom i2c mode` — hay un **comando de modo** que arranca el
  reporte.

Sus notificadores enumeran justo el alcance pedido: `PEN_HOVER_IN/OUT`,
`PEN_INSERT/REMOVE`, `PEN_CHARGING_STARTED/FINISHED`.

### Lo que no funcionó, anotado para no repetirlo

Los comandos de un byte al estilo Samsung (`0x2a`, `0x31`, `0x32`, `0x33`)
**hacen que el chip deje de reconocer su dirección**: durante un rato todas las
transferencias dieron `ENXIO`. Se recupera solo, pero no es su protocolo. La
consulta de seis bytes con registro y opcode sí funciona, así que la interfaz
es de estilo HID-sobre-I2C, no la de bytes sueltos.

Se sospechó que la suspensión cortaba el raíl del panel, que es quien alimenta
al digitalizador. **Falso**: `vreg_l13b_3p0` seguía habilitado, el panel
encendido, y solo hubo la suspensión de recuperación del arranque.

### Estado: responde, no reporta

Con el lápiz apoyado en la tablet no llega ningún evento; las lecturas dan una
cabecera fija `0d 03 11` que nunca cambia. Hay tres explicaciones y no se pueden
separar sin mover el lápiz: que un EMR **tumbado** acople mal por quedar su
bobina paralela a la rejilla, que falte el comando de modo, o que FWE esté alta.

Queda un grabador de solo lectura corriendo en la tablet
(`/tmp/spen-record.sh` a `/tmp/spen-capture.log`) que registra cualquier cambio
con marca de tiempo. En cuanto la dueña coja el lápiz y lo sostenga en
perpendicular, el formato del informe queda capturado sin necesidad de estar
delante.

Nada de lo que ya funcionaba se ha tocado: cero líneas de error de I²C en todo
el arranque, y pantalla, GPU, sensores y el controlador pogo intactos.

## Sesión 23 — el S Pen escribe: driver propio, y tres defectos que la dueña encontró

Fecha: 2026-08-07.

### El formato del informe, decodificado de 5.200 fotogramas

Con el bus levantado y un grabador de solo lectura corriendo, mover el lápiz
bastó para capturar el protocolo. La cabecera fija `0d 03 11` que se veía en
reposo no era el informe: los informes aparecen solo con el lápiz en rango.

```
[0]    estado: 0x80 en rango · 0x20 botón lateral · 0x10 punta · 0x01 siempre
[1:2]  X          big endian        [7]   inclinación X (con signo)
[3:4]  Y          big endian        [8]   inclinación Y (con signo)
[5:6]  presión    big endian        [9]   distancia
       bit15 marca el campo         [10]  contador de secuencia
```

Lo que hace el decodificado seguro no es que encaje, sino que cada campo se
valida contra algo independiente: la presión es distinta de cero **exactamente**
en los fotogramas con bit4 y cero en los otros 5.059; la inclinación Y recorre
−63…21, que es el ±63 del árbol de Samsung; y no queda ni un bit sin explicar.

El botón lateral necesitó una captura aparte, porque en la primera no se pulsó
ni una vez. Aparecieron dos estados nuevos, `0xa1` y `0xb1`: bit5.

### Driver propio, y por qué no valía ninguno de mainline

`wacom_i2c` lee 19 bytes little-endian desde los offsets 3, 5 y 11; este chip
responde big-endian desde el 17. Y falla **en silencio**: su probe devuelve el
error de la consulta sin imprimir nada, así que un fallo es indistinguible de no
haber casado, lo que despistó al principio. `wacom_w9000` solo cubre W9002 y
W9007A. Se retiran los dos del kernel: conservarlos solo haría ambiguo de cuál
viene un fallo futuro.

### Tres defectos, todos encontrados usándolo

La dueña probó y describió tres síntomas. Los tres eran reales y ninguno era el
que yo habría mirado primero.

**«Se ignoran los toques» y «deja de pillar el lápiz al mover rápido».** El
mismo defecto: mi driver soltaba el lápiz ante cualquier fotograma sin el bit de
rango, y el chip intercala cabeceras de estado y lecturas rotas entre los
buenos. Medido: **75 pérdidas en quince minutos**. Descartando lo que no es un
informe de lápiz y exigiendo tres fotogramas seguidos antes de creerse una
salida de rango, **bajaron a cero**.

**«El hover va con retraso, sobre todo al mover rápido».** Esa descripción era
la pista: es la firma de una tasa de muestreo baja, no de un driver lento. El
intervalo medía 25,0 ms a tres cifras, que son 40 Hz exactos, que es literalmente
`COM_SAMPLERATE_40` de Samsung. Enviar `0x31` lo llevó a ~440 Hz de posiciones
**distintas** —5.385 X nuevas en 5.637 paquetes, así que no son repeticiones—.
Y la tasa **se revierte sola**, que es lo que `wez01` llama «samplerate state is
%d, need to recovery», así que el driver la pide también en cada entrada en
rango.

**«Al rotar la pantalla el lápiz se queda girado 90º».** Aquí el instinto de
mirar las propiedades de orientación era el equivocado: si la base estuviera
mal, fallaría también sin rotar. La comparación con el táctil lo cerró en un
vistazo: mismo árbol, mismas propiedades, pero `PROP=2` frente a `PROP=0`. Sin
`INPUT_PROP_DIRECT`, libinput archiva el lápiz como tableta gráfica externa, que
se mapea al escritorio entero y **deliberadamente** no sigue la orientación de
la salida.

### El arranque

El primer intento no enganchaba: NACK a los 3,887 s. La alimentación es LDO13
del PMIC B, compartida con el VCI del panel, y yo había decidido no declararla
razonando que «el panel ya la mantiene encendida». Cierto en régimen
permanente, falso durante el arranque, que es justo cuando el driver sondea.
Declarada y encendida desde el driver, con reintentos, engancha a los 3,97 s sin
que nadie haga nada.

### Lo que queda

Las partes 2 y 3 —acoplamiento y carga del lápiz, y los gestos por BLE—. El
`wez01` de Samsung depende de `stm32_pogo_v3`, `hall_ic_notifier` y
`usb_typec_manager`, y sus notificadores nombran `PEN_INSERT`, `PEN_REMOVE`,
`PEN_CHARGING_STARTED` y `PEN_CHARGING_FINISHED`, así que esa parte pasa por el
mismo sitio que la funda.

### La rotación del lápiz no estaba en el kernel, y la pista la dio el dedo

Con el driver funcionando, la dueña encontró que el lápiz no seguía la rotación
de la pantalla. Costó tres iteraciones porque **estuve mirando donde no era**.

El error de método: ella describía el fallo **en vertical**, donde lo que se ve
es la transformación del driver *más* la del compositor. Atribuí la diferencia
entera al árbol de dispositivos, quité `touchscreen-inverted-x` y rompí el
horizontal, que llevaba bien desde el principio.

La medida que había que hacer desde el primer momento es en la orientación
nativa, donde el compositor no rota nada. Dos esquinas opuestas con el lápiz:

```
superior izquierda   ABS_X   7 %   ABS_Y  97 %
inferior derecha     ABS_X  92 %   ABS_Y   6 %
```

`ABS_X` crece de izquierda a derecha; `ABS_Y` decrece de arriba a abajo. Luego
la configuración original —invertir X y luego intercambiar— era correcta, y una
sola esquina no habría bastado para saberlo: distingue mal entre «el eje está
invertido» y «me he equivocado al interpretar qué esquina es».

La pista buena la dio ella: **el táctil giraba bien en todas las orientaciones**.
Eso descarta el compositor y señala lo único que el dedo y el lápiz no comparten:

- un **táctil** se calibra contra su salida, y GNOME le aplica la matriz sin
  consultar nada más;
- una **tableta** se *asigna* a una salida, y para saber a cuál —o si le toca
  alguna— GNOME pregunta a **libwacom**.

Nuestro digitalizador no estaba en su base de datos. Una tableta desconocida se
asume externa, y una tableta externa **deliberadamente** no sigue la orientación
de la pantalla: es lo correcto para una Intuos sobre la mesa y justo lo
contrario cuando la tableta *es* la pantalla.

La entrada `samsung-gts9u-spen.tablet` lo dice en una línea,
`IntegratedIn=Display;System`, y libwacom pasó a devolver `integration flags=0x3`.
No bastó con reenlazar el driver: el compositor lee esa base al arrancar, así
que hizo falta un reinicio. Con eso, correcto en las cuatro orientaciones.

Vale la pena retener que **esta parte es userspace**: va en el paquete de
dispositivo, no en el kernel, así que iterar aquí cuesta un minuto y no obliga a
reflashear.

## Sesión 24 — la carga lenta eran tres fallos encadenados

Fecha: 2026-08-07.

La dueña reportó que la tablet cargaba muy despacio con el cargador oficial de
45 W. Medido al empezar: **4,7 W** entrando a la batería, y un 1 % cada siete
minutos. El cargador anunciaba 5V/3A, 9V/3A, 15V/3A, 20V/2,25A y **PPS hasta
11 V a 5 A**; nosotros negociábamos 9 V a 1,66 A.

### El SM5440 estaba ahí, y su driver también

Ni el chip ni el driver faltaban: `0-0063 -> sm5440`, «direct charger device ID
0x21», y `sm5440_direct.c` ya sabía pedir PPS, refrescarlo y volver al cargador
conmutado. El fallo no era de ausencia sino de comportamiento.

### Primero: I2C durante la suspensión, que tumbaba el puerto entero

```
i2c i2c-0: Transfer while suspended     ← el SM5440
i2c i2c-4: Transfer while suspended     ← y detrás el controlador PD
```

El lazo de sondeo de un segundo se ejecutaba durante la suspensión del sistema,
y las transferencias fallidas **se llevaban por delante el contrato USB-PD**: el
puerto caía a 5 V de DCP y se quedaba ahí. No era una carrera rara — la
recuperación en frío del panel suspende a los ~21 s de cada arranque, que es
justo cuando el cargador está negociando.

Es la misma lección de la sesión 9 con el pogo. Allí se pudo quitar el sondeo;
aquí no, porque la carga directa necesita su lazo, así que se para alrededor de
la suspensión devolviendo antes la batería al conmutado.

### Segundo: no había lazo cerrado

Con el PD ya estable se vio el siguiente: el driver calculaba la tensión
objetivo **una vez al arrancar** y luego reenviaba siempre la misma. Según sube
la batería, el margen sobre 2×Vbat se estrecha y la corriente se apaga sola:

```
ibus: 970 → 1047 → 995 → 1050 → 775 → se suelta
```

Ahora recalcula el objetivo antes de cada refresco, en pasos de 20 mV, que es la
resolución del propio cargador.

### Tercero: REVBLK, y el chip lo dijo por su boca

Seguía soltándose, con firmas contradictorias —una parada con 1085 mA
circulando y otra con cero— y sin periodo fijo. En vez de una tercera conjetura
se añadió instrumentación: leer los cuatro pestillos de interrupción en el
momento del fallo, que es cuando sirven porque se borran al leerlos.

```
int=0x0/0x0/0x2/0x0   →  INT3 bit 1
```

El orden de bits salió de las cadenas del `sm5440-charger.ko` de Samsung, en el
orden del binario, y **se valida solo**: `VBUSPOK` cae en el bit 5, que es
exactamente lo que ya definía nuestro driver. El bit 1 es **REVBLK**, bloqueo
por corriente inversa.

La causa: a 1,8 A el cargador y el cable ceden unos 400 mV, así que de los
700 mV nominales de margen quedaban ~290 mV en el chip —vbus 8291-8332 contra un
pack de 4003— y cualquier bajón invertía la corriente. **Subir la corriente fue
lo que destapó esto**: a 1 A la caída era la mitad y sobraba margen.

Margen a 1100 mV. Resultado: de tramos de 22-43 s a **más de 350 s seguidos**, y
de 4,7 W a **~10 W** entrando a la batería, con la capacidad subiendo un 2 % en
seis minutos.

### Sobre el método

Dos hipótesis propias cayeron por el camino —el margen de tensión y el perro
guardián—, ambas deducidas de datos indirectos. La primera incluso se revirtió a
propósito para no mezclar un arreglo demostrado con una inferencia sacada de
lecturas que podían estar corruptas por el fallo de suspensión; resultó ir en la
dirección correcta pero con el signo cambiado, y solo se recuperó cuando el
hardware nombró la causa.

Añadir instrumentación en lugar de probar una conjetura más fue lo que desatascó
el asunto.

### Lo que queda

Los 45 W. Los topes actuales son del driver: 2200 mA de petición PPS y 1800 mA
de límite de entrada. Subirlos exige cuidado porque **la caída del cable crece
con la corriente**, que es precisamente lo que provocó el REVBLK: cada escalón
de corriente se come más margen y acerca otra vez el borde.

### El lazo definitivo: regular sobre la corriente, no sobre la tensión

Quedaba entender qué limitaba la corriente. No era ningún tope del driver: pedía
2000 mA, el limitador del chip estaba en 1800 y solo circulaban 1300.

El patrón sale de los propios datos. Un convertidor 2:1 de condensadores
conmutados **se comporta como una resistencia**: la corriente la fija la
diferencia entre la entrada y el doble del pack.

| vbus | 2×vbat | ΔV | ibus | ΔV/I |
|---|---|---|---|---|
| 8623 | 8396 | 227 mV | 1321 mA | 0,172 Ω |
| 8455 | 8228 | 227 mV | 1325 mA | 0,171 Ω |
| 8291 | 8006 | 285 mV | 1720 mA | 0,166 Ω |
| 8332 | 8006 | 326 mV | 1805 mA | 0,181 Ω |

Cuatro puntos, 0,17 Ω constante. Subir los topes no habría servido de nada
porque nunca se tocaban; lo que hacía falta era **empujar la tensión hasta que
la corriente llegue**.

Hay además un desajuste sin explicar entre lo que se pide al cargador y lo que
el chip mide en su entrada: ~900 mV, y **crece cuando la corriente baja**, que
descarta la caída de cable. El cable es el original y funciona bien en One UI.
No hizo falta resolverlo: regulando sobre la corriente medida, la exactitud
absoluta del ADC de tensión deja de importar. Queda anotado como pendiente, no
como bloqueo.

Resultado con la batería al 28 %: **18,8 W** entrando al pack, 4,76 A a 3,96 V,
sin un solo corte en cinco minutos, chip a 43 °C y pack a 33,9 °C. La capacidad
subió del 28 % al 32 % en cinco minutos.

De 4,7 W a 18,8 W: **cuatro veces**, y el ritmo pasa de 1 % cada siete minutos a
1 % cada minuto y cuarto.

## Sesión 25 — el bucle de `iio-sensor-proxy` era una espera que no esperaba

Fecha: 2026-08-08.

`iio-sensor-proxy` quemaba **un núcleo entero de forma permanente**, desde el
arranque. Línea base medida al empezar, con 18 minutos de uptime: `cpu-time
00:17:27` — es decir, el 96 % del tiempo transcurrido—, 199 ticks/2 s, **94,7 °C**
en la zona térmica más caliente con la tablet en reposo, y la corriente de carga
hundida.

Lo difícil no era encontrarlo, era que **el demonio que giraba funcionaba**:
`AccelerometerOrientation = "normal"`, `HasAccelerometer = true`, autorrotación
correcta. Y matarlo no valía: la instancia nueva pierde el sensor hasta que
vuelve la sesión gráfica, y vuelve a girar igual. La sesión anterior ya se había
estrellado contra eso construyendo un servicio de recuperación que ni curaba el
bucle ni conservaba la rotación, y que quedó retirado.

### El `strace` apuntaba al llamante, no al bucle de eventos

La evidencia previa decía: 106.941 `ppoll` en tres segundos, 99,64 % del tiempo
de proceso, **todas** con `{tv_sec=0, tv_nsec=0}` y **todas** devolviendo
`0 (Timeout)`. La lectura natural es un `GSource` cuyo `prepare()` se declara
listo en cada pasada. Es la lectura equivocada.

Un timeout de cero en cada vuelta no lo produce una fuente mal armada: lo
produce `g_main_context_iteration (ctx, FALSE)`. Con `may_block` a `FALSE` GLib
**fuerza** el timeout a cero, mire lo que mire. La firma acusaba al llamante.

### Un `gdb` sobre el proceso vivo cerró el caso en una traza

No había gdb en la tablet; instalarlo costó un `apt-get`. El hilo principal:

```
#3 ssc_common_wait_sync_context (ctx=…) at ../src/libssc-common.c:56
#4 ssc_sensor_light_open_sync (…)      at ../src/libssc-sensor-light.c:225
#5 ssc_light_set_polling (…)           at ../src/drv-ssc-light.c:94
#6 handle_method_call (… method_name="ClaimLight" …)
#10 g_main_loop_run
```

Dos cosas a la vez. La primera, que libssc 0.4.4 implementa sus esperas
síncronas girando el contexto por defecto sin bloquear:

```c
while (!ctx->finished) {
        g_main_context_iteration (g_main_context_default (), FALSE);
}
```

Eso no es esperar, es girar. Cualquier petición que el SSC no conteste clava un
núcleo mientras viva el proceso.

La segunda, que el que no contestaba era el **sensor de luz**: el firmware
Samsung descubre el STK31610, acepta el `enable` y nunca manda la respuesta de
configuración, así que `ssc_sensor_light_open_sync()` no termina jamás. GNOME
llama a `ClaimLight` al abrir sesión y ahí se quedaba.

Y así se explica por fin la paradoja: como el bucle itera el contexto principal,
D-Bus y el flujo del acelerómetro **se despachaban desde dentro de la espera**.
El demonio giraba y funcionaba porque girar era, literalmente, lo que lo hacía
funcionar.

### El arreglo, y por qué no cambia nada más

`packaging/sensors/fix-ssc-sync-wait-busy-loop.patch`: bloquear en `poll()`. La
callback que termina la espera se despacha desde ese mismo contexto, así que lo
que despierta el poll es exactamente lo que acaba la espera, y las demás fuentes
se siguen despachando igual desde la iteración anidada. Sólo el hilo que conduce
el contexto puede bloquearse en él, de ahí el `g_main_context_acquire()` y el
respaldo sobre la `GCond` que la callback ya señalaba.

El disparador concreto ya tenía parche desde la sesión anterior
(`disable-broken-ssc-light.patch`, que saca `ssc-light` de la tabla de drivers),
pero **nunca se había instalado en la tablet**: el binario que corría era
anterior. Se comprobó comparando el sha256 del `.deb` construido con el de
`/usr/libexec/iio-sensor-proxy` en el dispositivo. Van los dos juntos: uno quita
la petición que no se contesta, el otro hace que ninguna petición sin contestar
vuelva a costar un núcleo.

### Resultado, medido tras arranque en frío

| | antes | después |
|---|---|---|
| ticks/2 s | 199 | 1 |
| CPU acumulada / uptime | 00:17:27 en 1094 s | 00:00:01 en 222 s |
| zona térmica más caliente | 94,7 °C | 46,9 °C |
| corriente de batería | −908 mA | +1505 mA |
| `AccelerometerOrientation` | `"normal"` | `"normal"` |

La medición es de tasa, no de contador acumulado sobre un proceso recién
nacido: ese fue justamente el error de método de la sesión anterior.

Queda pendiente reintentar la subida de corriente de carga a 3200 mA, que se
había medido con el bus contaminado por este bucle.

## Sesión 26 — el lápiz se quedaba «presente», y la explicación bonita era falsa

Fecha: 2026-08-08.

La dueña reportó un fallo anterior a todo esto: usando el lápiz, **una parte de
la pantalla deja de responder al dedo**. El detalle que lo hacía interesante es
que un arrastre iniciado en la zona buena **sí** atraviesa la zona muerta;
empezar dentro, no. Intermitente, y se va al reiniciar.

### Lo que se encontró, que es real

Ese detalle describe con precisión el arbitraje táctil de libinput: con una
herramienta en proximidad descarta los contactos **nuevos** dentro de un
rectángulo y no cancela los que ya están en curso. Y los dos dispositivos están
emparejados: `udevadm info /dev/input/event4` da
`LIBINPUT_DEVICE_GROUP=18/0/0:input/ts`, donde `18/0/0` son el bus y los IDs del
**lápiz**.

Con eso en la cabeza, se miró el estado real del digitalizador y estaba clavado:
`BTN_TOOL_PEN` a 1 sin lápiz cerca. Y no era que el driver perdiese un evento:
**0 interrupciones en 5 s**, `ABS_DISTANCE` congelado, último frame válido con
distancia 235 de 255. El controlador se calla al irse el lápiz, y
`samsung_wacom_w90xx` sólo sabía sintetizar la salida contando frames que ya no
llegan. Se queda a 1 hasta el siguiente reinicio.

Arreglado con un `timer_list` de 250 ms que trata el silencio como una marcha.
Verificado tras flashear: sube a 1 al dibujar y vuelve a 0 solo al apartar el
lápiz, y sigue a 0 tras 90 s de muestreo.

### Lo que no era

La historia encajaba tan bien que casi se cierra ahí. Pero antes de darla por
buena se pidió la comprobación física, y con el flag clavado —clavado y
verificado clavado— **la dueña no encontró ninguna zona muerta**.

O sea: la marca de proximidad pegada es un defecto real y está corregido, pero
**no es la causa del fallo del táctil**, o al menos no basta. El fallo sigue
abierto.

La lección no es nueva pero volvió a aparecer con otra cara: una explicación que
predice el síntoma con todo detalle sigue siendo una hipótesis mientras no se
contraste. Aquí lo barato era preguntar, y preguntar la tumbó.

Queda `work/catch-dead-zone.sh` para el próximo episodio. Parte el problema en
dos según una sola medida —si los toques de la zona muerta llegan al kernel o
no— y está validado contra un toque real, para que un «0 contactos» no pueda
confundirse con una herramienta rota.

### De paso: dos scripts de `work/` que no hacían nada

`flash-boot-ssh.sh` no podía funcionar por dos motivos independientes. La tablet
**no tiene `authorized_keys`**, y el script fuerza clave con `BatchMode=yes`. Y
aunque autenticase, su payload nunca se ejecutaría: en
`ssh host "echo PW | sudo -S bash -s" <<'EOF'`, el stdin de `sudo` es el pipe de
`echo`, que sólo lleva la contraseña; `sudo` se la come y a `bash -s` le llega
EOF. Reproducido con un payload inofensivo: salida vacía.

Lo peligroso es la combinación: imprimiría `pushed`, luego nada, y saldría con
código 0 **sin haber escrito la partición**. `work/restore-tree-and-test.sh`
tiene el mismo patrón, así que lo que se concluyera de ejecutarlo se concluyó de
un no-op. Ninguno de los dos está en el repo publicado; se comprobó.

El sustituto, `work/flash-boot-password.sh`, usa contraseña y ejecuta el payload
desde un fichero por ruta, conservando las comprobaciones que importan: sha de
la imagen subida, exigir que el destino resuelva a `/dev/sd*`, y releer la
partición para compararla.

## Sesión 27 — 25 W: el techo estaba en lo que pedíamos, no en lo que empujábamos

Fecha: 2026-08-08.

Con el bucle de sensores fuera, tocaba reintentar la carga. La sesión 24 había
dejado 18,8 W y una nota diciendo que 3200 mA de objetivo hundieron el bus, que
2200 era «prudencia, no un límite medido», y que convenía reintentarlo con
batería baja y el cargador recién enchufado. Se dieron las tres condiciones:
batería al 6 %, cargador oficial de 45 W recién conectado, y nada pinando un
núcleo.

Primer dato, gratis: **19,4-20,9 W** sin tocar nada. El bucle de
`iio-sensor-proxy` valía casi dos vatios.

### El barrido que no movía nada

Para no gastar un ciclo de compilar-flashear-reiniciar por escalón, se expuso
`SM5440_TARGET_IBUS_MA` como parámetro escribible. El barrido salió plano:
`ibus` 2587, 2596, 2600 mA con el objetivo en 2200, 2600 y 2800. Un lazo que no
reacciona a su consigna está saturado en otro sitio.

Forzándolo a 3400 la petición sí subió —`in0_input` a 9860 mV— pero **bajaron a
la vez tensión y corriente**, hasta 1867 mA. Eso no es un lazo flojo: es una
fuente plegándose porque ya está en su límite.

Aquí hubo que retirar una interpretación propia: la diferencia entre lo pedido
y lo medido parecía 0,55 Ω de resistencia serie, pero **crece cuando baja la
corriente**, que es lo contrario de lo que hace una resistencia. El propio
driver ya advertía de que el ADC de `vbus` del chip se desvía así.

### Lo que sí era

```c
target_ma = min(target_ma, 3000);
```

La corriente del contrato PPS, fijada. `dmesg` lo llevaba diciendo desde el
arranque: `direct charge started: PPS 8760 mV/3000 mA`. El adaptador anuncia
5 A, TCPM no añade tope propio, y el suelo que el lazo pedía ya quería ~4,1 A.
Pedíamos 3 A y nos daban 2,9.

Dos detalles hicieron falta para que el knob equivalente sirviese: el
`max(SM5440_INITIAL_PPS_MA, …)` de delante habría dejado el resultado en 3000
igualmente, y el refresco periódico es el único sitio que reenvía la corriente,
así que hay que recalcularla ahí para que el cambio surta efecto sobre la
sesión viva.

### Resultado

| contrato | pack | ibus | vbus | die |
|---|---|---|---|---|
| 3000 mA | 21,4 W | 2601 mA | 8556 mV | 45,5 °C |
| 3200 mA | 22,8 W | 2864 mA | 8611 mV | 46,5 °C |
| **3400 mA** | **25,0 W** | 2960 mA | 8652 mV | 48,5 °C |
| 3600 mA | 24,2 W | 3141 mA | 8801 mV | 54,0 °C |
| 3800 mA | 24,2 W | 3128 mA | 8780 mV | 55,0 °C |
| 4000 mA | 24,2 W | 3167 mA | 8835 mV | 55,0 °C |

Por encima de 3400 sube `ibus` y no la potencia: pérdida en la bomba, pagada en
seis grados de die. Soak de cinco minutos a 3400: **25,2-25,5 W** planos, die
49,5 °C, pack 36,4 °C, del 45 % al 49 % de batería.

De 18,8 a 25,2 W. Queda por ver si a batería más baja da más, que es la
condición que se gastó cargando mientras compilaba.

### Sobre parar a tiempo

A mitad de camino se llegó a la conclusión de que subir de 3 A exigía probar el
cable por SOP', y que sin `port0-cable` ni VCONN no era legítimo. Media
conclusión estaba mal: siendo *sink* y *UFP*, quien interroga al cable es el
cargador, no la tablet, así que la ausencia de esos nodos es normal en este rol
y no prueba nada sobre el cable.

Lo que sí se sostiene es la parte de fondo, y por eso el knob se queda con
bandas y con el aviso en el comentario: el que es de 5 A es *este* cable, y por
encima de 3 A lo que está en riesgo es el conector, no el silicio.

## Sesión 28 — cuatro sensores, cuatro fotos y luz real

Fecha: 2026-08-08.

El criterio se fijó antes de empezar: identificar por I²C o crear
`/dev/video0` no cerraba nada. Cada objetivo tenía que entregar un frame físico
reconocible y el flash tenía que iluminar la escena, no solo aceptar un valor en
sysfs.

### Primero, el flash

El bloque stock llamado `pm8350c-flash-led` está en el PM8550 de SID 1. En
mainline corresponde a `qcom,spmi-flash-led`. Los canales 0 y 1 están conectados
a los dos emisores traseros y Samsung los acciona juntos; el DT los expone como
un solo LED blanco con `led-sources = <1>, <2>` y límites conservadores.

Se probó primero linterna mantenida y después estrobo sincronizado con la clase
V4L2 flash. Las dos rutas encendieron físicamente y cambiaron la iluminación y
los reflejos de la mesa:

- [captura con estrobo](../work/resultado-flash.jpg);
- [captura con linterna](../work/resultado-linterna.jpg).

### Qué sensores había realmente

El DTS público stock no contiene los módulos: Samsung los entrega como blobs
CamX Parameter Parser V3. El inventario real resultó ser tres HI1337 —principal
trasero, principal frontal y angular frontal— y un HI847 angular trasero.

El HI847 upstream solo enlazaba por ACPI y suponía alimentación gestionada por
plataforma. Se añadió DT y su secuencia VDDIO/enable/reset/MCLK. Para HI1337 se
escribió un driver V4L2 pequeño y específico de la X910. Un extractor local
decodificó de los blobs la tabla global exacta de 1.476 registros y los tres
modos exactos; el header generado queda en `kernel/drivers/` para que el build
sea reproducible sin depender del árbol stock en `work/`.

Los fallos intermedios que cambiaron el resultado fueron concretos:

- `slaveAddress = 0x40` del frontal principal era una dirección de ocho bits;
  Linux necesita `0x20`;
- CCI1 master 1 usa el par AON GPIO208/209, no el pinmux CCI ordinario;
- PM8550VS-C L1 y PM8550B L11 necesitan el paso representable de 1.104 V;
- los dos frontales comparten MCLK4/GPIO104, por lo que solo el principal puede
  poseer su pinctrl;
- los GPIO de módulo/reset no pueden quedar reclamados durante toda la vida del
  subdispositivo: se toman al encender y se sueltan al apagar.

Al final los cuatro IDs físicos respondieron:

```
rear-main       1-0021  model=0x1337 vendor=0x2000
front-main      3-0020  model=0x1337 vendor=0x2000
front-ultrawide 9-0021  model=0x1337 vendor=0x2000
rear-ultrawide  0-0021  HI847
```

### Cuatro capturas, no cuatro enumeraciones

Cada sensor se condujo solo por `msm_csiphyN → msm_csid0 → msm_vfe0_rdi0 →
/dev/video0`. Cinco frames consecutivos de cada ruta llegaron a unos 30 fps.
El primer frame guardado y entregado dio:

| objetivo | subdev / CSIPHY | frame | SHA-256 RAW10 |
|---|---|---|---|
| trasera principal | `/dev/v4l-subdev32` / 1 | 4128×3096, 16.000.128 B | `104333e0d777448cb3857343a58bf6abbdcf1d4effefee70f7382f77d771ac43` |
| trasera angular | `/dev/v4l-subdev33` / 2 | 3264×2448, 9.987.840 B | `c72f2fb32c1f21d541b62f85b5cacbc86f1738e5405010864979738987ac4997` |
| frontal principal | `/dev/v4l-subdev31` / 4 | 3408×2556, 10.919.232 B | `876575b51473f80df986bb6b899a40b1bc93995f6de1baec09127f985fbd7a96` |
| frontal angular | `/dev/v4l-subdev30` / 5 | 4000×3000, 15.024.000 B | `4978876d3572e11855ee2fa9badc7f89f7cd3ba230d76e8a9d10554ec9c4176a` |

Las pruebas se repitieron tras un arranque posterior: las cuatro volvieron a
dar cinco frames, sin errores y con hashes nuevos —por tanto no eran buffers
congelados—. El revelado Bayer manual produjo las evidencias:

- [trasera principal](../work/resultado-trasera-principal.jpg);
- [trasera angular](../work/resultado-trasera-angular.jpg);
- [frontal principal](../work/resultado-frontal-principal.jpg);
- [frontal angular](../work/resultado-frontal-angular.jpg).

La mesa/ventilador y el techo/lámpara coinciden con las referencias y el campo
de las angulares es claramente mayor. La trasera principal está desenfocada:
falta el driver de su actuador. El color es conversión Bayer manual. Se entrega
así porque es evidencia honesta de la capa que funciona, no se llama a esto una
cámara de escritorio terminada.

### Regresión de audio y una comparación A/B que salió cara

Dos arranques dieron micrófono enumerado pero silencioso. Los dos tenían el APM
sin contestar `APM_CMD_GET_SPF_STATE` y el pinctrl LPASS rechazado con
`-EACCES`. Para distinguir regresión de carrera se probó temporalmente un
`boot`/`vendor_boot` anterior, con backup, escritura y relectura. Fue una mala
comparación: el kernel antiguo no coincidía con los módulos ath12k instalados y
la tablet se quedó sin Wi‑Fi. La dueña la dejó en TWRP; por ADB se restauraron
exclusivamente `/dev/sda21` y `/dev/sda24`, verificando los hashes
`579bf1ec…` y `9293c93b…`. No se tocó ninguna otra partición.

El arranque completo desde TWRP cerró la duda: con la misma imagen de cámaras,
PipeWire grabó 729.285 muestras no nulas antes de usar CAMSS y 733.706 después
de capturar con los cuatro sensores. Las cámaras no silencian los DMIC; el fallo
del APM es una carrera de arranque preexistente que debe medirse por sus logs,
no inferirse de un solo WAV cero.

### Build limpia final, teclado y regresión cerrada

La build final se hizo con `KERNEL_CLEAN=1` desde el checkout fijado de
7.2-rc3. Produjo `boot.img` SHA-256
`f24fce56c9cbb816f15c61f907369ccc5d0fdae516dcfd219e2f4fdb920503b6` y
`vendor_boot.img`
`9293c93b0ab1a1d0ad90353ec50969a120046aa2835aa2a05a28528c3ca3702d`.
Los dos se escribieron y releyeron completos; los módulos ath12k firmados se
instalaron desde esa misma compilación.

El arranque desde TWRP reveló una regresión lateral real: el STM32 del teclado
había vuelto a V34 y el restaurador automático no lo encontraba. CAMSS añade
adaptadores CCI y desplazó la numeración Linux del pogo de `6-002a` a
`11-002a`; el helper asumía el primer número. Ahora localiza `*-002a` bajo el
driver `samsung-gts9u-stm32-pogo`, que es la identidad estable. Restauró y
releyó los 52.132 bytes oficiales, confirmó `00370037`, recibió el modelo
`0xd6` y creó de nuevo `Book Cover Keyboard Slim (EF-DX920)`. Un reinicio
posterior conservó V37 y el servicio concluyó sin escribir.

Sobre la build limpia se hicieron dos pasadas de cinco frames por cada sensor,
siempre a unos 30 fps y con hashes distintos. También se repitieron el estrobo
de veinte frames y la linterna a dos intensidades, terminando ambos apagados.
La regresión consolidada dejó Wi-Fi con 3/3 respuestas, Bluetooth activo,
teclado, Wacom, Goodix, DSI, acelerómetro, brújula y audio presentes. El
micrófono dio 756.694 muestras no nulas antes de CAMSS y 757.065 después de las
cuatro capturas; una tercera toma consolidada dio 455.636. Otro arranque de la
misma imagen volvió a caer en la carrera APM y produjo ceros, confirmando que el
problema sigue siendo intermitente y anterior al uso de cámaras. El único
servicio fallido fue el `lxc-net` preexistente. La batería estaba al 98 %, por
lo que se verificó el contrato PD de 5 V/3 A, no una sesión térmica de 25 W.

## Sesión 29 — color procesado y cámaras para aplicaciones

Fecha: 2026-08-09.

El siguiente criterio fue más alto que el de la sesión anterior: las fotos ya
no podían ser un revelado Bayer manual. Las cuatro cámaras tenían que converger
en exposición y balance de blancos, abrir sin root y presentarse al escritorio
como fuentes repetibles.

Se fijó `libcamera` en `62d4bfc` (0.7.2 + 53 commits) y se compiló solo el
pipeline `simple`, su software ISP, `cam` y el plugin GStreamer. HI1337 e HI847
recibieron ayudantes con la ganancia real `(code + 16) / 16` y pedestal 64 de
RAW10. El tuning común parte de ganancias roja/azul `[1, 4]`, usa AWB de mundo
gris, AE y una CCM conservadora. Esto eliminó la dominante de canales de la
primera conversión y permitió que paredes, techo, metal, blancos y el objeto
rojo conservaran relaciones de color coherentes.

PipeWire Noble necesitó tres backports acotados. El mapper 1.0.5 no entendía el
`string_view` de libcamera 0.7, trataba `ColourGains` array como escalar y
abortaba, y confundía nombres DRM RGB con orden de bytes en memoria. El último
fallo era la causa directa de la imagen magenta. Se empaquetó el SPA corregido
sin reemplazar el resto de PipeWire. Una regla udev entrega `/dev/udmabuf` al
grupo `video`, así que GStreamer y el software ISP funcionan como `ubuntu`, no
como root.

Las pruebas físicas finales fueron:

- 150/150 frames RGB de cada una de las cuatro cámaras, con imágenes finales
  [frontal angular](../work/resultado-frontal-angular.jpg),
  [frontal principal](../work/resultado-frontal-principal.jpg),
  [trasera principal](../work/resultado-trasera-principal.jpg) y
  [trasera angular](../work/resultado-trasera-angular.jpg);
- 99 frames por PipeWire y una [captura de esa ruta](../work/resultado-pipewire-app.jpg);
- 30 frames negociados en cada fuente PipeWire y otros 30 al reabrir la
  frontal angular; PipeWire, `pipewire-pulse` y WirePlumber siguieron activos;
- GNOME Cámara (`Snapshot` 46.2) abierta en una sesión gráfica, con su stream
  mostrado por WirePlumber como `active`;
- linterna en niveles 32 y 128, estrobo durante una secuencia de 20 frames y
  comprobación final `strobe=0`, `torch=0`, sin fallo latente.

Los paquetes instalados son `libcamera-gts9u 0.7.2+53.g62d4bfc-gts9u1`,
`libspa-0.2-libcamera-gts9u 1.0.5-gts9u1` y `ubuntu-gts9u-device 2.0`. La build
limpia final produjo `boot.img`
`d4323b9acd26a8b2179af1fda58536a1d8e622cde787a86406293e71d47b3eba` y
`vendor_boot.img`
`4441ae918f878a9592b2e5c863833d20dfefb44e50bb29645de97aa1f33eef5d`;
ambos se escribieron y releyeron con esos mismos hashes.

La última corrección fue de metadatos, no de imagen: el valor DT `2` significa
cámara externa, no trasera. Las dos traseras pasaron a `orientation = <1>` y el
DTB tuvo que llegar mediante `vendor_boot`. El DT vivo, los controles V4L2,
`cam --list` y PipeWire coinciden ahora: dos `Internal/Built-in Front Camera` y
dos `Internal/Built-in Back Camera`.

Tras reiniciar, Wi-Fi respondió 3/3, el teclado volvió a enumerar como
`Book Cover Keyboard Slim (EF-DX920)` con firmware V37, Bluetooth estaba
encendido, Wacom/Goodix presentes, DSI conectado, acelerómetro y brújula
entregando datos, y el micrófono produjo 438.846 muestras no nulas. El único
servicio fallido siguió siendo `lxc-net`, anterior y ajeno a cámaras. Queda
abierto el actuador de enfoque de la trasera principal; color, exposición y
ruta de aplicaciones ya no son el bloqueo.

## Sesión 30 — linterna de escritorio, reinicio multimedia y orientación

Fecha: 2026-08-09.

El flash ya encendía físicamente, pero todavía no era una función diaria. El
paquete `ubuntu-gts9u-device 2.1` añade un mosaico **Linterna** a los ajustes
rápidos de GNOME 46, un icono propio y el comando `gts9u-flashlight`. Udev
entrega a `video` solamente `brightness` con modo 0660; la ruta de estrobo
sigue reservada a root. Nivel 32, nivel 128, toggle, rechazo de 999 y apagado
previo a suspensión se probaron como el usuario `ubuntu`. En todos los cierres
el LED acabó en cero. El usuario confirmó que el mosaico funciona en la UI.

La tablet se reinició además porque ninguna aplicación reproducía vídeo y la
cámara había dejado de avanzar. Antes del reinicio había servicios activos,
pero también varias instancias históricas y errores
`spa.libcamera: can't add buffer ...: El archivo ya existe`. Tras arrancar con
boot ID `58ff3ce2-64c6-48f8-827a-ee52ccaa5e7c`, la ruta de vídeo procesó 120
frames RAW y codificó/decodificó 60 frames VP9. Después de limpiar una vez la
sesión PipeWire, las cuatro fuentes de cámara dieron 30 frames y la frontal se
reabrió otros 30; los tres servicios multimedia quedaron activos.

La orientación se comprobó con escena conocida. Cada fuente produjo 150 JPEG
por PipeWire y se revisó el último: las dos frontales muestran a la persona
derecha y la línea de la pared horizontal; la trasera angular muestra el
billete de 50 derecho. La principal trasera volvió a quedar demasiado
desenfocada a esa distancia para extraer orientación. Los controles V4L2 son
coherentes con el montaje —frontales 270°, traseras 90°— y PipeWire conserva
dos ubicaciones `front` y dos `back`, sin publicar una transformación adicional.
No se cambió una rotación correcta basándose en la única imagen no evaluable.

## Sesión 31 — estabilidad entre aplicaciones y autofoco DW9808

Fecha: 2026-08-09.

El criterio de cierre pasó a ser el uso real de las cuatro cámaras en GNOME
Cámara, navegador y OBS, con cambios repetidos sin pantallas negras. PipeWire
recibió cuatro correcciones adicionales: reutilización explícita de buffers en
los requests, no cerrar descriptores prestados por PipeWire, procesar los
completados en el bucle de datos y suprimir una transformación redundante. La
regresión alternó las cuatro fuentes en ambos sentidos: 16 capturas de 45
frames, 720 frames totales, cero fallos, cero `EEXIST`, cero descriptores
inválidos y el mismo PID de PipeWire al terminar.

GNOME Cámara completó dos ciclos y guardó ocho fotos; las imágenes físicas
confirmaron que las cuatro salen derechas. Chrome enumeró cuatro identificadores
WebRTC distintos —dos frontales y dos traseros— y abrió cada uno a
1280×720/30 fps sin errores. OBS usó cuatro escenas GStreamer/PipeWire, produjo
cuatro capturas correctas y mantuvo PipeWire estable. El plugin queda fijado en
el commit `a936d45` y empaquetado como `obs-gstreamer-gts9u`.

Después se abordó el enfoque. El módulo CamX stock identificó `dw9808` y dio su
secuencia exacta; una barrida I²C de 0 a 1023 demostró movimiento y cambio de
plano antes de escribir driver. El kernel incorpora ahora un subdispositivo
V4L2 de lente, comparte GPIO15 de forma segura con VIO del HI1337 y enlaza la
lente mediante `lens-focus`. El control `focus_absolute` respondió en vivo en
todo su rango.

La IPA software de libcamera recibió estadística de contraste, barrido grueso,
afinación local y seguimiento continuo. El primer intento mezcló los mapas
V4L2 del sensor y de la lente; WirePlumber abortó correctamente porque sus
identificadores pertenecen a subdispositivos distintos. Se sustituyó por un
canal IPC dedicado `setLensPosition`, se reinstaló el paquete y WirePlumber
volvió a publicar exactamente cuatro cámaras. Una captura de 41 fotogramas con
el flash registró el recorrido real de la lente y terminó con «Plano
Esquemático de la Red» legible. Las fotos posteriores de GNOME Cámara y las
capturas de OBS confirmaron el enfoque por la ruta completa de aplicaciones.

Los paquetes finales instalados son `libcamera-gts9u
0.7.2+53.g62d4bfc-gts9u2` y `libspa-0.2-libcamera-gts9u
1.0.5-gts9u6`. Los SHA-256 de los artefactos finales instalados son
`8078a33e33081568dee2406a26fe2b54b26047f9bc12a2bc4171748fab9c2f7e` y
`f8f938d4e38e4d5dfecdf7191854ab98990883d4b702602dadd8309f9088ea9a`.
También quedaron instalados `obs-gstreamer-gts9u
0.4.0+git20260809.a936d45-gts9u1` y `ubuntu-gts9u-device 2.2`, con SHA-256 de
paquete `8b3ae0e64d5ce98aeaa83d92a51ec99c8537bf1a50516ffa1b69bbdba07267cc`
y `2131a585a22d93f9d26cc97571885dd07f2e4bebe2ce0c858661198e60095935`.
Al cerrar las pruebas, Snapshot, Chrome y OBS estaban cerrados, el flash en
`off`, PipeWire/PipeWire Pulse/WirePlumber activos y las cuatro fuentes
libcamera publicadas. `lxc-net` seguía siendo el único servicio fallido,
preexistente y ajeno a este trabajo.

## Sesión 32 — cámaras V4L2 de sistema, campo completo y OBS estable

Fecha: 2026-08-09.

Las escenas GStreamer de OBS demostraban que los píxeles llegaban, pero no
resolvían la interfaz de sistema: navegadores y la fuente «Dispositivo de
captura de video (V4L2)» no podían descubrir las cuatro cámaras en una
instalación limpia. Se sustituyó esa integración por cuatro nodos
`v4l2loopback`, `/dev/video20`–`23`, con nombres GTS9U estables. El módulo queda
fijado en `9ef83fb9`, recibe dos correcciones de eventos/colas, se compila contra
el kernel exacto y se firma con su clave de build. Cuatro `v4l2-relayd` de
sistema conectan esos nodos bajo demanda con las fuentes libcamera de PipeWire.

CAMSS sólo permite una entrada física activa. El relé serializa por ello las
cuatro entradas con un bloqueo común, agrupa cierres de negociación durante
500 ms y destruye la entrada entre clientes reales. Una primera guarda de
750 ms pasó una ronda pero PipeWire terminó en `SIGSEGV` al acumular cambios:
el registro mostró dos configuraciones casi simultáneas y callbacks CAMSS aún
en vuelo. La guarda final de dos segundos se aplica también a la ruta de error.
Dos rondas consecutivas completaron después 24 aperturas, diez frames cada una,
con los mismos PID de PipeWire y del servicio y cuatro relés vivos.

Chrome, sin habilitar un backend de cámara especial, enumeró exactamente
`GTS9U-Front-Ultra-Wide`, `GTS9U-Front-Main`, `GTS9U-Rear-Main` y
`GTS9U-Rear-Ultra-Wide`; abrió las cuatro por WebRTC a 1280×720/30 fps. OBS
reprodujo primero el cierre comunicado por la usuaria. Sus nodos CAMSS RAW
aparecían antes que las cámaras procesadas y, además, el plugin de Noble
liberaba un puntero sin inicializar cuando faltaban los directorios V4L
`by-id`/`by-path`. `obs-v4l2-gts9u` corrige ambos casos y oculta únicamente las
tarjetas `Qualcomm Camera Subsystem`. El diálogo estándar mostró sólo las
cuatro GTS9U, abrió cada una y permaneció estable; no se instala ninguna escena
ni configuración de OBS.

La sensación de zoom tenía otra causa reproducible. El software ISP escalaba
para cubrir el destino y recortaba los laterales cuando cambiaba la relación de
aspecto. `libcamera-gts9u 0.7.2+53.g62d4bfc-gts9u3` usa ahora ajuste *contain*,
centrado y fondo negro: la salida V4L2 1280×960 conserva el sensor 4:3 completo
y los clientes 16:9 deciden si añaden barras o recortan. Las capturas físicas
confirmaron el campo mucho mayor de ambas ultra gran angular; la trasera
principal sigue siendo ópticamente más estrecha.

La integración limpia queda en `v4l2-relayd-gts9u 0.1.2-gts9u3`,
`obs-v4l2-gts9u 30.0.2+dfsg-3build1-gts9u1` y
`ubuntu-gts9u-device 2.5`. `build-ubuntu-rootfs.sh` incluye esos tres paquetes y
su huella de entradas, y ya no incluye `obs-gstreamer-gts9u`. Al cerrar la
validación, Chrome y OBS estaban cerrados, el flash estaba en `off`, PipeWire y
los cuatro relés seguían activos.

## Sesión 33 — persistencia tras reinicio y revisión de color

Fecha: 2026-08-09.

La primera prueba de arranque en frío descubrió un fallo real oculto por la
sesión gráfica. `ubuntu` tenía `Linger=no`: SSH levantaba un PipeWire temporal,
pero al salir terminaba `user@1000` y los relés de sistema quedaban conectados
al servidor muerto. Los cuatro nombres seguían presentes aunque las capturas
eran negras. `ubuntu-gts9u-device 2.6` habilita *linger* tanto en instalaciones
existentes como al construir un rootfs limpio. El lanzador espera además el
`MainPID` vivo de PipeWire y reinicia los cuatro relés si cambia o si termina
uno de ellos. La recuperación se provocó dos veces; en ambas cambió PipeWire,
se recreó el servicio y quedaron exactamente cuatro relés funcionales.

Se hicieron tres reinicios reales, con `boot_id` distintos. El último arrancó
el paquete 2.6 exacto, mantuvo estable PipeWire entre conexiones SSH separadas,
publicó `/dev/video20`–`23` y sus cuatro alias, conservó Wi-Fi, Bluetooth,
teclado pogo y Wacom, y dejó el flash apagado. Una captura acompasada posterior
al arranque produjo PNG reales de 1,08–1,43 MB en los cuatro nodos. Desde una
sesión GNOME normal, Chrome enumeró exactamente las cuatro cámaras y abrió cada
una a 1280×720/30; el selector estándar de OBS mostró sólo esas cuatro, inició
captura desde `/dev/video20` y permaneció vivo. La entrada automática usada
sólo para esa prueba se retiró y se restauró la configuración GDM original.

La habitación sin luz no permitía una calibración fotométrica completa. En las
frontales, iluminadas sólo por el monitor, las medias RGB fueron próximas a
neutro; las traseras, probadas con la linterna, mostraron un sesgo verde
moderado sobre zonas grises. Como el encuadre estaba dominado por una tarjeta y
tejidos rojos/marrones, el AWB de mundo gris puede explicar el sesgo y una CCM
global no sería segura. Se conserva el tuning actual hasta disponer de una
carta gris/color bajo varias temperaturas de iluminación. Al cerrar, Chrome y
OBS estaban cerrados, el flash en `off`, la configuración gráfica original
restaurada y los cuatro relés activos.

---

## Sesión 34 — la raíz se muda a la UFS interna, en un solo ZIP

Fecha: 2026-08-10. No se tocó la tablet física: esta sesión produce el artefacto
que la usuaria probará.

### Contexto

Hasta v0.17 la instalación tenía dos pasos y dos artefactos: escribir a mano una
imagen de dos particiones en una microSD, y flashear después un ZIP que escribía
las imágenes de arranque y aplicaba sobre la tarjeta el overlay de firmware. La
tarjeta era además un punto único de fallo y el cuello de botella de E/S.

El encargo era instalar en la UFS **sin crear, borrar ni modificar
particiones**, y entregar un único `.zip` flasheable.

### Qué se revisó antes de decidir

El port de Ubuntu Touch de referencia (`../port`) resuelve lo mismo escribiendo
`super` entero: reconstruye sus particiones lógicas con `lpmake` y mete ahí el
rootfs como `system`. Eso es exactamente lo que aquí no se quería, y además
`super` mide 11,2 GiB, que no da para un escritorio.

La inspección del dispositivo (`port/device-inspection/partitions.txt`) daba la
respuesta: `sda34`, la `userdata` de Android, mide 984 360 924 KiB, es decir
939 GiB. Ya existe. Reutilizarla no toca la GPT.

### Qué se hizo

- `scripts/build-ufs-image.sh` construye la raíz como **sistema de ficheros a
  secas**, sin tabla de particiones: `/boot` dentro, overlay de firmware y
  módulos ya integrado, etiqueta `UBTS9U_UFS`, `fstab` reescrito, `-E resize=`
  para poder crecer hasta 1 TiB en línea, y `e2fsck -fp` al final para no
  distribuir un sistema de ficheros sucio.
- La generación del initramfs sale a `scripts/make-initramfs.sh`, compartido por
  las dos imágenes; tener dos copias de esa comprobación era pedir que
  divergiesen justo donde el síntoma es una pantalla negra.
- El instalador TWRP escribe la raíz en `userdata` y la **verifica releyéndola**
  y comparando SHA-256, antes de tocar las imágenes de arranque. Aborta si el
  ZIP está en el propio destino, si `userdata` es menor que la imagen, o si la
  etiqueta releída no cuadra.
- `cmdline.txt` pasa a `root=LABEL=UBTS9U_UFS`, que además desambigua contra una
  microSD antigua.
- `ubuntu-gts9u-grow-rootfs` distingue los dos casos: en microSD extiende
  partición y sistema de ficheros; en UFS **solo** `resize2fs`.
- `validate-bundle.sh` cambia la garantía que comprueba: `userdata` ya puede
  nombrarse, pero ningún `mkfs`, `parted`, `sgdisk`, `sfdisk`, `fdisk`,
  `partx` ni `wipefs` puede aparecer en el instalador.
- `build-release.sh` deja de producir la imagen `.img.xz`: la release es el ZIP.

### Un fallo que la validación estática cazó

La primera build falló en `validate-bundle.sh` con «installer code references a
partition it must never write». No era un error real de escritura: era un
`ui_print` que decía la palabra `super` al explicar lo que **no** se toca. La
comprobación mira código con los comentarios eliminados, y una cadena visible no
es un comentario. Se reformuló el mensaje. La comprobación es correcta y se
dejó como está: prefiere un falso positivo a dejar pasar un `dd` a `super`.

### Estado del artefacto

v0.18: ZIP único de 3,1 GiB de imagen de raíz más las cinco imágenes de
arranque, todas las comprobaciones estáticas en verde. **Sin arrancar todavía en
la tablet**; hasta que arranque, la fila de almacenamiento del README y la de
UFS de `hardware-status.md` dicen pendiente.

### Cámaras

Se rehízo el kernel para incluir el parche 3 de `v4l2loopback` que había en el
árbol de trabajo, y la raíz lleva el conjunto actual de paquetes de cámara
(`libcamera-gts9u` gts9u5, SPA gts9u10, `v4l2-relayd` gts9u12, device 2.17). El
trabajo sobre el relevo entre cámaras sigue en curso y sin commitear; la
documentación pasa a decir lo que de verdad ocurre: cada cámara y el flash
funcionan, y cambiar de una a otra todavía falla.

---

## Sesión 35 — el primer flasheo real de la v0.18, y por qué abortó

Fecha: 2026-08-10. Dos intentos en la tablet, ninguno llegó a escribir nada.

### Intento 1, desde el almacenamiento interno

`Installing zip file '/sdcard/ubuntu-24.04-gts9uwifi-v0.18-sm-x910-twrp.zip'` →
`ERROR: the ZIP is stored on the installation target`.

Esto es la protección funcionando: `/sdcard` es `/data/media`, dentro de la
partición que el instalador va a sobrescribir. No hay nada que arreglar aquí,
salvo que el README y `boot-strategy.md` ya lo decían y conviene que se lea
antes.

### Intento 2, por sideload

`Installing zip file '/sideload/package.zip'` → `ERROR: malformed rootfs image
size`, con el ZIP intacto y verificado.

La causa es que TWRP ejecuta `update-binary` con **mksh**, cuya aritmética es de
32 bits aunque el binario sea aarch64 de 64. La imagen mide 3 271 557 120
bytes, que pasa de 2³¹ y se lee como negativo, así que `[ "$ROOTFS_SIZE" -gt 0 ]`
resultaba falso. Las comprobaciones previas pasaron porque todos los tamaños
anteriores (100 663 296 y menores) caben en 32 bits.

Se confirmó extrayendo el ramdisk de `TWRP-gts9u-V2.img`: `/sbin/sh` →
`/system/bin/sh`, ELF aarch64, y sus cadenas incluyen «Use 'exit' to leave
mksh». El mismo ramdisk confirmó que sí están disponibles `wc`, `dd`, `unzip`,
`sha256sum`, `tune2fs`, `e2fsck`, `blockdev`, `cut` y `resize2fs`.

### Qué se cambió

- El manifiesto `ROOTFS-IMAGE` publica ahora un tercer campo con el tamaño en
  MiB, y el instalador lee ese. Los bytes se conservan para las personas y para
  `validate-bundle.sh`.
- La comprobación de capacidad ya no compara `blockdev --getsize64` de
  `userdata` (~1,008 × 10¹², imposible en ese shell): lee con `dd` el último MiB
  que ocupará la imagen y comprueba que devuelve 1 048 576 bytes.
- `validate-bundle.sh` rechaza cualquier literal de diez cifras o más en el
  código del instalador.
- El banco de pruebas de loopback pasa a ejecutarse con `mksh` en lugar de
  `bash`. Ese es el fallo de método real: el banco había dado verde
  inmediatamente antes del flasheo, porque `bash` cuenta con 64 bits.

### Estado

v0.18 repaquetada. La imagen de raíz no cambia; sólo el instalador y el
manifiesto. Sigue sin arrancar en la tablet.
