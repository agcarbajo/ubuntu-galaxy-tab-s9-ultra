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
  `Tab Companion virtual keyboard` (`uinput`). El backend captura el EF-DX920
  y retransmite todas las teclas normales; sólo sustituye una tecla especial
  cuando su acción elegida no es «Conservar la acción predeterminada».

## S Pen

El dibujo cambia con `PenOrientation`. En el X910 está calibrado con una medida
real: respuesta Samsung `downside` es punta hacia la derecha/USB-C. La app
distingue acoplado, cercano y no emparejado, aunque hoy sólo está medido el
primer caso.

Al insertar el lápiz, el kernel envía automáticamente la secuencia Samsung
habilitar/iniciar/mantener y consulta el cargador cada 30 segundos. El
porcentaje muestra «no expuesto» porque el protocolo del garaje sólo entrega
cargando/completo/no cargando. Cuando responde carga completa se publica 100 %;
un `-1` en `PenBattery` significa desconocido, no cero. El nivel intermedio se
intentará obtener del servicio Battery de BLE.

Las filas de pulsación simple, doble y larga ya usan `BTN_STYLUS`. Los
deslizamientos y círculos guardan su asignación, pero no se ejecutan mientras
`GestureAvailable=false`: falta caracterizar el perfil BLE de Samsung.

## Teclado funda

Cada fila tiene tres controles:

1. el botón con el nombre de la acción abre una lista estable; sustituye al
   desplegable GTK que seleccionaba la fila incorrecta después de desplazarlo;
2. el lápiz abre el destino usado por «Abrir una aplicación» o «Comando
   personalizado»;
3. el botón «Learn» inicia aprendizaje: la siguiente tecla física pulsada queda
   vinculada a esa fila. Cambia a «Cancel» y caduca a los ocho segundos para
   no capturar por accidente una tecla posterior.

Los códigos medidos en el EF-DX920 físico son Galaxy AI 760, DeX 701, Finder
710, Fn+Finder/Ajustes 709 y Fn+F1–F5 757/758/759/705/254. Fn+F6–F11 emiten
Inicio, brillo−, brillo+, silencio, volumen− y volumen+; quedan en «Conservar la
acción predeterminada». Fn+F12 aparece en la UI, pero el firmware V37 no emite
ningún evento ni incrementa el contador bruto al pulsarlo.

Para una aplicación se usa su ID de escritorio, por ejemplo
`org.gnome.Calculator.desktop`. Un comando personalizado se ejecuta con la
cuenta de la usuaria; no debe contener contraseñas ni secretos.

## Pruebas físicas pendientes

Estas pruebas necesitan a la propietaria y no están marcadas como superadas:

1. abrir la app en la sesión GNOME real y confirmar aspecto, desplazamiento y
   tamaño táctil de los controles;
2. confirmar que la carga alcanza el estado completo y que la app muestra
   100 %;
3. con la punta en hover, probar simple, doble y larga del botón con una acción
   inocua, como volumen;
4. comprobar escritura normal y el LED de Caps Lock con la retransmisión del
   teclado activa; las acciones de Galaxy AI, DeX, Finder, Ajustes y Fn+F1–F11
   ya se validaron físicamente;
5. sacar el lápiz, ponerlo en modo emparejamiento y capturar con BlueZ nombre,
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
