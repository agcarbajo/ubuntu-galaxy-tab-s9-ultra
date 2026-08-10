# Artefactos generados

Este directorio se mantiene deliberadamente vacío en Git. Los ZIP de TWRP, las
imágenes de partición y de raíz, y los logs de build son productos
regenerables, ocupan mucho espacio y pueden contener firmware propietario.
Nunca deben publicarse en este repositorio.

Cada build entregable debe dejar aquí, localmente:

- el ZIP TWRP, que desde v0.18 lleva dentro `boot`, `init_boot`,
  `vendor_boot`, `dtbo`, `vbmeta` y la raíz que se instala en la UFS, y es el
  único artefacto que la usuaria necesita;
- un `MANIFEST.txt` con los SHA-256 de todo lo anterior y la revisión de las
  fuentes que lo produjeron.

Hasta v0.17 se entregaba además una imagen comprimida de microSD.

La vía de vuelta a postmarketOS no vive aquí: está en
`../../PostmarketOS/artifacts/`, junto a su propio manifiesto.
