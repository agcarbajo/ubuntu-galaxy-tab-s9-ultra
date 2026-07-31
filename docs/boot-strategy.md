# Cadena de arranque, instalación y recuperación

Última revisión: 2026-07-31. Hereda la cadena demostrada físicamente por
postmarketOS v1.71; lo que cambia es únicamente el rootfs y su initramfs.

## Cadena demostrada

- El SM-X910 no usa slots A/B y Samsung ofrece Download Mode/Odin, no un
  `fastboot boot` utilizable.
- La cadena Android usa **boot header v4**.
- Samsung ABL carga el kernel de `boot`, el initramfs genérico de `init_boot` y
  el DTB, cmdline y bootconfig de `vendor_boot`, todos desde la UFS interna.
- El rootfs Linux vive en una **microSD ext4**. ABL no busca kernel en la
  tarjeta.
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

La instalación **no** toca `super`, `userdata`, recovery, bootloader, PIT, EFS,
persist, modem/modemst ni calibraciones. En el TWRP usado durante el port
`vbmeta` es de solo lectura: el instalador verifica que ya contiene `flags=2` y
lo conserva en lugar de reescribirlo.

## Instalación en dos pasos

1. **Escribir la imagen en la microSD.** Primero `sgdisk --zap-all` para borrar
   metadatos GPT antiguos, después escribir la imagen y **verificar por hash lo
   leído de vuelta** antes de reiniciar. La partición raíz se expande en el
   primer arranque.
2. **Flashear el ZIP TWRP.** Escribe `boot`, `init_boot`, `vendor_boot` y
   `dtbo`, y aplica sobre la tarjeta el overlay con firmware y configuración.

Hasta completar el segundo paso la tarjeta está incompleta: el firmware de GPU,
ADSP y audio llega en ese overlay, no en la imagen del rootfs. No debe
esperarse aceleración ni paridad de hardware antes de terminar el paso 2.

Las herramientas de build **nunca** escriben en una partición ni en una
tarjeta. La usuaria escribe la microSD y flashea el ZIP a mano.

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

El kernel lockdown exige que `boot` y los módulos ath12k instalados en la
microSD procedan de la **misma** compilación. Recrear el árbol `O=` genera una
clave de firma nueva y los módulos antiguos pasan a rechazarse con «Operation
not permitted»: hay que sincronizar siempre los dos módulos junto al kernel.

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
3. Confirmar **qué microSD** se va a sobrescribir. Se borra por completo.

### Paso 1 — escribir la microSD

Con la tarjeta en el lector del PC, identificada sin ambigüedad:

```bash
xz -dc ubuntu-24.04-gts9uwifi-v<versión>-sd.img.xz > ubuntu-sd.img
sudo sgdisk --zap-all /dev/<tarjeta>
sudo dd if=ubuntu-sd.img of=/dev/<tarjeta> bs=4M status=progress conv=fsync
```

Verificar lo leído de vuelta antes de sacar la tarjeta, comparando con
`uncompressed_sd_image_sha256` del manifiesto:

```bash
sudo dd if=/dev/<tarjeta> bs=4M count=<bloques-de-la-imagen> | sha256sum
```

### Paso 2 — flashear el ZIP desde TWRP

1. Copiar el ZIP a `/sdcard` o a un USB.
2. Arrancar en TWRP.
3. `Install` → seleccionar el ZIP.
4. Leer la salida: el instalador aborta si el dispositivo no es un SM-X910, si
   el tamaño de alguna partición no cuadra, si `vbmeta` no tiene AVB flags 2 o
   si la microSD no lleva una raíz Ubuntu etiquetada `UBTS9U_ROOT`.
5. El ZIP **no reinicia**. Reiniciar a mano cuando termine.

### Si algo va mal

El ZIP no formatea, no borra y no reinicia, así que un fallo a mitad deja el
dispositivo en TWRP, que sigue siendo accesible. Desde ahí:

- reintentar el flasheo, o
- volver a postmarketOS con los dos pasos equivalentes, o
- entrar en Download Mode y restaurar el firmware oficial con Odin.

## Recuperación

Por orden:

1. **Volver a postmarketOS v1.71**: reescribir la microSD con la imagen de
   rollback y flashear el ZIP v1.71. Ambos artefactos se conservan fuera de Git
   en `../PostmarketOS/artifacts/`, con su manifiesto de hashes.
2. **TWRP y `adb`**, para montar la microSD, extraer el journal y restaurar
   imágenes.
3. **Download Mode y Odin** con el firmware oficial X910XXS5CYG1.

Las copias se restauran mediante `/dev/block/by-name/<partición>`, nunca con
números de LUN codificados. EFS solo puede montarse `ro,noload` cuando haga
falta leer la dirección Bluetooth; jamás se escribe.

## Futuro: rootfs en UFS y dual boot

La UFS enumera correctamente, pero este port mantiene el rootfs en microSD. Un
Ubuntu instalado en UFS o un dual boot exige antes un diseño separado de
layout, selector y recuperación. **No se reparticionará UFS ni se reutilizará
`super`** hasta que Ubuntu alcance paridad razonable desde microSD y exista un
procedimiento reversible probado.
