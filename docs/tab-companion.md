# Tab Companion

`Tab Companion` es la aplicación nativa de ajustes del S Pen y el teclado funda
EF-DX920. La instala el paquete `ubuntu-gts9u-companion`; aparece en el menú de
GNOME y no necesita ejecutarse para que el demonio aplique asignaciones.

## Arquitectura

- La ventana GTK4/libadwaita sólo usa GSettings y D-Bus.
- `tab-companion-hardware.service` corre como servicio de usuario, detecta las
  capacidades presentes y publica
  `io.github.agcarbajo.TabCompanion.Hardware`.
- `tab-companion-spen-pairing.service` corre como servicio de sistema: puede
  ordenar el reset Wacom de emparejamiento y acepta en BlueZ únicamente un
  dispositivo SPEN con UUID Samsung mientras `pen_docked=1`.
- Sólo el backend lee sysfs y los dispositivos de entrada.
- Las acciones de teclado y botón del lápiz salen por
  `Tab Companion virtual keyboard` (`uinput`). El backend captura el EF-DX920
  y retransmite todas las teclas normales; sólo sustituye una tecla especial
  cuando su acción elegida no es «Conservar la acción predeterminada».

## S Pen

El dibujo cambia con `PenOrientation`. En el X910 está calibrado con una medida
real: respuesta Samsung `downside` es punta hacia la derecha/USB-C. La app
distingue acoplado, cercano, emparejado en reposo y no emparejado.

Al insertar el lápiz, el kernel envía automáticamente la secuencia Samsung
habilitar/iniciar/mantener y consulta el cargador cada 30 segundos. El
porcentaje muestra «no expuesto» porque el protocolo del garaje sólo entrega
cargando/completo/no cargando. Cuando responde carga completa se publica 100 %;
un `-1` en `PenBattery` significa desconocido, no cero. Una vez enlazado, el
backend lee el porcentaje real de la característica Samsung Battery Level; la
primera lectura física devolvió 100 %.

El emparejamiento no usa el diálogo Bluetooth clásico. Con el lápiz insertado,
el comando Wacom `0xea` abre el anuncio y el propio S Pen inicia una solicitud
de autorización. El servicio la acepta sólo si coinciden simultáneamente el
acoplamiento físico, el nombre SPEN y ambos UUID FD6C/FEF5. El vínculo se
guarda como `Paired`, `Bonded` y `Trusted`, igual que el flujo transparente de
One UI desde el punto de vista de la usuaria. El agente sólo se registra como
predeterminado durante esa ventana, que se cierra a los 65 segundos o en cuanto
termina el enlace, para no interferir con otros emparejamientos Bluetooth.

Las filas de pulsación simple, doble y larga usan `BTN_STYLUS`. El transporte
de aire es el servicio FD6C, Mode `0x10` y Button State con muestras
incrementales `dx`/`dy`. El clasificador acumula la trayectoria: separa primero
los círculos por energía en ambos ejes y área firmada, y después los
deslizamientos por eje dominante y signo. Arriba, abajo, izquierda, derecha,
horario y antihorario quedaron validados con el lápiz físico y ejecutan la
asignación guardada. Al comenzar movimiento se cancela la pulsación larga para
que un gesto no dispare dos acciones.

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
2. dejar que la batería baje de 100 % y confirmar un porcentaje BLE intermedio;
3. con la punta en hover, probar simple, doble y larga del botón con una acción
   inocua, como volumen;
4. comprobar escritura normal y el LED de Caps Lock con la retransmisión del
   teclado activa; las acciones de Galaxy AI, DeX, Finder, Ajustes y Fn+F1–F11
   ya se validaron físicamente;
5. confirmar reconexión automática al sacar/reinsertar y tras un arranque limpio;
6. asignar una acción visible distinta a cada uno de los seis gestos y confirmar
   desde la interfaz que cada fila ejecuta su destino.

No se deben documentar direcciones Bluetooth, MAC, SSID ni credenciales. La
fase BLE sólo puede cerrarse tras la prueba visual de las acciones y la
reconexión desde un arranque limpio.

## Diagnóstico rápido

```sh
systemctl --user status tab-companion-hardware.service
systemctl status tab-companion-spen-pairing.service
gdbus introspect --session \
  --dest io.github.agcarbajo.TabCompanion.Hardware \
  --object-path /io/github/agcarbajo/TabCompanion/Hardware \
  --only-properties
```

Los estados importantes son `PenState`, `PenOrientation`,
`ButtonActionsAvailable`, `KeyboardPresent`, `RemappingAvailable` y
`GestureAvailable`.
