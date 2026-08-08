# Construcción del rootfs Ubuntu 24.04 arm64

Última revisión: 2026-07-31. Documento de arquitectura del Hito 1; todavía no
describe un sistema arrancado.

Este documento define **cómo se construye** el userspace Ubuntu y qué
decisiones son propias de Ubuntu. La cadena de arranque está en
[`boot-strategy.md`](boot-strategy.md); lo que se hereda del port postmarketOS
está en [`hardware-status.md`](hardware-status.md).

## Principio rector

El hardware ya está resuelto en el kernel. Ubuntu no debe reinventar nada de
eso: aporta únicamente userspace. Por tanto el pipeline se divide en dos
mitades con responsabilidades separadas:

| Mitad | Origen | Qué produce |
|---|---|---|
| Kernel y arranque | Fuentes importadas del port pmOS (`kernel/`) | `boot`, `init_boot`, `vendor_boot`, `dtbo`, módulos ath12k |
| Userspace | `mmdebstrap` sobre archive.ubuntu.com/ports | rootfs ext4 de la microSD |

Ninguna de las dos mitades puede depender de que la otra se haya montado a
mano en una instalación viva.

## Herramienta de construcción: mmdebstrap

Se usa **`mmdebstrap`**, no `debootstrap` ni una imagen preinstalada de
Ubuntu, por tres razones concretas:

1. acepta un `--architecture=arm64` con `qemu-user-static` y no exige un
   entorno arm64 nativo, que aquí no existe: el build corre en WSL x86-64;
2. permite `--customize-hook` para inyectar configuración, paquetes locales y
   overlays **dentro** de la misma invocación, de forma que el rootfs no se
   modifica después «a mano»;
3. produce el mismo resultado a partir del mismo manifiesto de paquetes, y
   permite fijar el snapshot del archivo si más adelante hace falta
   reproducibilidad estricta.

`debootstrap` se descarta como herramienta principal porque necesitaría una
segunda fase de configuración fuera de la herramienta, que es exactamente el
patrón «instalación irrepetible» que este proyecto prohíbe.

### Suite y componentes

- Suite: `noble` (Ubuntu 24.04 LTS).
- Arquitectura: `arm64`.
- Componentes: `main`, `restricted`, `universe`, `multiverse`.
- Mirror: `http://ports.ubuntu.com/ubuntu-ports`.
- Bolsillos habilitados: `noble`, `noble-updates`, `noble-security`.

`ports.ubuntu.com` es obligatorio: `archive.ubuntu.com` no publica arm64.

### Conjunto de paquetes del primer rootfs

El objetivo del Hito 1/2 es un sistema que arranque, tenga red y SSH. El
escritorio se instala en el mismo rootfs porque el Hito 3 lo necesita y
reconstruir es barato, pero el orden de validación sigue siendo
consola → red → escritorio.

Base y arranque:

```
ubuntu-minimal, ubuntu-standard, systemd, systemd-sysv, udev,
initramfs-tools, linux-firmware (solo lo genérico; los blobs Samsung/Qualcomm
llegan por el overlay del ZIP), e2fsprogs, dosfstools, parted, gdisk,
zstd, xz-utils
```

Red y acceso:

```
netplan.io, network-manager, wpasupplicant, openssh-server, avahi-daemon,
iputils-ping, curl, ca-certificates
```

Escritorio:

```
ubuntu-desktop-minimal, gdm3, gnome-shell, gnome-control-center,
gnome-session, mutter, xdg-desktop-portal-gnome,
mesa-vulkan-drivers, mesa-utils, libgl1-mesa-dri, vulkan-tools,
pipewire, pipewire-pulse, wireplumber, pipewire-audio-client-libraries,
libspa-0.2-bluetooth, bluez, alsa-ucm-conf, alsa-utils,
iio-sensor-proxy, upower, power-profiles-daemon
```

Diagnóstico durante el bring-up:

```
gdb, strace, evtest, i2c-tools, usbutils, pciutils, ethtool, tree,
libdrm-tests, drm-info, edid-decode
```

`ubuntu-desktop-minimal` en lugar de `ubuntu-desktop` deja fuera ofimática y
snaps de escritorio que no aportan nada al bring-up. Snap se evalúa como tema
separado en el Hito 5, no se asume desde el principio.

### Decisiones de Ubuntu que deben probarse primero en su forma nativa

De la baseline postmarketOS se hereda hardware, **no** parches de userspace.
Estas piezas deben probarse nativas antes de portar nada:

| Pieza | pmOS/Alpine | Ubuntu 24.04 — probar primero |
|---|---|---|
| Greeter | cuentas `gdm-greeter-*` creadas a mano porque Alpine compila systemd sin `systemd-userdbd` | GDM3 nativo: Ubuntu **sí** trae `systemd-userdbd`, así que el workaround no debe copiarse |
| Servidor de sonido | PulseAudio 17 | PipeWire + WirePlumber, con `pipewire-pulse` como capa de compatibilidad |
| Topología GPU/DPU partida | Xorg parcheado + reverse PRIME | Mutter/Wayland gestiona `card0` (Adreno, render) y `card1` (DPU, KMS) sin parches; el stack Xorg de pmOS **no** se porta |
| Rotación | Mutter r6 parcheado | Mutter de Ubuntu tal cual; el parche solo se porta si reaparece la regresión concreta (ratón externo desactiva la autorrotación) |
| Escalado | ajustes GTK/Xft manuales de XFCE | `scale-monitor-framebuffer` de Mutter y escalado 200 % de GNOME |
| Sensores | `iio-sensor-proxy` 3.9 parcheado + `libssc` + `hexagonrpcd` | `iio-sensor-proxy` de Ubuntu; `libssc`/`hexagonrpcd` **sí** hay que empaquetarlos porque no existen en Ubuntu. Los tres llevan parches propios, `libssc` incluido |
| Gestión de red | NetworkManager | NetworkManager con netplan como frontend (por defecto en Ubuntu) |

Lo que **no** se traduce y hay que reempaquetar como `.deb`:

- `libssc` y `hexagonrpcd` (cliente SSC/FastRPC de los sensores). `libssc`
  lleva parche propio: su espera síncrona giraba el contexto GLib sin bloquear,
  lo que costaba un núcleo entero en cuanto el SSC dejaba una petición sin
  contestar;
- `pd-mapper` (imprescindible: sin él el ADSP no publica `servreg locator` y no
  aparece la tarjeta ALSA);
- el paquete de dispositivo con udev, UCM, servicios de recuperación y
  `deviceinfo` equivalentes.

## Estructura del rootfs y la microSD

La microSD lleva **dos particiones**, como en la baseline:

| Partición | FS | Etiqueta | Contenido |
|---|---|---|---|
| 1 | ext4 | `UBTS9U_BOOT` | `initramfs-extra`, DTB de referencia y metadatos de build |
| 2 | ext4 | `UBTS9U_ROOT` | rootfs Ubuntu |

Dos particiones y no una: el initramfs que cabe en `init_boot` (8 MiB) no puede
contener el árbol completo de módulos, y en la baseline se demostró que la
alternativa de una sola partición produce un initramfs de ~15 MiB imposible de
empaquetar. La segunda etapa vive en la partición de boot de la tarjeta.

Las etiquetas son nuevas a propósito. Reutilizar `pmOS_boot`/`pmOS_root` haría
que un initramfs de postmarketOS y otro de Ubuntu compitiesen por la misma
tarjeta; con etiquetas distintas cada sistema solo monta la suya y una tarjeta
mal identificada falla de forma ruidosa en lugar de silenciosa.

La imagen se genera pequeña (rootfs + margen) y una unidad
`ubuntu-gts9u-grow-rootfs.service` expande partición y filesystem en el primer
arranque. Dimensionar la imagen para una tarjeta concreta solo traslada el
problema a la siguiente tarjeta.

## initramfs propio de Ubuntu

**No se reutiliza el initramfs de postmarketOS.** Ubuntu genera el suyo con
`initramfs-tools`, y debe cumplir cuatro requisitos que no vienen por defecto:

1. **Localizar la microSD sin números de dispositivo.** El root se indica por
   `root=LABEL=UBTS9U_ROOT`, nunca `mmcblk1p2`. El orden de enumeración de
   `sdhc_2` frente a la UFS no está garantizado.
2. **Esperar a que aparezca la tarjeta.** `rootwait` ya está en la cmdline de
   `vendor_boot`; además el hook local reintenta el `blkid` en lugar de caer al
   shell de emergencia al primer fallo.
3. **Empaquetarse en LZ4 legacy.** Esto es innegociable: el ABL del X910
   concatena el ramdisk genérico de `init_boot` con el fragmento de
   `vendor_boot`, y con un ramdisk genérico gzip Linux rechaza el initrd con
   «invalid magic at start of compressed archive» aunque la imagen Android sea
   válida. `initramfs-tools` se configura con `COMPRESS=lz4` y el empaquetador
   verifica la magia `02 21 4c 18`.
4. **Caber en 8 MiB menos el footer AVB.** `MODULES=dep` y no `most`. Como los
   proveedores críticos de este port son built-in, el initramfs no necesita un
   árbol grande de módulos; si aun así no cabe, la solución es mover módulos a
   `initramfs-extra` en la partición de boot, no recortar drivers necesarios.

El script de validación comprueba los cuatro puntos sobre la imagen generada,
sin flashear nada.

## Firmware

El repositorio no contiene blobs. Los helpers `scripts/stage-stock-*.sh` se
adaptan del port pmOS conservando sus hashes fijados y cambian únicamente el
destino, que en Ubuntu es la jerarquía Debian:

| Contenido | Ruta en el rootfs Ubuntu |
|---|---|
| GPU Adreno 740 (`a740_*`, `gmu_gen70200.bin`) | `/lib/firmware/qcom/` |
| ADSP Samsung (`adsp*.mdt`, `adsp*.bNN`, `*.jsn`) | `/lib/firmware/qcom/sm8550/` |
| Topología AudioReach | `/lib/firmware/qcom/sm8550/Samsung-Galaxy-Tab-S9-Ultra-tplg.bin` |
| Wi-Fi WCN7850 (amss oficial + BDF QRD en ELF) | `/lib/firmware/ath12k/WCN7850/hw2.0/` |
| Bluetooth (`hmtbtfw20.tlv`, `hmtnv20.b21`) | `/lib/firmware/qca/` |
| CS35L45 (protección, aún no cargada) | `/lib/firmware/` |
| Árbol HexagonFS de sensores | `/usr/share/qcom/sm8550/Samsung/gts9uwifi/` |

En Ubuntu `/lib` es un symlink a `/usr/lib`, igual que en el initramfs de
postmarketOS. Es la misma trampa que rompió la v0.69 de aquel port: el overlay
debe escribirse en `/usr/lib/firmware/...`, nunca crear un directorio `/lib`
sobre el symlink.

`hmtbtfw20.tlv` y `hmtnv20.b21` deben ir **también** en el fragmento vendor del
`vendor_boot`, porque `hci_qca` es built-in y sondea antes de montar la
microSD.

## Usuario, locale y entrada

- Usuario gráfico `ubuntu` con `sudo`, creado dentro del `--customize-hook`.
- Locale `es_ES.UTF-8`, zona horaria `Europe/Madrid`, teclado `es`.
- Hostname distinto del de postmarketOS para no confundir dos sistemas en la
  misma LAN.
- Escalado 200 % por defecto: 2960×1848 en 14,6" es inusable al 100 %.
- SSH habilitado con clave; contraseña del usuario fuera del repositorio.

## Pipeline de build

Todo se ejecuta como root dentro de `wsl.exe -d Ubuntu-24.04`, con base en
`/root/ubuntu-gts9u`. Ningún script acepta un dispositivo de bloque ni escribe
en una partición.

| Paso | Script | Produce |
|---|---|---|
| 0 | `install-build-deps.sh` / `check-build-deps.sh` | entorno de build comprobado |
| 0 | `fetch-mainline.sh` | checkout fijado en `a13c140c` (7.2-rc3) |
| 0 | `stage-android-tools.sh` | `mkbootimg`, `mkdtboimg`, `avbtool` |
| 0 | `import-kernel-sources.sh` | reimporta DTS, drivers y parches con hash de origen |
| 1 | `build-mainline-kernel.sh` | `Image.gz`, DTB, config y módulos ath12k |
| 2 | `build-ubuntu-rootfs.sh` | rootfs Ubuntu arm64 con `mmdebstrap` |
| 3 | `build-rootfs-overlay.sh` | overlay de módulos y firmware para la microSD |
| 4 | `build-sd-image.sh` | initramfs Ubuntu e imagen de dos particiones |
| 5 | `build-android-v4-bundle.sh` | `boot`, `init_boot`, `vendor_boot`, `dtbo`, `vbmeta` |
| 6 | `make-twrp-zip.py` | ZIP TWRP determinista |
| 7 | `validate-bundle.sh` | validación estática, sin flashear |
| — | `build-release.sh` | encadena 1–7 y escribe el manifiesto |

`build-sd-image.sh` falla la build si el initramfs no es LZ4 legacy o no cabe
en `init_boot`. Esos dos errores se descubren aquí y no en la tablet.

## Orden de validación

1. `systemd` llega a `multi-user.target` con journal persistente.
2. Wi-Fi y SSH.
3. GDM y sesión GNOME Wayland.
4. GPU acelerada comprobada con `eglinfo`/`vulkaninfo`, no supuesta.
5. Resto de paridad de hardware.

Ningún componente se marca funcional en la matriz por el hecho de que su
driver haya enlazado.
