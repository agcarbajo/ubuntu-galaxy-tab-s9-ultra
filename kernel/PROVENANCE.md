# Procedencia de las fuentes de kernel importadas

Todo lo que hay bajo `kernel/` procede del port postmarketOS del mismo
dispositivo y conserva su licencia y autoría:

- Repositorio de origen:
  <https://github.com/agcarbajo/postmarketos-galaxy-tab-s9-ultra>
- Commit de referencia del relevo: `b1dcca0`
- Paquete de origen:
  `pmaports/device/testing/linux-samsung-gts9uwifi-mainline/`
- Baseline: postmarketOS v1.71, kernel package r114
- Kernel base: Linux mainline 7.2-rc3, commit
  `a13c140cc289c0b7b3770bce5b3ad42ab35074aa`

Licencias, sin excepción:

| Ruta | Licencia | Motivo |
|---|---|---|
| `kernel/drivers/*.c` | `GPL-2.0-only` | Obras derivadas de Linux |
| `kernel/patches/*.patch` | `GPL-2.0-only` | Obras derivadas de Linux |
| `kernel/dts/*.dts` | `BSD-3-Clause` | Convención de los DTS Qualcomm upstream |
| `kernel/config/*` | `MIT` | Configuración del proyecto |

La cabecera SPDX de cada fichero prevalece sobre el MIT por defecto del
repositorio.

## Inventario

Se completa a medida que se importa cada fichero, con el hash SHA-256 de la
copia de origen para poder detectar divergencias futuras.

| Fichero | Origen en el port pmOS | SHA-256 de origen |
|---|---|---|
| _(pendiente de importar)_ | | |
