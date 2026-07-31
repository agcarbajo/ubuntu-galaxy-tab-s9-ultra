# Artefactos generados

Este directorio se mantiene deliberadamente vacío en Git. Las imágenes de
microSD, los ZIP de TWRP, las imágenes de partición y los logs de build son
productos regenerables, ocupan mucho espacio y pueden contener firmware
propietario. Nunca deben publicarse en este repositorio.

Cada build entregable debe dejar aquí, localmente:

- la imagen comprimida de microSD;
- el ZIP TWRP con `boot`, `init_boot`, `vendor_boot` y `dtbo`;
- un `MANIFEST.txt` con los SHA-256 de todo lo anterior y la revisión de las
  fuentes que lo produjeron.

La vía de vuelta a postmarketOS no vive aquí: está en
`../../PostmarketOS/artifacts/`, junto a su propio manifiesto.
