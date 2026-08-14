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
- Alimentación de 3,3 V: TLMM GPIO91 (`etspi-ldoPin`).
- Enable/reset: TLMM GPIO155 (`etspi-sleepPin`).
- Modelo comunicado por Samsung: `X916`.
- Posición stock:
  `16.70,0.00,9.10,9.10,14.80,14.80,12.00,12.00,5.00`.

El sensor trabaja en modo seguro. El controlador Linux de Samsung no contiene
el algoritmo de reconocimiento ni una ruta normal para obtener imágenes: el
registro, la comparación y las plantillas se delegan en aplicaciones firmadas
dentro de TrustZone.

La cadena del firmware oficial está identificada con precisión:

```text
fingerprint-service
  → libsfp_sensor
  → libsfp_teegw
  → libQSEEComAPI (objetos)
  → AppLoader compatible, UID 122
  → nombre lógico "securefp"
  → TA firmada dualfp
```

El servicio Samsung solicita el nombre lógico `securefp`, pero no existe un
fichero `securefp.mbn` en `system`, `vendor`, `odm` ni en el APEX biométrico. La
ruta `fpta` admite una actualización u override, pero está vacía en este
firmware. El análisis completo de `NON-HLOS.bin` resolvió la ambigüedad:
`fingerpr.b00`–`b08` contiene el motor QFP genérico, mientras
`dualfp.b00`–`b08` contiene la implementación Samsung/Egis del EL721, BAUTH,
matching y plantillas. `authnr.mbn` es otro autenticador que referencia tanto
`securefp` como `dualfp`, no el matcher principal.

La imagen ensamblada `dualfp` mide 19.927.128 bytes. El AppLoader compatible
UID 122 la acepta con `loadFromRegion` y devuelve un controlador QSEEComCompat
válido; la descarga posterior también termina correctamente. Esto demuestra
que la TA segura necesaria está presente y es ejecutable desde Ubuntu, aunque
`lookupTA("securefp")` no publique un alias ni antes ni después de la carga.

La imagen oficial contiene además el servicio biométrico de Samsung y las
bibliotecas Egis, pero dependen de Bionic, Binder, la AIDL biométrica de Android
y tokens de Gatekeeper. Por eso no son un backend intercambiable directamente
con `fprintd`.

## Arquitectura preparada

La infraestructura es deliberadamente **opt-in**. Una compilación normal usa
exactamente el DT y el controlador de panel del último commit validado, no
aplica la extensión FOD de Goodix y no compila el EL721. QCOMTEE conserva la
configuración modular de la base pero queda en la blacklist. Para una prueba
controlada puede usarse el selector conjunto
`ENABLE_FINGERPRINT_EXPERIMENTAL=1` o activar por separado
`FINGERPRINT_PANEL_FOD`, `FINGERPRINT_TOUCH_FOD` y `FINGERPRINT_EL721`. El
módulo QCOMTEE firmado
sólo se carga con `modprobe qcomtee`, después de arrancar y habilitar el
registro. Esta separación se introdujo tras observar un reinicio anterior al
montaje del rootfs y evita convertir otro fallo en un bootloop.

La implementación separa cuatro responsabilidades:

1. `egis_el721.c` controla únicamente el raíl de 3,3 V y la línea de
   enable/reset. Publica `/dev/esfp0` para la parte no sensible de la ABI Egis;
   no registra el sensor como un periférico SPI accesible por Linux.
2. `CONFIG_TEE=y` mantiene la infraestructura común. En builds experimentales,
   `CONFIG_QCOMTEE=m` empaqueta el transporte de objetos QTEE de Qualcomm; al
   cargarlo manualmente publica `/dev/tee0`. El transporte Qualcomm Diagnostics
   y el AppLoader UID 122 están validados físicamente. Los mensajes conservan
   el límite upstream de 4 MiB; las TA mayores se entregan con un objeto de memoria TEE
   mediante `loadFromRegion`, sin inflar el mensaje ni duplicar 20 MiB en CMA.
3. `panel-samsung-ana38407.c` ofrece el modo de alto brillo requerido por
   un lector óptico. Conserva el brillo solicitado por GNOME, lo restaura al
   terminar y fuerza la limpieza después de 15 segundos. Una extensión de
   GNOME dibuja el objetivo y compensa el HBM global fuera de esa región.
4. El controlador Goodix suprime dedos sólo dentro del rectángulo del sensor
   durante una operación biométrica. El firmware ya entrega `press/release`
   FOD reales y no reenvía ese contacto como toque normal. El resto de la
   pantalla permanece utilizable y al desactivar la sesión se liberan los
   contactos retenidos. La sesión también se cancela, en vez de restaurarse,
   al suspender el sistema.

GNOME 46 y `fprintd` no conocen por sí mismos la geometría de un UDFPS ni
controlan el HBM del panel. La extensión de sistema
`gts9u-fingerprint-overlay@agcarbajo` cubre esa carencia en la sesión y el
desbloqueo; aún hay que conectarla al backend y cargarla también en GDM.

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
| `sensor_power` | lectura/escritura | estado y control de GPIO91/GPIO155 |
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
| `fod_circle` | lectura/escritura | comando DDIC diagnóstico; exige `fod_mode=1`, pero no dibuja sin Self Display |

El panel conserva en paralelo el brillo pedido por el escritorio. Al escribir
`fod_mode=0` restaura ese valor, y también desactiva el círculo si estuviera
activo. El watchdog devuelve ambos controles a cero tras 15 segundos.

Esta capa ya arrancó de forma aislada en hardware. Se validaron HBM, el
watchdog y la restauración exacta del brillo. `fod_circle=1` llega al DDIC sin
error, pero no produce una imagen visible: el kernel Samsung carga primero una
imagen Self Display y comprueba su checksum. Portar ese subsistema sólo para el
indicador no aporta captura; se usa el objetivo de GNOME. El panel por sí solo
queda descartado como causa del bootloop inicial.

El ANA38407 no ofrece HBM local. Al leer una huella entra en FlatZ/HBM global y
GNOME oscurece los píxeles externos al objetivo. Al ser OLED, esos píxeles
emiten físicamente menos luz aunque la selección de la región se haga en el
compositor. La opacidad se calcula desde el brillo actual con la tabla oficial:
el modo normal alcanza 420 cd/m² en `WRDISBV=2047` y FlatZ de huella, 650 cd/m².
El objetivo queda fuera de la compensación y recibe el máximo óptico; el resto
conserva aproximadamente la luminancia anterior. La extensión recalcula cada
100 ms si una tecla cambia el brillo durante la lectura.

### Táctil Goodix

El bloqueo UDFPS se configura en el dispositivo I²C Goodix mediante cuatro
atributos sysfs:

| Atributo | Acceso | Contenido |
|---|---|---|
| `fod_rect` | root lectura/escritura | `left top right bottom` en coordenadas crudas Goodix |
| `fod_enable` | root lectura/escritura | activa el sponge FOD y la supresión regional |
| `fod_property` | root lectura/escritura | política Samsung `fast/strict`, valores `0`–`3`; por defecto `3` |
| `fod_state` | lectura, pollable | `idle|pressed|released|out|vi x y secuencia` |

El driver obtiene la dirección del sponge de la extensión SEC que publica el
firmware GT6936; no fija registros del controlador en el código. En la unidad
física anuncia `0x29800`, longitud 1024. La estructura SEC empieza después de
los 10 bytes reservados finales de `IC_INFO`; omitirlos produce una dirección
falsa. Igual que el driver Samsung, cada acceso despierta primero el firmware
al modo normal con el comando `0x9f` y después confirma el sponge con `0xf2`.

El rectángulo crudo `[854,2732]–[994,2872]` quedó validado físicamente: un dedo
en el centro visual produjo `released 911 2808` y `released 945 2809`. Durante
la misma prueba no apareció ningún `BTN_TOUCH`, tracking ID ni coordenada
normal. Cada slot se clasifica al comenzar: un dedo iniciado dentro se consume
hasta `UP`, mientras uno iniciado fuera sigue funcionando aunque cruce el
rectángulo.

## Secuencia prevista para una lectura

El futuro backend de `fprintd` debe tratar cada lectura como una transacción:

1. comprobar panel, QTEE y sensor;
2. transformar la geometría a la orientación actual y activar únicamente la
   exclusión Goodix de esa zona;
3. encender y, si procede, resetear el EL721;
4. mostrar la máscara/objetivo de GNOME y activar `fod_mode`;
5. solicitar la captura o comparación a `dualfp` mediante QTEE;
6. en un bloque de limpieza incondicional, quitar círculo y HBM, apagar el
   sensor y reactivar el tacto.

No se debe mantener el sensor, el círculo ni HBM activos entre muestras más
tiempo del solicitado por la aplicación segura.

## Validación por capas

### 1. Sondeo no destructivo

Tras arrancar un build experimental, confirmar primero que QTEE sigue
descargado y cargarlo sólo con un canal de recuperación disponible:

```sh
test ! -e /dev/tee0
lsmod | grep -q '^qcomtee ' && exit 1
sudo modprobe qcomtee
```

Después:

```sh
test -c /dev/esfp0
test -c /dev/tee0
fp_vendor=$(grep -l '^EGISTEC$' /sys/bus/platform/devices/*/vendor | head -n1)
test -n "$fp_vendor"
fp_sysfs=${fp_vendor%/vendor}
for attr in vendor name model position sensor_power; do
	printf '%s: ' "$attr"
	cat "$fp_sysfs/$attr"
done
dmesg | grep -Ei 'egis|el721|qcomtee|fingerprint'
```

El resultado esperado antes de iniciar una operación es `sensor_power=0`. La mera
existencia de estos nodos sólo valida infraestructura; no demuestra que se
pueda registrar o reconocer una huella.

### 2. Alimentación y reset

La prueba se ejecuta como `root`, debe ser breve y termina apagando el sensor
incluso si una orden falla:

```sh
fp_vendor=$(grep -l '^EGISTEC$' /sys/bus/platform/devices/*/vendor | head -n1)
test -n "$fp_vendor"
fp_sysfs=${fp_vendor%/vendor}
trap 'printf 0 > "$fp_sysfs/sensor_power"' EXIT
printf 1 > "$fp_sysfs/sensor_power"
cat "$fp_sysfs/sensor_power"
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
sleep 2
printf 0 > "$bl/fod_mode"
```

La validación debe confirmar que vuelve el brillo anterior, que suspender o
apagar limpia el estado y que el watchdog actúa si el cliente muere.

### 4. Exclusión táctil

Validado el 14 de agosto de 2026 en la tablet física. Con `fod_property=3`, el
GT6936 entregó `released` dentro del rectángulo y la escucha simultánea de
`/dev/input/event5` no recibió ningún contacto normal. Al desactivar la sesión,
la pantalla respondió de inmediato. Queda repetir la experiencia completa de
autenticación en GDM y en las cuatro orientaciones cuando exista el backend.

### 5. QTEE y autenticación completa

La consulta de sólo lectura con las herramientas oficiales `quic-teec` ya
confirma QTEE 5.2.0, Qualcomm Diagnostics y el AppLoader compatible UID 122.
`lookupTA("securefp")` devuelve `2` tanto desde clientes de usuario como desde
el entorno privilegiado interno del driver: el alias no está publicado en
este estado de TrustZone. Esto ya no bloquea la carga porque UID 122 acepta la
imagen firmada `dualfp` y devuelve directamente su controlador compatible.

`scripts/probe-qtee-securefp.c` implementa exactamente esa consulta. Se compila
contra `quic-teec` `736419e25a2036aac3292a10a93e394a90750ca3` y QCBOR
`4ace4620d549f22c1163c5b00d3ae0c0dae1d207`: abre UID 122, ejecuta únicamente
`lookupTA("securefp")` y libera el controlador devuelto sin obtener el objeto de
aplicación ni enviarle una operación.

`scripts/probe-qtee-load-securefp.c` reconstruye una imagen dividida stock con
los offsets ELF que utiliza Qualcomm. Recibe por separado el nombre base de los
segmentos y el nombre de carga. Para `dualfp` reserva un objeto de memoria
TEE y usa `loadFromRegion`; QTEE aceptó los 19.927.128 bytes como `dualfp` y los
descargó limpiamente. El probe ofrece además `--type-check`: la petición llega
a la TA (`invoke result 0`), pero con el sensor aún sin alimentación física la
TA devuelve `29`. No se inicia captura, registro ni comparación.

Se verificó que las particiones activas de la tablet coinciden byte a byte con
el firmware analizado: `apnhlos` coincide con `NON-HLOS.bin` (SHA-256
`1aa9de73…`) y `tz` con `tz.mbn` (`865b32e1…`). El resultado no se debe a una
mezcla de versiones o a antirollback.

Las herramientas auxiliares se mantienen en `scripts/` y no se instalan en la
imagen final: `probe-el721-abi.c` comprueba que la ABI restringida sólo expone
el modelo, `probe-qtee-securefp.c` consulta un nombre lógico, y
`probe-qtee-load-ta.c` permite cargar y descargar una TA pequeña ya ensamblada.
`probe-stock-qseecom.c` conserva el experimento equivalente para enlazar contra
la biblioteca Bionic stock. Ninguna registra plantillas ni se usa como backend
de autenticación.

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
Linux. Transporte QTEE, AppLoader, carga de `dualfp`, iluminación óptica y
señal/supresión FOD de Goodix están comprobados. El bloqueo actual se ha
reducido a encender de forma segura el EL721 después del arranque y completar
el protocolo BAUTH sobre el controlador ya obtenido. El driver prepara un
dispositivo de plataforma tardío y mapea GPIO91/GPIO155 sin modificar el DTB;
esta nueva alimentación diferida debe validarse físicamente antes de enviar
comandos de captura.

Después se implementará el puente mínimo hacia `libfprint`/`fprintd`. Las
plantillas y la comparación permanecerán en TrustZone. `fprintd` no se añade ni
se habilita mientras falte ese backend: mostrar una opción de huella en GNOME
sin poder completarla sería un falso positivo de compatibilidad.
