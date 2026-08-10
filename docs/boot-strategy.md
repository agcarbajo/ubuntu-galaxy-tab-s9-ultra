# Cadena de arranque, instalación y recuperación

Última revisión: 2026-08-10. Hereda la cadena demostrada físicamente por
postmarketOS v1.71; lo que cambia es únicamente el rootfs y su initramfs.

Desde v0.18 el rootfs se instala en la **UFS interna** y la release es un solo
ZIP flasheable. La sección [Instalación en la UFS sin
reparticionar](#instalación-en-la-ufs-sin-reparticionar) explica por qué eso no
toca la tabla de particiones.

## Cadena demostrada

- El SM-X910 no usa slots A/B y Samsung ofrece Download Mode/Odin, no un
  `fastboot boot` utilizable.
- La cadena Android usa **boot header v4**.
- Samsung ABL carga el kernel de `boot`, el initramfs genérico de `init_boot` y
  el DTB, cmdline y bootconfig de `vendor_boot`, todos desde la UFS interna.
- El rootfs Linux es un **ext4 dentro de `userdata`**, en esa misma UFS. ABL no
  lee sistemas de ficheros: el kernel sale de `boot` y solo el initramfs busca
  la raíz, por etiqueta.
- La DTBO stock contiene interfaces downstream y no se aplica sobre un DTB
  mainline. El bundle escribe un `dtbo` que deliberadamente **no** es una tabla
  DT de Android, lo que hace que ABL use su fallback de DTB anexado al kernel.
- TWRP lleva su propio DTB/DTBO de recovery y sigue siendo recuperable aunque
  cambien las imágenes mainline.

Dos invariantes que no se pueden tocar:

- `APPEND_DTB_TO_KERNEL=1` y `DISABLE_RUNTIME_DTBO=1`. Con los valores
  contrarios ABL vuelve a su fork `ufdt`, rechaza el DTB base y entra en Odin
  antes de llegar a Linux.
- **Cambiar el DTS obliga a reescribir `vendor_boot`.** El ABL del X910 aplica
  el DTB de `vendor_boot`, no el anexado a `boot.img`. Reescribir solo `boot`
  deja el DTS antiguo en uso.

## Particiones utilizadas

| Partición | Tamaño exacto | Contenido |
|---|---:|---|
| `boot` | 100663296 | `Image.gz` + DTB anexado, header v4, sin ramdisk |
| `init_boot` | 8388608 | initramfs Ubuntu, LZ4 legacy |
| `vendor_boot` | 100663296 | DTB X910, cmdline, bootconfig y fragmento vendor con el firmware temprano de Bluetooth |
| `dtbo` | 16777216 | imagen no-tabla que fuerza el fallback appended-DTB |
| `vbmeta` | 131072 | AVB con verification/verity desactivados (`flags=2`) |
| `userdata` | 1007985586176 | rootfs ext4 de Ubuntu etiquetado `UBTS9U_UFS` |

La instalación **no** toca `super`, recovery, bootloader, PIT, EFS, persist,
modem/modemst ni calibraciones. En el TWRP usado durante el port `vbmeta` es de
solo lectura: el instalador verifica que ya contiene `flags=2` y lo conserva en
lugar de reescribirlo.

## Instalación en la UFS sin reparticionar

Ubuntu ocupa `userdata` porque es la única partición de este dispositivo con
sitio para un escritorio —939 GiB— y porque usarla no exige cambiar nada de la
tabla de particiones. La imagen ext4 se escribe con `dd` en una partición que
ya existe, y el sistema de ficheros crece hasta ocuparla entera en el primer
arranque.

Lo que esto garantiza, y por qué importa:

- **La GPT sigue siendo la de Samsung, byte a byte.** Ni el build ni el
  instalador ejecutan `sgdisk`, `parted`, `sfdisk`, `mkfs` ni `wipefs` contra
  el dispositivo; `scripts/validate-bundle.sh` falla si alguna de esas
  herramientas aparece en el instalador empaquetado. Por eso restaurar One UI
  sigue siendo un flasheo de Odin y nada más.
- **`super` no se toca**, así que la imagen de sistema de Android sigue ahí.
- **Los datos de usuario de Android sí se pierden**: son exactamente lo que
  ocupa la partición que se reutiliza. Esto no es un dual boot, y no hay
  partición sobrante donde dejarlos.

La alternativa era `super` (11,2 GiB), que no da para un escritorio y además
obligaría a reconstruir sus particiones lógicas. Reparticionar la UFS queda
descartado mientras exista esta opción.

El ZIP se flashea **desde fuera del almacenamiento interno**, que *es* la
partición que se sobrescribe: leer el ZIP de ahí lo destruiría a mitad de la
escritura, así que el instalador aborta si la ruta del ZIP está en `/data`,
`/sdcard` o equivalentes.

Por orden de comodidad:

1. **`adb sideload`.** El ZIP se sirve desde el PC y no ocupa nada en la
   tablet. Es la vía probada.
2. **USB-OTG**, si hay un pendrive a mano.
3. **microSD**, con una advertencia: TWRP monta en `/external_sd` la **primera**
   partición de la tarjeta, y si esa tarjeta lleva una instalación de las
   versiones microSD, su primera partición es `UBTS9U_BOOT`, de 256 MiB. Ahí no
   cabe un ZIP de ~1 GiB. Hace falta una tarjeta de datos normal.

### Etiquetas

| Etiqueta | Dónde | Qué es |
|---|---|---|
| `UBTS9U_UFS` | `userdata` | la raíz instalada, desde v0.18 |
| `UBTS9U_ROOT` | microSD | la raíz de las releases hasta v0.17 |

Son distintas a propósito. `root=LABEL=` resuelve a lo primero que encuentra, y
con la misma etiqueta en los dos sitios una tarjeta vieja olvidada en la ranura
arrancaría en lugar de la instalación nueva. Las tarjetas antiguas siguen
sirviendo de vuelta atrás si se reflashea su ZIP.

## Instalación en un solo paso

Flashear el ZIP desde TWRP. Escribe el rootfs en `userdata`, lo verifica por
hash releyéndolo, y después escribe `boot`, `init_boot`, `vendor_boot` y
`dtbo`. Ese orden es deliberado: si falla la parte larga, el dispositivo
conserva las imágenes de arranque que ya tenía y sigue estando a un reintento
de donde estaba.

El firmware de GPU, ADSP, Wi-Fi y audio va **dentro** de la imagen del rootfs,
no en un overlay aplicado después. El estado intermedio de «tarjeta incompleta»
de las versiones microSD ya no existe.

Las herramientas de build **nunca** escriben en una partición. La usuaria
flashea el ZIP a mano.

### ZIPs de actualización

Un ZIP sin `rootfs.img` pero con overlay actualiza en sitio una instalación ya
existente: monta la raíz de `userdata` tras comprobarla con `e2fsck -p`,
sustituye firmware, módulos y configuración, y no toca los datos. Es la vía
para probar un kernel nuevo sin reinstalar. Los dos contenidos son excluyentes
y `make-twrp-zip.py` rechaza generar un ZIP con ambos.

## Iteración sobre un sistema ya arrancado

Cuando Ubuntu arranque, los cambios de kernel o DTS podrán probarse escribiendo
solo la imagen estrictamente necesaria desde el sistema vivo, siempre con
autorización explícita:

- `boot` para el kernel;
- `vendor_boot` para DTS, cmdline o bootconfig;
- ambos cuando el kernel y los módulos ath12k formen un conjunto firmado nuevo.

Antes de cada escritura: backup temporal, comprobación de tamaño, `dd
conv=fsync` y comparación SHA-256 entre origen y destino. Nunca se codifican
números `sdaN`; se usan los enlaces estables de `/dev/disk/by-partlabel/`.

El kernel lockdown exige que `boot` y los módulos instalados en la raíz
—ath12k y v4l2loopback— procedan de la **misma** compilación. Recrear el árbol
`O=` genera una clave de firma nueva y los módulos antiguos pasan a rechazarse
con «Operation not permitted»: hay que sincronizar siempre los módulos junto al
kernel.

## Particularidades de arranque que Ubuntu debe conservar

- El panel ANA38407 no queda accesible tras el hand-off frío de Samsung. Antes
  de iniciar el display manager hace falta un único suspend/resume de
  plataforma (`pm_test=platform`) que recupera DDIC, DPU y sesión gráfica. En
  Ubuntu esto se ordena `Before=gdm3.service`.
- Si hay un dock DisplayPort ya conectado, su HPD debe permanecer **aplazado**
  hasta terminar esa recuperación. Un HPD temprano bloqueó también el DSI
  interno en las pruebas de la baseline.
- La consola visible temprana no es un requisito: ABL puede añadir
  `console=null`. El journal persistente y TWRP son las fuentes fiables de
  diagnóstico.
- Los proveedores críticos del kernel son **built-in**. Este port no instala ni
  autocarga un árbol general de módulos; solo distribuye los dos módulos ath12k
  firmados de forma aislada. Un símbolo crítico que quede en `=m` normalmente
  hace que el subsistema no aparezca en absoluto.

## Procedimiento exacto de instalación

Los pasos que ejecuta la usuaria. Ninguna herramienta del proyecto los hace por
ella.

### Antes de empezar

1. Comprobar que los hashes del `MANIFEST-v<versión>.txt` coinciden con los
   ficheros descargados.
2. Tener a mano la vía de vuelta: el ZIP y la imagen de postmarketOS v1.71 con
   su `MANIFEST-v1.71-rollback.txt`.
3. Asumir que **lo que Android guarde en `userdata` se pierde**. Es la
   partición donde se instala Ubuntu. `super`, el bootloader, EFS y las
   calibraciones no se tocan.
4. Tener el ZIP fuera del almacenamiento interno, que es la partición que se
   sobrescribe. Lo más simple es `adb sideload`; ver la lista de medios de la
   sección anterior.

### Paso único — flashear el ZIP desde TWRP

1. Arrancar en TWRP. Para sideload: `Advanced` → `ADB Sideload`, y desde el PC
   `adb sideload <zip>`. Con un medio externo: `Install` → seleccionar el ZIP.
2. Esperar. La escritura del rootfs tarda varios minutos, no muestra progreso,
   y va antes que las imágenes de arranque a propósito.
3. Leer la salida. El instalador aborta si el dispositivo no es un SM-X910, si
   el tamaño de alguna partición no cuadra, si `vbmeta` no tiene AVB flags 2,
   si `userdata` es más pequeña que la imagen, si el ZIP está en el destino, si
   `userdata` sigue montada, o si lo releído no coincide con el SHA-256 de la
   imagen.
4. El ZIP **no reinicia**. Reiniciar a mano cuando termine.
5. En el primer arranque el sistema de ficheros crece hasta ocupar las 939 GiB.
   Solo se redimensiona el sistema de ficheros: la partición ya era así.

### Si algo va mal

El ZIP no formatea, no reparticiona y no reinicia, así que un fallo a mitad
deja el dispositivo en TWRP, que sigue siendo accesible. Desde ahí:

- reintentar el flasheo, o
- volver a postmarketOS con sus dos pasos, o
- entrar en Download Mode y restaurar el firmware oficial con Odin.

Un fallo durante la escritura del rootfs deja `userdata` a medias, pero las
imágenes de arranque intactas: no hay un estado en que el dispositivo tenga un
kernel nuevo y ningún sistema que arrancar.

## Recuperación

Por orden:

1. **Volver a postmarketOS v1.71**: reescribir la microSD con la imagen de
   rollback y flashear el ZIP v1.71. Ambos artefactos se conservan fuera de Git
   en `../PostmarketOS/artifacts/`, con su manifiesto de hashes. Esa instalación
   vive en la tarjeta y no depende de lo que haya en `userdata`.
2. **TWRP y `adb`**, para montar la raíz de `userdata`, extraer el journal y
   restaurar imágenes.
3. **Download Mode y Odin** con el firmware oficial X910XXS5CYG1. Sigue siendo
   un paso, porque la GPT nunca se ha modificado.

Las copias se restauran mediante `/dev/block/by-name/<partición>`, nunca con
números de LUN codificados. EFS solo puede montarse `ro,noload` cuando haga
falta leer la dirección Bluetooth; jamás se escribe.

## Futuro: dual boot

El rootfs ya vive en la UFS. Lo que queda es instalarlo **junto a Android en
lugar de en su sitio**, que exige un diseño separado de layout, selector y
recuperación. La regla no cambia: **no se reparticionará la UFS ni se
reutilizará `super`**. Un dual boot que dependa de mover particiones no es una
opción; si llega, será compartiendo las que ya existen.
