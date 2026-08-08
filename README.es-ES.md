

# LOOI-Robot

Este repositorio contiene mis experimentos con el robot LOOI. Consideré que la aplicación original era demasiado primitiva, así que decidí hacer ingeniería inversa del protocolo Bluetooth LE para controlar la base del robot directamente con Python.

Basándome en registros de un analizador de paquetes, mapeé con éxito los comandos de movimiento, los informes de estado y la secuencia de inicialización específica requerida para mantener el robot activo.

Características:

✅ Control completo de movimiento: Adelante/Atrás/Giro (Modo Drift) con soporte para velocidad variable.

✅ Control de la cabeza: Ajuste del ángulo de la cabeza.

✅ Conexión estable: Se implementó el "doble handshake" específico y el latido de sondeo de batería necesario para evitar que el robot se desconecte.

✅ Soporte para macOS: Incluye correcciones para problemas de descubrimiento de servicios de bleak en macOS.

Objetivo: Esto es una Prueba de Concepto. El objetivo es permitir que la comunidad desarrolle aplicaciones mejores y más avanzadas para LOOI que la aplicación original por defecto.

🛠️ Detalles técnicos (El protocolo)
Si quieres crear tu propia aplicación, aquí está lo que encontré durante el proceso de ingeniería inversa:

1. UUIDs clave
Movimiento (Escritura): 0000fed0-0000-1000-8000-00805f9b34fb

Cabeza (Escritura): 0000fed1-0000-1000-8000-00805f9b34fb

Handshake/Configuración (Escritura): 0000feda-0000-1000-8000-00805f9b34fb

Batería/Estado (Lectura): 0000fed8-0000-1000-8000-00805f9b34fb

Sensores (Notificación): 0000fed5-0000-1000-8000-00805f9b34fb

2. Secuencia de inicialización (Crítica)
El robot tiene un temporizador de vigilancia (watchdog timer) agresivo. Para mantenerlo activo, debes seguir esta secuencia exactamente:

Conectar vía BLE.

Handshake 1: Escribir 0x01 en FEDA.

Suscribirse: Habilitar notificaciones en FED5 (Sensores) y FED9 (Telemetría).

Handshake 2: Escribir 0x03 en FEDA. Sin esto, el robot acepta comandos pero se desconecta después de unos segundos.

3. Protocolo de movimiento (FED0)
La carga útil consta de 2 bytes: [Velocidad, Giro]. Los valores son Signed Int8 (-127 a +127).

0x7F (127) = Máxima velocidad adelante / Giro máximo a la izquierda.

0x81 (-127) = Máxima velocidad atrás / Giro máximo a la derecha.

Latido de mantenimiento (Heartbeat): Debes enviar un paquete de movimiento (incluso 00 00) cada ~30 ms, de lo contrario los motores se desactivan.

4. Mantenimiento de conexión (Keep-Alive / Batería)
La aplicación oficial lee la Característica de Batería (FED8) aproximadamente cada 4-5 segundos. Si esta solicitud de lectura no se realiza durante demasiado tiempo, el robot podría asumir que la aplicación se ha cerrado inesperadamente y desconectarse.

💻 Requisitos
Python 3.10+

Biblioteca bleak

Bash

pip install bleak
🎮 Uso
Ejecuta el script para controlar el robot con tu teclado:

Bash

python looi_drift_fix.py
W / S: Adelante / Atrás (Velocidad máxima)

A / D: Izquierda / Derecha (Combinable con W/S para hacer drift)

I / K: Cabeza arriba / Abajo

Q: Salir

Descargo de responsabilidad: Este es un proyecto no oficial. Úsalo bajo tu propio riesgo. No tengo afiliación con los fabricantes del robot LOOI.
