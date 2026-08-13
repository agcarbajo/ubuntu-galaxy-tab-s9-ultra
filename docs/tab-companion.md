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
  insertar el lápiz y sólo autoriza un SPEN con los dos UUID Samsung.
- Sólo el backend accede a sysfs, evdev y `uinput`.
- El backend captura la funda conectada y retransmite sus eventos normales por
  `Tab Companion virtual keyboard`; únicamente sustituye una tecla cuando su
  asignación deja de ser «Mantener la acción predeterminada».

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

Se probó físicamente desconectar GATT mientras estaba insertado para ahorrar
batería. No es viable en este hardware: al sacarlo el lápiz no se anuncia, ni
siquiera con búsqueda activa, y BlueZ no puede recuperarlo. Por eso se mantiene
la conexión cuando está disponible. Si el lápiz entra por sí solo en reposo, la
UI indica que hay que insertarlo para que el garaje lo despierte y BlueZ vuelva
a conectarlo.

Las pulsaciones simple, doble y larga usan `BTN_STYLUS`. Los seis movimientos
de aire usan Button State del servicio FD6C y se clasifican como arriba, abajo,
izquierda, derecha, círculo horario o antihorario. El movimiento cancela la
pulsación larga para que un trazo no ejecute dos acciones.

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
Fn+F12 se muestra para completar las doce combinaciones, aunque el firmware V37
no emite ningún evento para ella.

## Selector de acciones

Cada fila tiene un único botón con icono y nombre. Abre una lista completa no
reciclada, evitando el fallo táctil de los antiguos desplegables después de
desplazarlos. «Abrir una aplicación» muestra todas las aplicaciones visibles
con icono, nombre, ID de escritorio y búsqueda. «Ejecutar un comando» abre un
campo de texto; el comando se ejecuta en la sesión de la usuaria y no debe
contener contraseñas ni secretos.

## Idiomas

La interfaz, los selectores, los estados, la lista de modelos y «Acerca de»
están disponibles en inglés, español, francés, alemán, italiano y portugués.
Se elige el idioma de la sesión y se usa inglés como respaldo.

## Validación y límites

La versión 0.7.0 se construyó con validación estricta de esquema, escritorio y
AppStream. En la tablet se comprobaron el desplazamiento del selector, la lista
de aplicaciones con iconos, el cuadro de comandos, el DX920 conectado, el nivel
100 % conservado en reposo y un arranque completo sin regresiones.

Siguen pendientes un porcentaje físico intermedio, probar EF-DX900/910/915/925
y verificar los touchpads de los modelos que los incluyen.

No se deben documentar direcciones Bluetooth, MAC, SSID ni credenciales.

## Diagnóstico rápido

```sh
systemctl --user status tab-companion-hardware.service
systemctl status tab-companion-spen-pairing.service
gdbus introspect --session \
  --dest io.github.agcarbajo.TabCompanion.Hardware \
  --object-path /io/github/agcarbajo/TabCompanion/Hardware \
  --only-properties
```

Los estados principales son `PenState`, `PenBattery`, `KeyboardPresent`,
`KeyboardModel`, `RemappingAvailable` y `GestureAvailable`.
