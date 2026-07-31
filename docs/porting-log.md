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
repitió el proceso ejecutando antes `scripts/sync-pmaports.sh`, de modo que la
imagen de rollback procede de las fuentes congeladas.

Conclusión reutilizable: la base de build en WSL no es una fuente de verdad. La
fuente es el repositorio, y `sync-pmaports.sh` debe ejecutarse antes de
cualquier build que se vaya a entregar.

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
- Ninguna partición, tarjeta ni instalación física modificada.

### Siguiente paso

Importar kernel, DTS, drivers, parches y configuración con atribución por
fichero, y construir el primer rootfs Ubuntu 24.04 arm64 con `mmdebstrap`.
