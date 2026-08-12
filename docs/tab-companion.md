# Tab Companion

`Tab Companion` es la aplicación nativa de ajustes del S Pen y el teclado funda
EF-DX920. La instala el paquete `ubuntu-gts9u-companion`; aparece en el menú de
GNOME y no necesita ejecutarse para que el demonio aplique asignaciones.

## Arquitectura

- La ventana GTK4/libadwaita sólo usa GSettings y D-Bus.
- `tab-companion-hardware.service` corre como servicio de usuario, detecta las
  capacidades presentes y publica
  `io.github.agcarbajo.TabCompanion.Hardware`.
- Sólo el backend lee sysfs y los dispositivos de entrada.
- Las acciones de teclado y botón del lápiz salen por
  `Tab Companion virtual keyboard` (`uinput`). El teclado físico no se captura
  en exclusiva: la escritura normal sigue llegando a GNOME.

## S Pen

El dibujo cambia con `PenOrientation`. En el X910 está calibrado con una medida
real: respuesta Samsung `downside` es punta hacia la derecha/USB-C. La app
distingue acoplado, cercano y no emparejado, aunque hoy sólo está medido el
primer caso.

El porcentaje muestra «no expuesto» porque el protocolo no lo entrega. Sí se
lee el estado discreto cargar/completo/no cargar. Un `-1` en la propiedad D-Bus
`PenBattery` significa desconocido, no cero.

Las filas de pulsación simple, doble y larga ya usan `BTN_STYLUS`. Los
deslizamientos y círculos guardan su asignación, pero no se ejecutan mientras
`GestureAvailable=false`: falta caracterizar el perfil BLE de Samsung.

## Teclado funda

Cada fila tiene tres controles:

1. el desplegable elige la acción;
2. el lápiz abre el destino usado por «Abrir una aplicación» o «Comando
   personalizado»;
3. el punto inicia aprendizaje: la siguiente tecla física pulsada queda
   vinculada a esa fila.

Galaxy AI, DeX y Search ya parten de los códigos del fuente Samsung. `Fn+F1` a
`Fn+F5` se dejan sin código hasta aprenderlos en el EF-DX920 real.

Para una aplicación se usa su ID de escritorio, por ejemplo
`org.gnome.Calculator.desktop`. Un comando personalizado se ejecuta con la
cuenta de la usuaria; no debe contener contraseñas ni secretos.

## Pruebas físicas pendientes

Estas pruebas necesitan a la propietaria y no están marcadas como superadas:

1. abrir la app en la sesión GNOME real y confirmar aspecto, desplazamiento y
   tamaño táctil de los controles;
2. retirar el S Pen: comprobar que pasa a desacoplado y que
   `SW_PEN_INSERTED` baja; reinsertarlo y comprobar el flanco contrario;
3. colocar el lápiz con punta izquierda si el imán lo admite y verificar que el
   dibujo se invierte;
4. con la punta en hover, probar simple, doble y larga del botón con una acción
   inocua, como volumen;
5. pulsar Galaxy AI, DeX, Search/Settings y aprender `Fn+F1`–`Fn+F5`, anotando
   los códigos que muestra `LastSpecialKey`;
6. sacar el lápiz, ponerlo en modo emparejamiento y capturar con BlueZ nombre,
   UUIDs, características y notificaciones; después producir una muestra de
   cada deslizamiento y círculo.

No se deben documentar direcciones Bluetooth, MAC, SSID ni credenciales. La
fase BLE sólo puede cerrarse cuando las notificaciones distingan los siete
movimientos de forma repetible.

## Diagnóstico rápido

```sh
systemctl --user status tab-companion-hardware.service
gdbus introspect --session \
  --dest io.github.agcarbajo.TabCompanion.Hardware \
  --object-path /io/github/agcarbajo/TabCompanion/Hardware \
  --only-properties
```

Los estados importantes son `PenState`, `PenOrientation`,
`ButtonActionsAvailable`, `KeyboardPresent`, `RemappingAvailable` y
`GestureAvailable`.
