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
  `2376e12699b4ba93287435a81cdae4ef767aa7235069f3bd18c480ea2d08bcc5`;
- imagen SD comprimida: SHA-256
  `e43500ebf2c1bb321fe8ccbd79fc1885090d8f25b27a2e465bc8c5ecc27e2fcb`.

Nada se ha flasheado y el driver todavía no puede marcarse funcional. La
siguiente evidencia exigida es que `i2c15` sondee `0x2a`, aparezca el
dispositivo de entrada y las pulsaciones físicas generen eventos correctos sin
regresiones en audio, Wi-Fi, rotación ni suspensión.
