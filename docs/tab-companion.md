# Tab Companion

`Tab Companion` es la aplicación nativa de ajustes del S Pen y las fundas con
teclado Samsung compatibles. La instala `ubuntu-gts9u-companion`; aparece en el
menú de GNOME y el servicio de usuario aplica las asignaciones aunque la ventana
esté cerrada.

## Arquitectura

- La ventana GTK4/libadwaita sólo usa GSettings y D-Bus.
- `tab-companion-hardware.service` detecta las capacidades presentes y publica
  `io.github.agcarbajo.TabCompanion.Hardware`.
- `tab-companion-spen-pairing.service` reproduce el emparejamiento iniciado al
  insertar el lápiz, sólo autoriza un SPEN con los dos UUID Samsung y expone
  el control privilegiado que conecta o desconecta sus funciones remotas.
- Sólo el backend accede a sysfs, evdev y `uinput`.
- El backend captura la funda conectada y retransmite sus eventos por
  `Tab Companion virtual keyboard`. En «Mantener la acción predeterminada»,
  deja pasar las teclas que ya entrega correctamente el firmware y aplica la
  utilidad base del port a las teclas especiales sin función nativa en GNOME.

## S Pen

La página muestra gráficamente la orientación, el estado y una barra con el
último porcentaje real conocido. El garaje sólo entrega estados discretos de
carga; el porcentaje procede de la característica Battery Level del perfil BLE
Samsung y se conserva mientras el lápiz duerme. No se estima ningún valor.

El emparejamiento no usa el diálogo Bluetooth clásico. Al insertar el lápiz,
el comando Wacom `0xea` abre el anuncio y el propio S Pen inicia la solicitud.
El servicio sólo la acepta cuando coinciden el acoplamiento físico, el nombre
SPEN y los UUID FD6C/FEF5. El resultado se guarda como enlazado y confiable sin
PIN ni interacción, como en One UI.

Si BlueZ conserva un enlace que el lápiz ya no reconoce, cuatro intentos de
conexión fallidos con el S Pen físicamente insertado activan una recuperación
limitada a ese dispositivo: se descarta el enlace obsoleto y se repite el flujo
del garaje. El servicio también espera al adaptador durante el arranque.

«Activar funciones remotas» separa por completo BLE de la escritura EMR. Al
desactivarlo, el servicio raíz cancela emparejamientos en curso, desconecta el
S Pen sin borrar su vínculo y deja de intentar conectar o emparejar. La app sólo
muestra si está insertado; la escritura y las dos opciones de comportamiento
siguen funcionando. La preferencia se guarda también bajo `/var/lib` para que
se respete antes de iniciar sesión. Al reactivarla puede ser necesario insertar
el lápiz: el garaje es el único mecanismo fiable para despertarlo y hacer que
vuelva a anunciarse.

«Ignorar los toques con el dedo durante el hover» comparte la proximidad Wacom
con el controlador Goodix. En cuanto entra `BTN_TOOL_PEN`, el touchscreen
libera sus contactos activos y no publica dedos hasta que el lápiz sale de
rango. «Deshabilitar el digitalizador mientras está insertado» mantiene vivos
garaje, carga y BLE, pero descarta los paquetes de coordenadas EMR. La IRQ
física no se desactiva porque también transporta las respuestas de orientación
y carga; esta separación corrige la orientación obsoleta al reinsertar el S Pen
al revés. La alimentación AVDD se comparte con el panel, por lo que no supone
un apagado eléctrico total.

Las pulsaciones simple, doble y larga usan `BTN_STYLUS`. Los seis movimientos
de aire usan Button State del servicio FD6C y se clasifican como arriba, abajo,
izquierda, derecha, círculo horario o antihorario. El movimiento cancela la
pulsación larga para que un trazo no ejecute dos acciones.

Gestos y puntero son modos alternativos. El segundo sigue el concepto de
[PenMouseS](https://github.com/jojczak/PenMouseS): integra los incrementos del
giroscopio BLE y los convierte en un
ratón relativo nativo mediante `uinput`, sin overlay ni servicio de
accesibilidad. El botón es el clic principal y permite arrastrar. La app expone
sensibilidad, suavizado y aceleración; el eje vertical se invierte para que el
movimiento físico coincida con el cursor.

## Vibración y teclado en pantalla

El firmware stock describe un motor COINDC habilitado por TLMM GPIO18. El DTS
mainline lo registra con `gpio-vibrator`, que publica un dispositivo evdev
`FF_RUMBLE`. El servicio de hardware es el único que abre ese nodo y ofrece el
método D-Bus `Vibrate`.

GNOME Shell 46 no ofrece una preferencia genérica de hápticos para su teclado en
pantalla. La extensión incluida observa únicamente pulsaciones táctiles sobre
actores `keyboard-key` y solicita un pulso al backend. Como el GPIO sólo permite
encendido/apagado, Suave/Media/Fuerte ajustan la duración (8/14/22 ms), no la
amplitud eléctrica. La nueva página Hápticos permite apagarlo y contiene un
botón temporal de prueba.

## Fundas con teclado

Sin una funda conocida, la sección sólo muestra una bienvenida y el botón
«Teclados compatibles». Al conectar una por primera vez se guardan su modelo y
nombre comercial. Si luego se desconecta, sus asignaciones continúan editables
y una X permite olvidarla y volver al estado inicial.

La tabla oficial del X910 y las páginas de producto de Samsung identifican
estos cinco modelos:

| Modelo | Nombre comercial |
|---|---|
| EF-DX900 | Galaxy Tab S8 Ultra Book Cover Keyboard |
| EF-DX910 | Galaxy Tab S9 Ultra Book Cover Keyboard Slim |
| EF-DX915 | Galaxy Tab S9 Ultra Book Cover Keyboard |
| EF-DX920 | Galaxy Tab S10 Ultra / S9 Ultra Book Cover Keyboard Slim (AI Key) |
| EF-DX925 | Galaxy Tab S10 Ultra / S9 Ultra Book Cover Keyboard (AI Key) |

El kernel distingue las revisiones por el identificador de protocolo y la
respuesta VERSION. El EF-DX920 es el único disponible y validado físicamente;
la enumeración y las teclas especiales de los otros cuatro modelos están
preparadas, pero sus teclados y touchpads todavía requieren prueba real.

No hay modo «Learn»: los códigos medidos forman parte de los valores de fábrica.
«Restablecer valores» restaura de una vez acciones, destinos y códigos físicos.
En el EF-DX920 son Galaxy AI 760, DeX 701, Finder 710,
Fn+Finder/Ajustes 709 y Fn+F1–F11 757/758/759/705/254/172/224/225/113/114/115.
Fn+F12 no se muestra: el firmware V37 no emite ningún evento y no hay nada
fiable que remapear.

«Mantener la acción predeterminada» no es una asignación guardada. Para las
teclas sin función nativa, el backend aplica la utilidad base del port: Galaxy
AI abre Tab Companion; Finder abre la búsqueda; Ajustes abre Configuración;
Fn+F1/F2/F3 abren Archivos, navegador y terminal; Fn+F4 abre aplicaciones;
Fn+F5 abre la vista general; y DeX maximiza o restaura la ventana actual.
Fn+F6–F11 se retransmiten sin sustituir y conservan sus eventos nativos.

Elegir otra acción sólo reemplaza ese comportamiento mientras la asignación
esté guardada. Volver a «Mantener la acción predeterminada», o usar
«Restablecer valores», elimina la personalización y recupera la utilidad base.

## Selector de acciones

Cada fila tiene un único botón con icono y nombre. Abre una lista completa no
reciclada, evitando el fallo táctil de los antiguos desplegables después de
desplazarlos. «Abrir una aplicación» muestra todas las aplicaciones visibles
con icono, nombre, ID de escritorio y búsqueda. «Ejecutar un comando» abre un
campo de texto; el comando se ejecuta en la sesión de la usuaria y no debe
contener contraseñas ni secretos.

«Simular una tecla» abre un teclado gráfico con alfanuméricas, F1–F12,
navegación y modificadores. Se puede tocar una tecla o pulsarla en cualquier
teclado físico; Ctrl, Mayús, Alt, AltGr y Super permiten crear combinaciones.
«Activar/desactivar la linterna» usa `gts9u-flashlight toggle` y está disponible
para cualquier tecla o gesto.

## Idiomas

La interfaz, los selectores, los estados, la lista de modelos y «Acerca de»
están disponibles en inglés, español, francés, alemán, italiano y portugués.
Se elige el idioma de la sesión y se usa inglés como respaldo.

## Validación y límites

La versión 0.9.0 se construyó con validación estricta de esquema, escritorio y
AppStream. En la tablet se comprobaron el backend, los dispositivos `uinput`,
la API D-Bus, el teclado gráfico, una combinación
`Ctrl+Alt+T`, la linterna, el DX920, BLE al 100 %, permisos sysfs y transiciones
de IRQ. La propietaria validó físicamente el rechazo del dedo durante hover y
la desactivación/reactivación del digitalizador al insertar y extraer el S Pen.

Un reinicio de validación quedó detenido antes de iniciar Tab Companion, en el
ciclo `pm_test=platform` que el port usa para recuperar el panel tras un arranque
frío. El siguiente arranque completó el ciclo y todas las comprobaciones. Si la
tablet vuelve a quedar congelada durante el arranque, este recuperador del panel
es la primera ruta de diagnóstico; no se observó relación con las políticas
Wacom/Goodix.

Siguen pendientes sentir físicamente el motor, calibrar el puntero con uso real,
validar el ciclo desactivar/reactivar BLE, obtener un porcentaje de batería
intermedio, probar EF-DX900/910/915/925 y verificar sus touchpads.

No se deben documentar direcciones Bluetooth, MAC, SSID ni credenciales.

## Diagnóstico rápido

```sh
systemctl --user status tab-companion-hardware.service
systemctl status tab-companion-spen-pairing.service
gnome-extensions info tab-companion-haptics@agcarbajo
gdbus introspect --session \
  --dest io.github.agcarbajo.TabCompanion.Hardware \
  --object-path /io/github/agcarbajo/TabCompanion/Hardware \
  --only-properties
```

Los estados principales son `PenState`, `PenBattery`, `KeyboardPresent`,
`KeyboardModel`, `RemappingAvailable`, `GestureAvailable` y `HapticsAvailable`.
