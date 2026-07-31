# cmdline y bootconfig de `vendor_boot`

El ABL del X910 toma la cmdline y el bootconfig de `vendor_boot`, no de
`boot.img`. Cambiar cualquiera de los dos exige regenerar y reflashear
`vendor_boot`.

## Por qué la cmdline no es la de postmarketOS

`cmdline.pmos.txt` es la copia de referencia del port postmarketOS, importada
para poder comparar. **No se usa.** La cmdline de Ubuntu difiere en tres cosas,
y una de ellas es imprescindible:

| Diferencia | Motivo |
|---|---|
| `root=LABEL=UBTS9U_ROOT rootfstype=ext4` **añadido** | El initramfs de postmarketOS localiza su partición por sí mismo, así que su cmdline no lleva `root=`. `initramfs-tools` **no** hace eso: sin `root=` espera a un dispositivo que nunca llega y termina en la shell de emergencia. Se indica por etiqueta porque el orden de enumeración entre la microSD y la UFS no está garantizado |
| `ignore_console_null` **eliminado** | Es un parámetro del parche `ignore-console-null.patch`, que este port **no** aplica por defecto: el kernel validado de la build directa tampoco lo llevaba. Pasar un parámetro que ningún código lee solo genera ruido |
| `pmos.nosplash` **eliminado** | Específico de postmarketOS |

Se conservan `rootwait` —la microSD tarda en enumerar—, `panic=10` y
`msm.separate_gpu_kms=1`, sin el cual Adreno no crea su render node.

Si se activa el parche de consola con `APPLY_IGNORE_CONSOLE_NULL=1`, hay que
añadir `ignore_console_null` aquí y regenerar `vendor_boot`.
