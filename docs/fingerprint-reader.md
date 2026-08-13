# Lector de huellas EL721 bajo Ubuntu

Este documento describe la infraestructura experimental del lector óptico en
pantalla del Galaxy Tab S9 Ultra Wi-Fi (`SM-X910`). **El registro, la
verificación y el inicio de sesión con huella todavía no funcionan**: no se
instalará ni anunciará soporte en GNOME hasta disponer de un backend seguro para
`libfprint`/`fprintd` y validarlo en la tablet.

## Identificación confirmada

- Sensor: EgisTec EL721, identificado por el overlay R03 y el controlador GPL
  oficial de Samsung para la familia `el7xx`.
- Tipo: lector óptico bajo el panel AMOLED.
- Alimentación: LDO2 del PM8550B a 3,3 V (`VDD_BTP_3P3`).
- Enable/reset: TLMM GPIO155.
- Modelo comunicado por Samsung: `X916`.
- Posición stock:
  `16.70,0.00,9.10,9.10,14.80,14.80,12.00,12.00,5.00`.

El sensor trabaja en modo seguro. El controlador Linux de Samsung no contiene
el algoritmo de reconocimiento ni una ruta normal para obtener imágenes: el
registro, la comparación y las plantillas se delegan en la aplicación firmada
`securefp` dentro de TrustZone.

La cadena del firmware oficial está identificada con precisión:

```text
fingerprint-service
  → libsfp_sensor
  → libsfp_teegw
  → libQSEEComAPI (objetos)
  → AppLoader compatible, UID 122
  → lookupTA("securefp")
```

`securefp` es un TA **precargado por TrustZone**, no un fichero `securefp.mbn`
que falte copiar a Ubuntu. La ruta `fpta` de Samsung admite una actualización u
override, pero está vacía en este firmware; el APEX biométrico contiene sólo su
manifiesto. El fichero `authnr.mbn` pertenece al autenticador y no es el matcher
de huellas. Esto evita dos vías falsas: buscar indefinidamente un blob
`securefp` en las particiones o intentar usar `authnr.mbn` en su lugar.

La imagen oficial contiene además el servicio biométrico de Samsung y las
bibliotecas Egis, pero dependen de Bionic, Binder, la AIDL biométrica de Android
y tokens de Gatekeeper. Por eso no son un backend intercambiable directamente
con `fprintd`.

## Arquitectura preparada

La implementación separa cuatro responsabilidades:

1. `egis_el721.c` controla únicamente el raíl de 3,3 V y la línea de
   enable/reset. Publica `/dev/esfp0` para la parte no sensible de la ABI Egis;
   no registra el sensor como un periférico SPI accesible por Linux.
2. `CONFIG_TEE=y` y `CONFIG_QCOMTEE=y` integran en el kernel el transporte de
   objetos QTEE de Qualcomm. Se espera que publique `/dev/tee0` para el futuro
   puente con la aplicación segura.
3. `panel-samsung-ana38407.c` ofrece el modo de alto brillo requerido por
   un lector óptico y el círculo de lectura. Conserva el brillo solicitado por
   GNOME, lo restaura al terminar y fuerza la limpieza después de 15 segundos.
4. El controlador Goodix puede suprimir dedos sólo dentro del rectángulo del
   sensor durante una operación biométrica. El resto de la pantalla permanece
   utilizable y al desactivar la sesión se liberan los contactos retenidos. La
   sesión también se cancela, en vez de restaurarse, al suspender el sistema.

GNOME 46 y `fprintd` no conocen por sí mismos la geometría de un UDFPS ni
controlan el HBM del panel. El backend futuro tendrá que coordinar estas cuatro
capas y mostrar el indicador en la sesión de usuario y en GDM.

## Límites de seguridad

Estos límites forman parte del diseño, no son tareas opcionales:

- Linux no debe exponer fotogramas, registros ni transacciones SPI crudas del
  EL721. Las operaciones desconocidas de `/dev/esfp0` fallan con
  `EOPNOTSUPP`.
- `/dev/esfp0` se crea con modo `0600`; sus `ioctl` requieren
  `CAP_SYS_ADMIN`. El sensor arranca apagado y se apaga al suspender, retirar el
  driver o cerrar el sistema.
- Las plantillas y la comparación deben permanecer en QTEE. El port no importa,
  exporta ni reutiliza las huellas inscritas en Android.
- No se modifica la lista de máquinas del QSEECOM heredado. La ruta elegida es
  el transporte QTEE moderno que ya existe en el kernel fijado.
- La exclusión táctil debe limitarse al rectángulo del sensor y sólo durante una
  operación activa. Tomar en exclusiva todo el dispositivo con `EVIOCGRAB`
  bloquearía la pantalla de bloqueo y no es aceptable.
- Toda salida, cancelación, error, suspensión o cierre del cliente debe ejecutar
  la secuencia inversa: quitar el círculo, salir de HBM, apagar el sensor y
  rehabilitar los toques. El watchdog del panel es una segunda protección, no
  el mecanismo normal de cierre.

## Interfaces del kernel

Las rutas contienen nombres asignados dinámicamente; hay que descubrir el
dispositivo en vez de fijar su índice.

### Sensor EL721

El nodo de carácter es fijo:

```text
/dev/esfp0
```

El dispositivo de plataforma expone estos atributos:

| Atributo | Acceso | Contenido |
|---|---|---|
| `vendor` | lectura | `EGISTEC` |
| `name` | lectura | `EL721` |
| `model` | lectura | `X916` |
| `position` | lectura | metadatos geométricos del overlay stock |
| `power` | lectura/escritura | estado y control del raíl/enable |
| `reset` | escritura | reset controlado; sólo acepta `1` |
| `reset_count` | lectura | resets ejecutados desde el arranque |

Se pueden localizar sin asumir el nombre del dispositivo:

```sh
find /sys/bus/platform/devices -type f -name vendor -exec grep -l EGISTEC {} +
```

### Panel ANA38407

Los atributos aparecen junto al backlight ANA38407:

| Atributo | Acceso | Contenido |
|---|---|---|
| `fod_ready` | lectura | `1` cuando el panel está preparado y encendido |
| `fod_mode` | lectura/escritura | HBM óptico y secuencia FlatZ |
| `fod_circle` | lectura/escritura | círculo de lectura; exige `fod_mode=1` |

El panel conserva en paralelo el brillo pedido por el escritorio. Al escribir
`fod_mode=0` restaura ese valor, y también desactiva el círculo si estuviera
activo. El watchdog devuelve ambos controles a cero tras 15 segundos.

### Táctil Goodix

El bloqueo UDFPS se configura en el dispositivo I²C Goodix mediante tres
atributos sysfs:

| Atributo | Acceso | Contenido |
|---|---|---|
| `fod_rect` | root lectura/escritura | `left top right bottom` en coordenadas crudas Goodix |
| `fod_enable` | root lectura/escritura | activa el sponge FOD y la supresión regional |
| `fod_state` | lectura, pollable | `idle|pressed|released|out|vi x y secuencia` |

El driver obtiene la dirección del sponge de la extensión SEC que publica el
firmware GT6936; no fija registros del controlador en el código. La estimación
inicial del rectángulo en coordenadas crudas verticales es
`[854,2732]–[994,2872]`; **no es aún una calibración física**. Cada slot se
clasifica al comenzar: un dedo iniciado dentro se consume hasta `UP`, mientras
uno iniciado fuera sigue funcionando aunque cruce el rectángulo.

## Secuencia prevista para una lectura

El futuro backend de `fprintd` debe tratar cada lectura como una transacción:

1. comprobar panel, QTEE y sensor;
2. transformar la geometría a la orientación actual y activar únicamente la
   exclusión Goodix de esa zona;
3. encender y, si procede, resetear el EL721;
4. activar `fod_mode` y `fod_circle` y mostrar el indicador de GNOME/GDM;
5. solicitar la captura o comparación a `securefp` mediante QTEE;
6. en un bloque de limpieza incondicional, quitar círculo y HBM, apagar el
   sensor y reactivar el tacto.

No se debe mantener el sensor, el círculo ni HBM activos entre muestras más
tiempo del solicitado por la aplicación segura.

## Validación por capas

### 1. Sondeo no destructivo

Tras arrancar el kernel nuevo:

```sh
test -c /dev/esfp0
test -c /dev/tee0
fp_vendor=$(grep -l '^EGISTEC$' /sys/bus/platform/devices/*/vendor | head -n1)
test -n "$fp_vendor"
fp_sysfs=${fp_vendor%/vendor}
for attr in vendor name model position power; do
	printf '%s: ' "$attr"
	cat "$fp_sysfs/$attr"
done
dmesg | grep -Ei 'egis|el721|qcomtee|fingerprint'
```

El resultado esperado antes de iniciar una operación es `power=0`. La mera
existencia de estos nodos sólo valida infraestructura; no demuestra que se
pueda registrar o reconocer una huella.

### 2. Alimentación y reset

La prueba se ejecuta como `root`, debe ser breve y termina apagando el sensor
incluso si una orden falla:

```sh
fp_vendor=$(grep -l '^EGISTEC$' /sys/bus/platform/devices/*/vendor | head -n1)
test -n "$fp_vendor"
fp_sysfs=${fp_vendor%/vendor}
trap 'printf 0 > "$fp_sysfs/power"' EXIT
printf 1 > "$fp_sysfs/power"
cat "$fp_sysfs/power"
printf 1 > "$fp_sysfs/reset"
cat "$fp_sysfs/reset_count"
```

Hay que verificar además que el raíl vuelve a cero tras reiniciar, apagar o
forzar la retirada del driver.

### 3. Panel óptico

Sólo se prueba como `root` y con la pantalla encendida. Debe observarse el
cambio durante unos segundos, nunca dejar HBM fijo:

```sh
bl=$(for d in /sys/class/backlight/*; do
	test -e "$d/fod_ready" && { printf '%s\n' "$d"; break; }
done)
test -n "$bl"
test "$(cat "$bl/fod_ready")" = 1
trap 'printf 0 > "$bl/fod_mode"' EXIT
printf 1 > "$bl/fod_mode"
printf 1 > "$bl/fod_circle"
sleep 2
printf 0 > "$bl/fod_mode"
```

La validación debe confirmar que vuelve el brillo anterior, que suspender o
apagar limpia el estado y que el watchdog actúa si el cliente muere.

### 4. Exclusión táctil

Con una herramienta de eventos se comprobará que, al activar una sesión FOD,
un dedo iniciado dentro del rectángulo no genera contactos, un dedo fuera sí
funciona y un contacto existente se libera correctamente. Al desactivar la
sesión toda la pantalla debe responder de inmediato. La prueba se repetirá en
las cuatro orientaciones.

### 5. QTEE y autenticación completa

Primero se hará una consulta de sólo lectura con las herramientas oficiales
`quic-teec`: `/dev/tee0` debe responder y el AppLoader compatible (UID 122) debe
aceptar `lookupTA("securefp")`. Esto comprueba que el TA precargado es visible;
no autoriza todavía a invocar operaciones biométricas ni a manipular datos de
Android.

`scripts/probe-qtee-securefp.c` implementa exactamente esa consulta. Se compila
contra `quic-teec` `736419e25a2036aac3292a10a93e394a90750ca3` y QCBOR
`4ace4620d549f22c1163c5b00d3ae0c0dae1d207`: abre UID 122, ejecuta únicamente
`lookupTA("securefp")` y libera el controlador devuelto sin obtener el objeto de
aplicación ni enviarle una operación.

Sólo cuando exista un backend seguro se instalará `fprintd` y se validarán, en
este orden:

- registro y cancelación sin dejar HBM, sensor o bloqueo táctil activos;
- varias verificaciones correctas y dedos incorrectos;
- desbloqueo de GNOME y autenticación en GDM;
- suspensión/reanudación, rotación y cambios de brillo durante una lectura;
- reinicio sin pérdida ni exposición de plantillas;
- recuperación tras caída del backend y tras agotar el watchdog.

Hasta superar toda esta matriz, el estado público permanece experimental y la
autenticación por huella se considera no disponible.

## Bloqueo actual y siguiente paso

`libfprint` no incluye soporte para el EL721 y el sensor no entrega imágenes a
Linux. El trabajo pendiente no es un decodificador SPI: es un puente mínimo que
hable con `securefp` por QTEE, mantenga las plantillas dentro del entorno seguro
y presente a `fprintd` las operaciones de registro/verificación que GNOME ya
consume. Antes de diseñar ese backend hay que confirmar en hardware, con la
consulta de sólo lectura UID 122 `lookupTA("securefp")`, que QTEE puede obtener
el objeto del TA precargado y documentar su protocolo sin escribir en las
plantillas existentes. `fprintd` no se añade ni se habilita mientras falte ese
backend: mostrar una opción de huella en GNOME sin poder completarla sería un
falso positivo de compatibilidad.
