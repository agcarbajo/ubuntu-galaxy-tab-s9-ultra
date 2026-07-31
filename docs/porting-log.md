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

### Siguiente paso

Construir el perfil `desktop` y preparar la primera prueba física con
instrucciones exactas y la vía de vuelta a v1.71 verificada. Ningún componente
de hardware se marcará como funcional bajo Ubuntu hasta observarlo.
