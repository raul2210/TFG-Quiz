# DronQuiz

Sistema interactivo de juego basado en dron, desarrollado como Trabajo de Fin de Grado dentro del ecosistema **DEE (Drone Engineering Ecosystem)** de la EETAC. Combina control de vuelo autónomo, visión artificial, reconocimiento de voz y comunicación en tiempo real para convertir a un dron en el maestro de ceremonias de una partida en la que los jugadores participan desde su propio móvil.

## Descripción general

El dron localiza y sobrevuela a los jugadores, les hace preguntas por voz y evalúa sus respuestas, mientras una estación de tierra en el suelo supervisa todo el proceso y una aplicación web permite a cada jugador participar desde su teléfono sin necesidad de instalar nada.

El sistema incluye dos modos de juego:

- **Random**: modo de validación técnica. El dron selecciona a un jugador al azar, se desplaza hasta su posición, se recoloca frente a él mediante detección visual y le toma una fotografía.
- **Quiz**: añade a lo anterior un sistema de preguntas de cultura general por voz, temporizador de respuesta y puntuación por jugador, con partidas de rondas configurables.

## Arquitectura

El sistema se compone de tres piezas que se comunican entre sí mediante MQTT:

```
┌──────────────────────┐       MQTT (HiveMQ)      ┌──────────────────────┐
│  Estación de Tierra  │ ◄──────────────────────► │   Aplicación Web     │
│  (Python / Tkinter)  │                          │  (HTML / JavaScript) │
└──────────┬───────────┘                          └──────────────────────┘
           │ Radio de telemetría / TCP (simulación)
           ▼
      ┌─────────┐
      │  Dron    │
      └─────────┘
```

- **Estación de tierra**: aplicación de escritorio en Python que controla el dron, gestiona la cámara con detección de personas (YOLOv5), coordina la partida y expone un panel de control gráfico.
- **Aplicación web**: página HTML/JavaScript de una sola vista, pensada para el navegador del móvil del jugador, que gestiona la interacción, el audio (síntesis y reconocimiento de voz) y la geolocalización.
- **Bróker MQTT**: intermediario de mensajes entre la estación de tierra y todos los dispositivos móviles conectados.
- **Servidor web**: sirve la aplicación web y gestiona la señalización WebRTC para el modo Visitante (streaming de vídeo en directo desde la cámara del dron).

## Estructura del proyecto

```
.
├── Estacion_De_Tierra.py       # Punto de entrada de la estación de tierra
├── games/
│   ├── random.py                # Lógica del modo de juego Random
│   └── quiz.py                  # Lógica del modo de juego Quiz
├── dronLink/                    # Librería de control de vuelo del dron
├── CorreccionOjoPez/
│   └── calibration_data_px.yaml # Calibración de la cámara (corrección de distorsión)
├── images/                      # Iconos de la interfaz (dron, jugadores, home, etc.)
├── fotos/                       # Fotografías capturadas durante la partida
├── audios/                      # Ficheros temporales de audio
├── config.json                  # Configuración persistente (generado automáticamente)
├── control.html                 # Aplicación web para el jugador
└── servidor_web.py              # Servidor HTTP + señalización WebRTC
```

## Requisitos

### Clonar el repositorio
```bash
git clone https://github.com/tu-usuario/tu-repositorio.git
cd VersiónFinal
```
#### Configuración de Certificados SSL/TLS
Si el servidor web requiere comunicación segura (HTTPS y WSS), es necesario generar certificados SSL.

**Generar certificados autofirmados:**
```bash
# Crear directorio para certificados
mkdir -p WebAppMQTT/certs
cd WebAppMQTT/certs

# Generar clave privada
openssl genrsa -out server.key 2048

# Generar certificado autofirmado (válido por 365 días)
openssl req -new -x509 -key server.key -out server.crt -days 365 -subj "/CN=localhost"
```


### Estación de tierra (Python)

- Python 3.10+
- Paquetes principales:
  - `paho-mqtt`
  - `tkintermapview`
  - `pillow`
  - `numpy`
  - `pyyaml`
  - `pyproj`
  - `shapely`
  - `opencv-python`
  - `torch` (para YOLOv5, vía `torch.hub`)
  - `aiortc`
  - `av`
  - `websockets`
  - `pydub`
  - Librería propia `dronLink` (control del dron)

Instalación orientativa:

```bash
pip install -r requirements.txt
```
O manualmente:
```bash
pip install paho-mqtt tkintermapview pillow numpy pyyaml pyproj shapely opencv-python torch aiortc av websockets pydub
```

> El modelo YOLOv5 (`yolov5s`) se descarga automáticamente la primera vez que se activa la cámara, a través de `torch.hub`.

### Aplicación web

No requiere instalación: es una página estática que se sirve desde `servidor_web.py` y se abre directamente en el navegador del móvil. Utiliza:

- [MQTT.js](https://github.com/mqttjs/MQTT.js) (vía CDN) para la conexión con el bróker.
- APIs nativas del navegador: `SpeechSynthesis`, `SpeechRecognition`, `Geolocation`, `WebRTC` y `Web Audio API`.

Requiere un navegador móvil moderno con soporte de `SpeechRecognition` (recomendado: Chrome para Android) y conexión HTTPS/WSS para que el navegador autorice el acceso a micrófono y geolocalización.

## Puesta en marcha

1. **Configurar el dron**:
   - En modo simulación (por defecto), la estación de tierra se conecta al simulador de Mission Planner vía TCP en `127.0.0.1:5763`.
   - En modo producción, se conecta al dron real mediante radio de telemetría por el puerto `COM3` a 57600 baudios.
   - El modo se alterna desde la opción "Simulación" del panel de la estación de tierra.

2. **Arrancar la estación de tierra**:

   ```bash
   python Estacion_De_Tierra.py
   ```

3. **Arrancar el servidor web** (sirve `control.html` y gestiona la señalización WebRTC):

   ```bash
   python servidor_web.py
   ```

4. **Conectar los jugadores**: cada jugador abre la URL del servidor web desde su móvil, concede los permisos de geolocalización y micrófono, y selecciona su color de jugador.

5. **Seleccionar el modo de juego** (Random o Quiz) desde el desplegable del panel "Juego" en la estación de tierra, y pulsar "Iniciar" para comenzar la partida.

## Añadir un nuevo modo de juego

El sistema está diseñado para ser ampliable sin modificar la estación de tierra. Cualquier módulo de juego que implemente los métodos `construir_panel(parent, root)` y `detener()` puede añadirse simplemente registrándolo en el diccionario `juegos_disponibles` del punto de entrada. Ver el apartado de extensibilidad de la memoria del proyecto para el detalle completo.

## Estado del proyecto

Este proyecto es un Trabajo de Fin de Grado y se encuentra en desarrollo activo. Algunas partes (como el despliegue en servidor de producción) están pendientes de completar.

## Autor

Proyecto desarrollado como Trabajo de Fin de Grado en la EETAC (UPC), dentro del ecosistema DEE (Drone Engineering Ecosystem).