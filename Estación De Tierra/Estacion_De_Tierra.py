import tkinter as tk
from tkinter import ttk
from dronLink.Dron import Dron
import paho.mqtt.client as mqtt
import random
import json
import threading
import time
import ssl
import tkintermapview
from PIL import Image, ImageTk
import numpy as np
import yaml
import os
import base64
from tkinter import messagebox
from pyproj import Transformer
from shapely.geometry import Point, Polygon, LineString
import math
from shapely.geometry import Point, Polygon
from tkinter import Menu
import asyncio
from aiortc import RTCPeerConnection, RTCIceCandidate, RTCSessionDescription, VideoStreamTrack, RTCConfiguration, RTCIceServer
from av import VideoFrame
from websockets import connect
from aiortc.sdp import candidate_from_sdp

import time
import cv2

from games.random import Random
from games.quiz import Quiz

import torch
import pathlib
import warnings

# =========================
# DRON CONTROLLER
# =========================

ESCENARIO_INICIAL = {'type': 'polygon', 'waypoints': [{'lat': 41.2764496, 'lon': 1.9881981}, {'lat': 41.2766391, 'lon': 1.9890323}, {'lat': 41.276369, 'lon': 1.9891557}, {'lat': 41.2761654, 'lon': 1.9883188}]}
RESOLUCION_CAMARA = (640, 480)

CONFIG_FILE = "config.json"

# ── flag global de cierre ──────────────────────────────────────────────────────
_app_closing = False

def save_config(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=4)

def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)


# =========================
# CAMERA CONTROLLER
# =========================

class CameraController:
    """Gestiona todo lo relacionado con la cámara, independientemente del dron."""

    def __init__(self, config):
        self.fishcamera   = config.get("fishcamera", False)
        self.camera_mode  = config.get("camera_mode", 0)
        self.zoomargen    = config.get("zoomargen", 0)
        self.imagenmode   = config.get("imagenmode", 0)

        self.person_center_x = 0
        self.person_center_y = 0
        self.video_center_x  = 0
        self.video_center_y  = 0
        self.img_cara        = ()

        self._camera_active  = False

        # calibración ojo de pez (se carga en ActivarCamara)
        self.cam_matrix  = None
        self.dist_coefs  = None
        self.new_cam_mtx = None
        self._roi        = (0, 0, 640, 480)   # x, y, w, h

        # referencia al frame actual (compartida con WebRTC)
        self.current_frame = None   # usar este atributo en lugar de la global img

    # ── persistencia ──────────────────────────────────────────────────────────
    def _save(self):
        config = load_config()
        config.update({
            "fishcamera":  self.fishcamera,
            "camera_mode": self.camera_mode,
            "zoomargen":   self.zoomargen,
            "imagenmode":  self.imagenmode,
        })
        save_config(config)

    # ── toggles ───────────────────────────────────────────────────────────────
    def toggleFishCamera(self):
        self.fishcamera = not self.fishcamera
        print(f"Modo fishcamera {'activado' if self.fishcamera else 'desactivado'}")
        self._save()

    def toggleCamera(self):
        self.camera_mode = 0 if self.camera_mode else 1
        self._save()
        print(f"Modo Camara Mode: {self.camera_mode}")

    def setMargen(self, valor):
        self.zoomargen = int(valor)
        self._save()

    def setImagenMode(self):
        self.imagenmode = not self.imagenmode
        self._save()

    # ── Selector de camara ─────────────────────────────────────────
    def listar_camaras(self, max_test=6):
        """Prueba índices de cámara y devuelve los que responden."""
        disponibles = []
        for i in range(max_test):
            cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
            if cap is not None and cap.isOpened():
                disponibles.append(i)
            cap.release()
        if not disponibles:
            disponibles = [0]
        return disponibles

    def siguienteCamara(self):
        disponibles = self.listar_camaras()
        if self.camera_mode in disponibles:
            idx_actual = disponibles.index(self.camera_mode)
        else:
            idx_actual = -1
        siguiente = disponibles[(idx_actual + 1) % len(disponibles)]
        self.camera_mode = siguiente
        self._save()
        print(f"Cámara cambiada a índice {siguiente}")
        return siguiente, len(disponibles)

    # ── apertura física de la cámara ─────────────────────────────────────────
    def abrir_camara(self, index=0):
        backends = [cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY]
        for backend in backends:
            cap = cv2.VideoCapture(index, backend)
            if cap.isOpened():
                print("Cámara abierta con backend:", backend)
                return cap
            cap.release()
        return None

    def OpenCamera(self, camera):
        global current_camera
        print(f"Poniendo Camara: {self.camera_mode}")
        nueva = self.camera_mode
        cap = self.abrir_camara(nueva)
        if cap is not None and cap.isOpened():
            print(f"Cámara {nueva} OK")
            current_camera = nueva
            return cap
        else:
            self.toggleCamera()
            print(f"Cámara {nueva} NO funciona, manteniendo {camera}")
        return None

    # ── activación ───────────────────────────────────────────────────────────
    def ActivarCamara(self):
        global current_camera
        ruta_actual = os.path.dirname(os.path.abspath(__file__))
        yamlname = ruta_actual + "/CorreccionOjoPez/calibration_data_px.yaml"
        with open(yamlname) as f:
            data = yaml.safe_load(f)

        self.cam_matrix = np.array(data['camera_matrix'])
        self.dist_coefs = np.array(data['distortion_coefficients'])

        h, w = 480, 640
        new_cam_mtx, roi = cv2.getOptimalNewCameraMatrix(
            self.cam_matrix, self.dist_coefs, (w, h), 1, (w, h))
        self.new_cam_mtx = new_cam_mtx
        self._roi = roi   # (x, y, w, h)

        threading.Thread(target=self._run_camera, daemon=True, name="ActivarCamara").start()

    def _run_camera(self):
        try:
            temp = pathlib.PosixPath
            pathlib.PosixPath = pathlib.WindowsPath
            warnings.filterwarnings("ignore", category=FutureWarning)
            model = torch.hub.load('ultralytics/yolov5', 'yolov5s')
            self._ActivarCamara(model=model, delta_min=0)
        except Exception as e:
            print("Error iniciando cámara:", e)
            messagebox.showerror("Error cámara", f"No se pudo iniciar la cámara:\n{e}")

    def _ActivarCamara(self, model, delta_min):
        global current_camera, img
        print(f"Activando cámara (modo={self.camera_mode})")
        current_camera = self.camera_mode
        cap = self.OpenCamera(current_camera)

        if not cap.isOpened():
            print("No se pudo abrir la cámara")
            return

        self._camera_active = True
        previous = time.time()
        print("Camara ON")
        broker.cameraON = True

        while self._camera_active and cap.isOpened():
            if _app_closing:
                break

            current = time.time()
            if self.camera_mode != current_camera:
                nuevo_cap = self.OpenCamera(current_camera)
                if nuevo_cap is not None:
                    cap = nuevo_cap

            if current - previous > delta_min:
                status, frame = cap.read()
                if not status or frame is None:
                    print("Frame inválido, reintentando...")
                    time.sleep(0.1)
                    continue

                frame = cv2.resize(frame, RESOLUCION_CAMARA)
                frame = self.distorsionOjoPez(frame)
                img = frame               # mantener global para WebRTC
                self.current_frame = frame

                try:
                    pred = model(frame)
                    df = pred.pandas().xyxy[0]
                    df = df[df["confidence"] > 0.5]
                    df = df[df["name"] == "person"]
                    for i in range(df.shape[0]):
                        bbox = df.iloc[i][["xmin", "ymin", "xmax", "ymax"]].values.astype(int)
                        cv2.rectangle(frame, (bbox[0], bbox[1]), (bbox[2], bbox[3]), (255, 0, 0), 2)
                        self.person_center_x = (bbox[0] + bbox[2]) // 2
                        self.person_center_y = (bbox[1] + bbox[3]) // 2
                        self.img_cara = bbox
                        cv2.circle(frame, (self.person_center_x, self.person_center_y), 5, (0, 255, 0), -1)
                        height, width = frame.shape[:2]
                        self.video_center_x = width // 2
                        self.video_center_y = height // 2
                        cv2.circle(frame, (self.video_center_x, self.video_center_y), 5, (0, 255, 0), -1)
                        cv2.line(frame,
                                 (self.person_center_x, self.person_center_y),
                                 (self.video_center_x, self.video_center_y), (0, 255, 0), 2)
                        cv2.putText(frame,
                                    f"{df.iloc[i]['name']}: {round(df.iloc[i]['confidence'], 4)}",
                                    (bbox[0], bbox[1] - 15),
                                    cv2.FONT_HERSHEY_PLAIN, 1, (255, 255, 255), 2)
                except Exception as e:
                    print("Error en inferencia:", e)

                if self.imagenmode:
                    frame = self.apply_zoom(frame)

                if not _app_closing:
                    frame_copy = frame.copy()
                    camera_label.after(0, lambda f=frame_copy: self.actualizar_frame(f))

                previous = current

            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

            elapsed = time.time() - current
            time.sleep(max(0, 0.1 - elapsed))

        cap.release()
        self._camera_active = False

    # ── imagen / zoom ─────────────────────────────────────────────────────────
    def distorsionOjoPez(self, frame):
        try:
            dst = frame
            if self.fishcamera and self.cam_matrix is not None:
                x, y, w, h = self._roi
                u_img = cv2.undistort(dst, self.cam_matrix, self.dist_coefs, None, self.new_cam_mtx)
                dst = u_img[y:y + h, x:x + w]
            frame_resized = cv2.resize(dst, (640, 480), interpolation=cv2.INTER_LINEAR)
            return frame_resized
        except Exception as e:
            print("Error en distorsionOjoPez:", e)
            return frame

    def apply_zoom(self, frame):
        if len(self.img_cara) == 0:
            return frame
        h, w = frame.shape[:2]
        sidex = abs(self.img_cara[0] - self.img_cara[2])
        zoom  = w / sidex
        sidex, sidey = w / zoom, h / zoom

        margen_x = int(self.zoomargen / 100 * w)
        margen_y = int(self.zoomargen / 100 * h)
        recorte_w = sidex + margen_x * 2
        recorte_h = sidey + margen_y * 2

        x1 = self.img_cara[0] - margen_x
        y1 = self.img_cara[1] - margen_y
        x2 = x1 + recorte_w
        y2 = y1 + recorte_h

        if x1 < 0: x1 = 0; x2 = recorte_w
        if y1 < 0: y1 = 0; y2 = recorte_h
        if x2 > w: x2 = w; x1 = w - recorte_w
        if y2 > h: y2 = h; y1 = h - recorte_h

        x1 = max(0, x1); y1 = max(0, y1)
        x2 = min(w, x2); y2 = min(h, y2)
        x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)

        cropped = frame[y1:y2, x1:x2]
        zoomed  = cv2.resize(cropped, (w, h), interpolation=cv2.INTER_LINEAR)
        return zoomed

    def actualizar_frame(self, frame):
        if _app_closing:
            return
        try:
            if frame is None:
                return
            frame   = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h       = int(camera_label.winfo_height())
            delta   = RESOLUCION_CAMARA[1] / h
            w       = int(RESOLUCION_CAMARA[0] / delta)
            if w > 1 and h > 1:
                display_frame = cv2.resize(frame, (w, h), interpolation=cv2.INTER_AREA)
            else:
                display_frame = frame
            img_pil = Image.fromarray(display_frame)
            imgtk   = ImageTk.PhotoImage(image=img_pil)
            camera_label.imgtk = imgtk
            camera_label.configure(image=imgtk)
        except Exception as e:
            print("Error actualizando frame:", e)

    def TomarFoto(self, color):
        global img
        if img is None:
            print("No hay frame disponible para tomar la foto")
            return
        try:
            frame      = self.apply_zoom(img)
            nombre     = time.strftime(color + ".jpg")
            ruta_actual = os.path.dirname(os.path.abspath(__file__))
            ruta_foto  = os.path.join(ruta_actual, "fotos", nombre)
            os.makedirs(os.path.join(ruta_actual, "fotos"), exist_ok=True)
            cv2.imwrite(ruta_foto, frame, [cv2.IMWRITE_JPEG_QUALITY, 100])
            print(f"Foto guardada en: {ruta_foto}")
            _, buffer  = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 100])
            img_base64 = base64.b64encode(buffer).decode()
            return img_base64
        except Exception as e:
            print("Error al tomar foto:", e)


# =========================
# DRONE CONTROLLER
# =========================

class DroneController:
    def __init__(self, camera: CameraController):
        config = load_config()
        self.dron   = Dron()
        self.camera = camera   # referencia a la cámara, NO duplica su lógica

        self.connected  = False
        self.simulation = config.get("simulation", True)

        self.lat     = None
        self.lon     = None
        self.alt     = None
        self.state   = None
        self.heading = None
        self.distance = config.get("distance", 1)
        self.speed    = config.get("speed", 1)

        self.Icon    = None
        self.homelat = None
        self.homelon = None

        self.scenario  = None
        self.movimiento = []

        self._align_active = False

    def _save(self):
        config = load_config()
        config.update({
            "simulation": self.simulation,
            "distance":   self.distance,
            "speed":      self.speed,
        })
        save_config(config)

    def procesarTelemetria(self, telemetryInfo):
        self.lat     = telemetryInfo.get('lat')
        self.lon     = telemetryInfo.get('lon')
        self.alt     = telemetryInfo.get('alt')
        self.state   = telemetryInfo.get('state')
        self.heading = telemetryInfo.get('heading')

        if broker.connected:
            broker.client.publish('demoDash/mobileFlask/telemetryInfo', json.dumps(telemetryInfo))

    def connect(self):
        if self.connected:
            print("Ya está conectado")
            return
        try:
            if self.simulation:
                print("Conectando al simulador en tcp")
                self.dron.connect('tcp:127.0.0.1:5763', 115200, freq=10)
            else:
                print("Conectando al dron en com3")
                self.dron.connect('com3', 57600, freq=10)
            self.connected = True
            connectBtn['bg'] = 'green'
            broker.allowExternal()
            print("Dron conectado")

            self.getEscenario()
            self.dron.send_telemetry_info(self.procesarTelemetria)
            root.after(50, ui_loop)
        except Exception as e:
            print("Error al conectar:", e)
            messagebox.showerror("Error de conexión", f"No se pudo conectar:\n{e}")

    def arm(self):
        if not self.connected:
            self.connect()
        try:
            self.dron.arm(blocking=True)
            armBtn['bg'] = 'green'
            print("Armado")
        except Exception as e:
            print("Error al armar:", e)

    def takeoff(self, alt=2):
        if self.state != "armed":
            self.arm()
        try:
            self.dron.takeOff(alt)
            takeoffBtn['bg'] = 'green'
            print("Despegando")
        except Exception as e:
            print("Error al despegar:", e)

    def move(self, direction):
        if not self.connected:
            print("Dron no conectado")
            return
        try:
            self.dron.unfixHeading()
            self.dron.changeNavSpeed(float(self.speed))
            self.dron.go(direction)
        except Exception as e:
            print("Error en move:", e)

    def MovimientoPrueba(self):
        print("Iniciando movimiento de prueba")
        if not self.connected:
            print("Dron no conectado, no se puede iniciar movimiento de prueba")
            return
        try:
            self.dron.fixHeading()
            self.dron.arm()
            self.dron.changeNavSpeed(1)
            self.dron.takeOff(2)
            print("Volando")
            time.sleep(2)
            print("Desplazando")
            self.dron.go("Right")
            time.sleep(10)
            print("Parando")
            self.dron.go("Stop")
            time.sleep(2)
            self.dron.Land()
            print("Movimiento de prueba completado")
        except Exception as e:
            print("Error en movimiento de prueba:", e)

    def disconnect(self):
        if not self.connected:
            print("Dron no conectado")
            return
        try:
            try:
                self.dron.stop_sending_telemetry_info()
            except Exception:
                pass
            print("State: " + str(self.state))
            if self.state != "connected":
                self.land()
            DeconOK = self.dron.disconnect()
            if DeconOK:
                self.state = "disconnected"
                self.connected = False
                print("Dron desconectado")
        except Exception as e:
            print("Error en Desconectando:", e)

    def land(self):
        if not self.connected:
            print("Dron no conectado")
            return
        try:
            self.dron.Land(blocking=False)
            print("Land ejecutado")
        except Exception as e:
            print("Error en Land:", e)

    def _IniciarThreadParaPruebas(self, function, params=()):
        print("Iniciando thread para pruebas con función:", function.__name__, "y params:", params)
        threading.Thread(target=function, args=params, daemon=True, name="ThreadPruebas").start()

    def Enviar(self, lat, lon, alt=2):
        try:
            print(f"Enviando dron a: lat={lat}, lon={lon}, alt={alt}")
            for path in self.movimiento:
                path.delete()
            self.movimiento.clear()

            if self.lat is None or self.lon is None:
                print("Posición del dron desconocida, esperando telemetría...")
                return

            self.movimiento.append(map_widget.set_path([(lat, lon), (self.lat, self.lon)], color='yellow', width=3))
            self.dron.arm()
            self.dron.takeOff(alt)

            latDentroFence, longDentroFence = CalcuarPosicion(float(lat), float(lon), self.distance)
            print(f"Coordenadas dentro del fence: lat={latDentroFence}, lon={longDentroFence}")
            self.movimiento.append(map_widget.set_path([(latDentroFence, longDentroFence), (self.lat, self.lon)], color='orange', width=3))
            self.dron.unfixHeading()
            time.sleep(1)

            print("Dron enviado a destino")
            self.dron.changeNavSpeed(float(self.speed))
            self.dron.goto(float(latDentroFence), float(longDentroFence), alt)
            print("Dron enviado a destino: ", latDentroFence, " ", longDentroFence)
        except Exception as e:
            print("Error en _Enviar:", e)

    def recolocarDronX(self, speed=0.3):
        """Alinea el dron con la persona detectada por la cámara."""
        print("Recolocando dron en el eje X")
        show_camera()
        self._align_active = True
        t_inicio = time.time()
        dir_x_pre = 0
        try:
            dir_x = self.camera.video_center_x - self.camera.person_center_x
            self.dron.fixHeading()
            time.sleep(1)
            self.dron.changeNavSpeed(float(speed))
            while abs(dir_x) > 20:
                print(f"Desalineación detectada: dir_x={dir_x}")
                if time.time() - t_inicio > 40:
                    print("recolocarDronX: timeout, abortando")
                    break
                if not self._align_active:
                    break
                dir_x = self.camera.video_center_x - self.camera.person_center_x
                if dir_x * dir_x_pre <= 0:
                    dir_x_pre = dir_x
                    if dir_x > 0:
                        self.dron.go("Left")
                    else:
                        self.dron.go("Right")
                time.sleep(0.05)
            print("Parando Dron")
            self.dron.fixHeading()
            self.dron.go("Stop")
            print("Dron alineado en el eje X")
        except Exception as e:
            print("Error en recolocarDronX:", e)
        finally:
            self._align_active = False

    def setDistance(self, valor):
        self.distance = int(valor)
        self._save()

    def setSpeed(self, speed=1):
        if not self.connected:
            print("Dron no conectado")
            return
        try:
            print(f"Cambiando velocidad a {speed}")
            self.speed = speed
            self.dron.changeNavSpeed(float(self.speed))
            self._save()
        except Exception as e:
            print("Error al cambiar velocidad:", e)

    def setStatus(self):
        if not self.connected:
            overlay_text.config(text="Disconnected")
        elif self.state != "arm":
            overlay_text.config(text="Disarmed")
        else:
            overlay_text.config(state="hidden")

    def setEscenario(self, scenario):
        if not self.connected:
            self.connect()
        print("Enviando escenario al dron:", scenario)
        scenario_lista = [scenario]
        if scenario == [] or scenario is None:
            messagebox.showinfo("showinfo", "El scenario está vacío")
        else:
            try:
                self.scenario = scenario_lista
                self.dron.setScenario(scenario_lista)
                drawScenario(self.scenario)
            except Exception as e:
                print("Error al enviar escenario:", e)

    def getEscenario(self):
        try:
            self.scenario = self.dron.getScenario()
            print("Escenario cargado desde el dron:", self.scenario)
            if self.scenario:
                drawScenario(self.scenario)
            else:
                messagebox.showinfo("showinfo", "No hay ningún escenario cargado en el dron")
        except Exception as e:
            print("Error al cargar escenario:", e)

    def toggleSimulation(self):
        self.simulation = not self.simulation
        print(f"Modo simulación {'activado' if self.simulation else 'desactivado'}")
        self._save()


# =========================
# MQTT CONTROLLER
# =========================

class CameraVideoTrack(VideoStreamTrack):
    def __init__(self, broker):
        super().__init__()

    async def recv(self):
        global img
        pts, time_base = await self.next_timestamp()
        timeout = 0
        while img is None:
            await asyncio.sleep(0.02)
            timeout += 1
            if timeout > 250:
                frame = np.zeros((480, 640, 3), dtype=np.uint8)
                avf = VideoFrame.from_ndarray(frame, format="rgb24")
                avf.pts = pts
                avf.time_base = time_base
                return avf
        frame = img.copy()
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        avf = VideoFrame.from_ndarray(frame, format="rgb24")
        avf.pts = pts
        avf.time_base = time_base
        return avf


class MQTTController:
    def __init__(self):
        self.client    = None
        self.connected = False
        self.cameraON  = False
        self.users     = {}
        self.GameState = None
        self.GameStart = False
        self.ofertas   = []

    def dict_to_ice_candidate(self, cand: dict):
        if cand is None:
            return None
        ice = candidate_from_sdp(cand["candidate"])
        ice.sdpMid        = cand.get("sdpMid") or "0"
        ice.sdpMLineIndex = cand.get("sdpMLineIndex") or 0
        return ice

    async def cleanup_client(self, id):
        pc = next((item["conexion"] for item in self.ofertas if item["id"] == id), None)
        if not pc:
            return
        for sender in pc.getSenders():
            if sender.track:
                sender.track.stop()
        if pc.connectionState != "closed":
            await pc.close()
        self.ofertas = [item for item in self.ofertas if item["id"] != id]

    def WebRTC(self):
        threading.Thread(
            target=lambda: asyncio.run(self._run_webRTC()),
            daemon=True,
            name="WebRTCThread"
        ).start()

    async def _run_webRTC(self):
        ssl_context = ssl._create_unverified_context()
        while True:
            try:
                async with connect("wss://192.168.1.144:8110", ssl=ssl_context) as ws:
                    await ws.send(json.dumps({"type": "registro", "role": "emisor"}))
                    async for raw in ws:
                        data = json.loads(raw)
                        if data.get("type") == "peticion":
                            id = data.get("id")
                            config = RTCConfiguration(iceServers=[
                                RTCIceServer(urls="turn:standard.relay.metered.ca:80",
                                             username="337f189c0bf26e1022e19f05",
                                             credential="pSwi01maZzQZTUAf"),
                                RTCIceServer(urls="stun:stun.l.google.com:19302")
                            ])
                            pc = RTCPeerConnection(config)

                            @pc.on("icecandidate")
                            async def on_ice(candidate, _id=id, _ws=ws):
                                if candidate:
                                    await _ws.send(json.dumps({"type":"ice","role":"emisor","id":_id,"candidate":candidate.to_dict()}))
                                else:
                                    await _ws.send(json.dumps({"type":"ice","role":"emisor","id":_id,"candidate":None}))

                            track = CameraVideoTrack(self)
                            pc.addTrack(track)
                            offer = await pc.createOffer()
                            await pc.setLocalDescription(offer)
                            self.ofertas.append({'id': id, 'conexion': pc})
                            await ws.send(json.dumps({"type":"sdp","role":"emisor","id":id,"sdp":pc.localDescription.sdp,"sdp_type":pc.localDescription.type}))

                        elif data.get("type") == "sdp":
                            id  = data.get("id")
                            desc = RTCSessionDescription(sdp=data["sdp"], type=data["sdp_type"])
                            pc  = next((item["conexion"] for item in self.ofertas if item["id"] == id), None)
                            if pc:
                                await pc.setRemoteDescription(desc)

                        elif data.get("type") == "ice" and data.get("role") == "receptor":
                            id = data.get("id")
                            pc = next((item["conexion"] for item in self.ofertas if item["id"] == id), None)
                            if not pc:
                                continue
                            try:
                                rtc_cand = self.dict_to_ice_candidate(data.get("candidate"))
                                await pc.addIceCandidate(rtc_cand)
                            except Exception as e:
                                print("Error añadiendo candidato:", e)

                        elif data.get("type") == "client-disconnect":
                            await self.cleanup_client(data.get("id"))

            except Exception as e:
                print(f"WebRTC: conexión perdida ({e}), reconectando en 5s...")
                for item in self.ofertas:
                    try:
                        await item["conexion"].close()
                    except Exception:
                        pass
                self.ofertas = []
                await asyncio.sleep(5)

    def allowExternal(self):
        if self.connected and self.client:
            return
        try:
            clientName = "demoDash" + str(random.randint(1000, 9000))
            self.client = mqtt.Client(clientName, transport="websockets")
            broker_address = 'broker.hivemq.com'
            self.client.tls_set(ca_certs=None, certfile=None, keyfile=None,
                                cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLS, ciphers=None)
            broker_port = 8884
            self.client.on_message = self.on_message
            self.client.on_connect = self.on_connect
            self.client.connect(broker_address, broker_port)
            print('Conectado a broker.hivemq.com:8884')
            self.connected = True
            self.client.subscribe('mobileFlask/demoDash/#')
            self.WebRTC()
            self.ChangeGameState("SelectMode")
            self.client.loop_start()
        except Exception as e:
            print("Error al conectar MQTT:", e)
            self.connected = False

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print("connected OK Returned code=", rc)
        else:
            print("Bad connection Returned code=", rc)
            self.connected = False

    def asignarcolor(self, coords, color):
        lat  = float(coords[0])
        long = float(coords[1])
        if color not in self.users:
            self.users[color] = {"lat": lat, "long": long, "puntos": 0}
        else:
            self.users[color]["lat"]  = lat
            self.users[color]["long"] = long
        DibujarMarcador(lat, long, color)
        self.client.publish('demoDash/mobileFlask/Coordenadas', json.dumps(self.users))

    def ChangeGameState(self, state):
        self.GameState = state
        self.client.publish('demoDash/mobileFlask/GameState', self.GameState)

    def EliminarColor(self, color=None):
        global personMarkers
        for c in self.users.keys():
            if color is None or c == color:
                if personMarkers[c]:
                    personMarkers[c].delete()
                    personMarkers[c] = None
        self.users = {}
        self.client.publish('demoDash/mobileFlask/Coordenadas', json.dumps(self.users))

    def IniciarJuego(self):
        if broker.cameraON and not self.GameStart:
            self.GameStart = True
            threading.Thread(target=self._IniciarJuego, daemon=True, name="GameThread").start()
        else:
            messagebox.showinfo("showinfo", "El juego requiere que la cámara esté activada.")

    def _IniciarJuego(self):
        self.ChangeGameState("PlayingMode")
        quiz.J1IniciarJuego()
        print("Finalizando IniciarJuego")
        self.GameStart = False

    def EnviarMensaje(self, topic, message=""):
        if self.connected:
            self.client.publish(topic, message)
        else:
            print("No se puede enviar mensaje, MQTT no conectado")

    def on_message(self, client, userdata, message):
        try:
            parts = message.topic.split('/')
            if len(parts) < 3:
                return
            command = parts[2]
            print('recibo', command)
            payload = message.payload.decode("utf-8")

            # ── Lógica propia de la estación de tierra ─────────────────────
            if command == 'PedirCoordenadas':
                partes = payload.split(',')
                if len(partes) != 3:
                    return
                lat, long, color = partes
                self.asignarcolor((lat, long), color)

            # ── Todo lo relacionado con el juego se delega a Quiz ──────────
            elif command in ('Respuesta', 'PedirState',
                              'PedirDron', 'PedirFoto', 'PedirPregunta','PedirStartTimer', 'StopTimer'):
                quiz.handle_message(command, payload)

        except Exception as e:
            print("Error en on_message:", e)


# =========================
# UI HELPERS
# =========================

def reset_buttons():
    connectBtn.config(bg="dark orange")
    armBtn.config(bg="dark orange")
    takeoffBtn.config(bg="dark orange")
    landBtn.config(bg="dark orange")
    DisBtn.config(bg="dark orange")


def set_state_buttons(state):
    reset_buttons()
    if state == "disconnected": return
    connectBtn.config(bg="green")
    if state == "connected": return
    if state == "arming":
        armBtn.config(bg="yellow"); return
    armBtn.config(bg="green")
    if state == "armed": return
    if state == "takingOff":
        takeoffBtn.config(bg="yellow"); return
    takeoffBtn.config(bg="green")
    if state == "flying": return
    if state == "landing":
        landBtn.config(bg="yellow")


def calcular_punto_heading(lat, lon, heading, distancia_m):
    R = 6378137
    heading_rad = math.radians(heading)
    lat_rad     = math.radians(lat)
    lon_rad     = math.radians(lon)
    nueva_lat   = math.asin(
        math.sin(lat_rad) * math.cos(distancia_m / R) +
        math.cos(lat_rad) * math.sin(distancia_m / R) * math.cos(heading_rad)
    )
    nueva_lon = lon_rad + math.atan2(
        math.sin(heading_rad) * math.sin(distancia_m / R) * math.cos(lat_rad),
        math.cos(distancia_m / R) - math.sin(lat_rad) * math.sin(nueva_lat)
    )
    return math.degrees(nueva_lat), math.degrees(nueva_lon)


def ActualizarState(lat, lon, alt, state):
    global lat_value, lon_value, alt_value, state_value
    global connectBtn, armBtn, takeoffBtn, DisBtn, landBtn

    if _app_closing:
        return

    head_lat, head_lon = calcular_punto_heading(lat, lon, dron.heading, 20)
    if lat is None or lon is None or alt is None:
        return

    if not dron.Icon:
        map_widget.set_position(lat, lon)
        map_widget.set_marker(lat, lon, icon=homePicture, icon_anchor="center")
        dron.Icon = map_widget.set_marker(lat, lon, icon=dronPicture, icon_anchor="center")
        dron.headingLine = map_widget.set_path([(lat, lon), (head_lat, head_lon)], color='purple', width=3)
        dron.homelat = lat
        dron.homelon = lon
        dron.lat, dron.lon, dron.alt, dron.state = lat, lon, alt, state
    else:
        dron.lat, dron.lon, dron.alt, dron.state = lat, lon, alt, state
        dron.Icon.set_position(lat, lon)
        dron.headingLine.set_position_list([(lat, lon), (head_lat, head_lon)])

    set_state_buttons(state)
    lat_value.config(text=f"{lat:.6f}")
    lon_value.config(text=f"{lon:.6f}")
    alt_value.config(text=f"{alt:.2f} m")
    state_value.config(text=state)


personMarkers = {"green": None, "yellow": None, "red": None, "blue": None}


def DibujarMarcador(lat, lon, color):
    global personMarkers
    icon = {"green":  lambda: person_green,
            "yellow": lambda: person_yellow,
            "red":    lambda: person_red,
            "blue":   lambda: person_blue}.get(color)
    if icon is None:
        print("Color no soportado:", color)
        return
    if personMarkers[color]:
        personMarkers[color].set_position(lat, lon)
    else:
        personMarkers[color] = map_widget.set_marker(lat, lon, icon=icon(), icon_anchor="center")
    print(f"Marcador {color} dibujado o actualizado en el mapa")


def drawScenario(scenario):
    global polys
    for poly in polys:
        try:
            poly.delete()
        except Exception:
            pass
    polys.clear()
    inclusion = scenario[0]
    if inclusion['type'] == 'polygon':
        poly = [(p['lat'], p['lon']) for p in inclusion['waypoints']]
        polys.append(map_widget.set_polygon(poly, outline_color="blue", fill_color=None, border_width=3))
    for i in range(1, len(scenario)):
        poly = [(p['lat'], p['lon']) for p in scenario[i]['waypoints']]
        polys.append(map_widget.set_polygon(poly, outline_color="red", fill_color="red", border_width=3))


def CalcuarPosicion(lat, lon, distance):
    global dron
    if not dron.scenario:
        return lat, lon
    fence = dron.scenario[0]
    transformer      = Transformer.from_crs(4326, 32631, always_xy=True)
    transformer_back = Transformer.from_crs(32631, 4326, always_xy=True)
    poly_coords = [transformer.transform(p['lon'], p['lat']) for p in fence['waypoints']]
    polygon     = Polygon(poly_coords)
    if not polygon.is_valid or polygon.area == 0:
        return lat, lon
    target_x, target_y = transformer.transform(lon, lat)
    if dron.lat is None or dron.lon is None:
        return lat, lon
    dron_x, dron_y = transformer.transform(dron.lon, dron.lat)
    dron_point     = Point(dron_x, dron_y)
    line           = LineString([(dron_x, dron_y), (target_x, target_y)])
    intersection   = line.intersection(polygon.exterior)
    if intersection.is_empty:
        return lat, lon
    points      = [intersection] if intersection.geom_type == 'Point' else list(intersection.geoms)
    entry_point = min(points, key=lambda p: p.distance(dron_point))
    dx = dron_x - entry_point.x
    dy = dron_y - entry_point.y
    norm = math.hypot(dx, dy)
    if norm == 0:
        return lat, lon
    dx /= norm; dy /= norm
    safe_x = entry_point.x + dx * distance
    safe_y = entry_point.y + dy * distance
    safe_lon, safe_lat = transformer_back.transform(safe_x, safe_y)
    return safe_lat, safe_lon


def show_map():
    mapaFrame.tkraise()


def show_camera():
    global camera_running
    cameraFrame.tkraise()
    if not camera_running:
        camera.ActivarCamara()
        camera_running = True
        # Poner el botón de cámara en verde cuando se activa
        if CameraBtn:
            CameraBtn.config(bg="#27ae60", fg="white")


def ui_loop():
    if _app_closing:
        return
    ActualizarState(dron.lat, dron.lon, dron.alt, dron.state)
    root.after(50, ui_loop)


# =========================
# TOGGLE SWITCH WIDGET
# =========================

class ToggleSwitch(tk.Frame):
    """
    Toggle switch estilizado con indicador LED y etiqueta.
    Reemplaza los checkbuttons planos de las Opciones.
    """
    COLOR_ON  = "#27ae60"   # verde
    COLOR_OFF = "#555555"   # gris oscuro
    LED_ON    = "#2ecc71"
    LED_OFF   = "#888888"

    def __init__(self, parent, label, icon, command, initial=False, **kwargs):
        super().__init__(parent, bg="#e8e8e8", **kwargs)
        self._on      = initial
        self._command = command

        # ── LED indicador ─────────────────────────────────────────────────────
        self._led = tk.Label(self, width=2, bg=self.LED_ON if initial else self.LED_OFF,
                             relief="flat", bd=0)
        self._led.pack(side="left", padx=(6, 4), pady=6)

        # ── etiqueta ──────────────────────────────────────────────────────────
        self._lbl = tk.Label(self, text=f"{icon}  {label}", bg="#e8e8e8", fg="#1a1a1a",
                             font=("Segoe UI", 9), anchor="w", width=14)
        self._lbl.pack(side="left", pady=6)

        # ── botón ON/OFF ──────────────────────────────────────────────────────
        self._btn = tk.Button(self,
                              text="ON" if initial else "OFF",
                              bg=self.COLOR_ON if initial else self.COLOR_OFF,
                              fg="white", font=("Segoe UI", 8, "bold"),
                              relief="flat", bd=0, padx=8, pady=2,
                              activebackground="#1a8a47" if initial else "#333333",
                              cursor="hand2",
                              command=self._toggle)
        self._btn.pack(side="right", padx=6, pady=6)

    def _toggle(self):
        self._on = not self._on
        self._btn.config(
            text="ON" if self._on else "OFF",
            bg=self.COLOR_ON  if self._on else self.COLOR_OFF,
            activebackground="#1a8a47" if self._on else "#333333"
        )
        self._led.config(bg=self.LED_ON if self._on else self.LED_OFF)
        if self._command:
            self._command()

    def get(self):
        return self._on


# =========================
# MAIN WINDOW
# =========================

def Ventana(dron, broker, camera):
    global person_blue, person_green, person_red, person_yellow, i_wp
    global map_widget
    global homePicture
    global dronIcon
    global polys
    global lat_value, lon_value, alt_value, state_value
    global connectBtn, armBtn, takeoffBtn, DisBtn, landBtn
    global paths, fence, scenario
    global camera_label
    global mapaFrame, cameraFrame
    global camera_running
    global dronPicture
    global overlay_text
    global CameraBtn
    global _app_closing

    fence          = {'type': 'polygon', 'waypoints': []}
    camera_running = False
    CameraBtn      = None
    paths          = []
    scenario       = []
    polys          = []

    root = tk.Tk()
    root.config(width=300, height=300)
    root.rowconfigure(0, weight=1)
    root.columnconfigure(4, weight=1)

    def on_closing():
        global _app_closing
        print("Cerrando aplicación...")

        _app_closing = True

        camera._camera_active  = False
        dron._align_active     = False
        quiz.detener()

        if broker.client:
            try:
                broker.client.loop_stop()
                broker.client.disconnect()
            except Exception:
                pass

        try:
            map_widget.destroy()
        except Exception:
            pass

        root.after(150, root.destroy)

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.geometry("1200x800")
    root.minsize(800, 600)
    root.update_idletasks()

    # ── paleta oscura para el panel izquierdo ─────────────────────────────────
    DARK_BG   = "#f0f0f0"
    PANEL_BG  = "#e8e8e8"
    ACCENT    = "dark orange"  # naranja estándar tkinter
    TEXT_CLR  = "#1a1a1a"
    SUBTEXT   = "#555555"

    root.config(bg=DARK_BG)

    # ── panel izquierdo con scroll ──────────────────────────────────────────
    # Se usa un Canvas + Scrollbar porque el contenido (Control, Estado,
    # Juego -que crece según el juego activo- y Opciones) puede superar el
    # alto de la ventana. leftFrame sigue siendo el "parent" de siempre para
    # todo lo que se añade a continuación (styled_lf, etc.), solo que ahora
    # vive dentro del canvas con scroll en vez de ir directo a root.
    leftContainer = tk.Frame(root, bg=DARK_BG, width=230)
    leftContainer.grid(row=0, column=0, sticky="ns")
    leftContainer.grid_propagate(False)

    leftCanvas = tk.Canvas(leftContainer, bg=DARK_BG, width=230, highlightthickness=0)
    leftScrollbar = tk.Scrollbar(leftContainer, orient="vertical", command=leftCanvas.yview)
    leftCanvas.configure(yscrollcommand=leftScrollbar.set)
    leftScrollbar.pack(side="right", fill="y")
    leftCanvas.pack(side="left", fill="both", expand=True)

    leftFrame = tk.Frame(leftCanvas, bg=DARK_BG)
    leftFrame_id = leftCanvas.create_window((0, 0), window=leftFrame, anchor="nw")

    def _on_leftFrame_configure(event):
        leftCanvas.configure(scrollregion=leftCanvas.bbox("all"))
    leftFrame.bind("<Configure>", _on_leftFrame_configure)

    def _on_leftCanvas_configure(event):
        leftCanvas.itemconfig(leftFrame_id, width=event.width)
    leftCanvas.bind("<Configure>", _on_leftCanvas_configure)

    def _on_mousewheel(event):
        leftCanvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
    def _bind_mousewheel(event):
        leftCanvas.bind_all("<MouseWheel>", _on_mousewheel)
    def _unbind_mousewheel(event):
        leftCanvas.unbind_all("<MouseWheel>")
    leftCanvas.bind("<Enter>", _bind_mousewheel)
    leftCanvas.bind("<Leave>", _unbind_mousewheel)

    # ── helper para LabelFrame con estilo ─────────────────────────────────────
    def styled_lf(parent, title, row):
        lf = tk.LabelFrame(parent, text=title, bg=PANEL_BG, fg=ACCENT,
                           font=("Segoe UI", 9, "bold"), bd=1, relief="groove",
                           padx=4, pady=4)
        lf.grid(row=row, column=0, padx=6, pady=(4, 2), sticky="ew")
        lf.columnconfigure(0, weight=1)
        lf.columnconfigure(1, weight=1)
        return lf

    # ─────────────────────────────────────────────────────────────────────────
    # 1. CONTROL DE VUELO
    # ─────────────────────────────────────────────────────────────────────────
    controlFrame = styled_lf(leftFrame, "Control", 0)

    BTN_STYLE = dict(bg=ACCENT, fg="#111111", font=("Segoe UI", 8, "bold"),
                     relief="flat", bd=0, padx=4, pady=3, cursor="hand2")

    connectBtn  = tk.Button(controlFrame, text="Conectar",  **BTN_STYLE, command=dron.connect)
    connectBtn.grid(row=0, column=0, padx=2, pady=2, sticky="ew")
    armBtn      = tk.Button(controlFrame, text="Armar",     **BTN_STYLE, command=dron.arm)
    armBtn.grid(row=0, column=1, padx=2, pady=2, sticky="ew")
    takeoffBtn  = tk.Button(controlFrame, text="Despegar",  **BTN_STYLE, command=dron.takeoff)
    takeoffBtn  .grid(row=0, column=2, padx=2, pady=2, sticky="ew")
    controlFrame.columnconfigure(2, weight=1)

    # D-pad
    tk.Button(controlFrame, text="🡸", **BTN_STYLE, command=lambda: dron.move("West")) .grid(row=2, column=0, padx=2, pady=2, sticky="ew")
    tk.Button(controlFrame, text="⏸", **BTN_STYLE, command=lambda: dron.move("Stop")) .grid(row=2, column=1, padx=2, pady=2, sticky="ew")
    tk.Button(controlFrame, text="🡺", **BTN_STYLE, command=lambda: dron.move("East")) .grid(row=2, column=2, padx=2, pady=2, sticky="ew")
    tk.Button(controlFrame, text="🡹", **BTN_STYLE, command=lambda: dron.move("North")).grid(row=1, column=1, padx=2, pady=2, sticky="ew")
    tk.Button(controlFrame, text="🡻", **BTN_STYLE, command=lambda: dron.move("South")).grid(row=3, column=1, padx=2, pady=2, sticky="ew")

    DisBtn  = tk.Button(controlFrame, text="Desconectar", **BTN_STYLE, command=dron.disconnect)
    DisBtn.grid(row=4, column=0, columnspan=2, padx=2, pady=(4, 2), sticky="ew")
    landBtn = tk.Button(controlFrame, text="Aterrizar",   **BTN_STYLE, command=dron.land)
    landBtn.grid(row=4, column=2, padx=2, pady=(4, 2), sticky="ew")

    # ─────────────────────────────────────────────────────────────────────────
    # 2. ESTADO / VISTA
    # ─────────────────────────────────────────────────────────────────────────
    selectFrame = styled_lf(leftFrame, "Estado", 1)

    def lbl_pair(parent, text, row):
        tk.Label(parent, text=text, bg=PANEL_BG, fg=SUBTEXT,
                 font=("Segoe UI", 8)).grid(row=row, column=0, sticky="w", padx=4)
        val = tk.Label(parent, text="—", bg=PANEL_BG, fg=TEXT_CLR,
                       font=("Segoe UI", 8, "bold"))
        val.grid(row=row, column=1, sticky="w", padx=4)
        return val

    lat_value   = lbl_pair(selectFrame, "Latitud:",   0)
    lon_value   = lbl_pair(selectFrame, "Longitud:",  1)
    alt_value   = lbl_pair(selectFrame, "Altitud:",   2)
    state_value = lbl_pair(selectFrame, "Estado:",    3)

    view_row = tk.Frame(selectFrame, bg=PANEL_BG)
    view_row.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(4, 2))
    MapBtn    = tk.Button(view_row, text="Mapa",   bg="#5b9bd5", fg="white",
                          font=("Segoe UI", 8, "bold"), relief="flat", padx=6, pady=3,
                          cursor="hand2", command=show_map)
    MapBtn.pack(side="left", expand=True, fill="x", padx=(0, 2))

    CameraBtn = tk.Button(view_row, text="Cámara", bg=ACCENT, fg="white",
                          font=("Segoe UI", 8, "bold"), relief="flat", padx=6, pady=3,
                          cursor="hand2", command=show_camera)
    CameraBtn.pack(side="left", expand=True, fill="x")

    # zoom + imagen mode en selectFrame
    tk.Label(selectFrame, text="Zoom margen (%):", bg=PANEL_BG, fg=SUBTEXT,
             font=("Segoe UI", 8)).grid(row=5, column=0, sticky="w", padx=4, pady=(4, 0))
    zoomBrr = tk.Scale(selectFrame, from_=0, to=50, orient=tk.HORIZONTAL,
                       command=camera.setMargen,
                       bg=PANEL_BG, fg=TEXT_CLR, highlightthickness=0,
                       troughcolor="#cccccc", activebackground=ACCENT)
    zoomBrr.grid(row=6, column=0, columnspan=2, sticky="ew", padx=4)
    zoomBrr.set(camera.zoomargen)

    ImagenBtn = tk.Button(selectFrame, text="Modo Imagen / Dron", bg="#cccccc", fg="#1a1a1a",
                          font=("Segoe UI", 8), relief="flat", padx=4, pady=3,
                          cursor="hand2", command=camera.setImagenMode)
    ImagenBtn.grid(row=7, column=0, columnspan=2, sticky="ew", padx=4, pady=(2, 4))

    # ─────────────────────────────────────────────────────────────────────────
    # 3. JUEGO  ← selector + contenedor genérico
    # ─────────────────────────────────────────────────────────────────────────
    gameFrame = styled_lf(leftFrame, "Juego", 2)

    # Selector de juego activo. La estación de tierra solo conoce el nombre
    # de cada juego y su objeto asociado; toda la UI específica del juego
    # vive dentro de game_panel_frame, construida por el propio juego.

    nuevojuego = {}
    juegos_disponibles = {
        "Quiz":   quiz,
        "Random": random_game,
        "Nuevo Juego": nuevojuego  
    }

    game_select_row = tk.Frame(gameFrame, bg=PANEL_BG)
    game_select_row.grid(row=0, column=0, columnspan=2, sticky="ew", padx=4, pady=(0, 4))
    tk.Label(game_select_row, text="Modo:", bg=PANEL_BG, fg=SUBTEXT,
             font=("Segoe UI", 8)).pack(side="left", padx=(0, 4))

    game_select_var = tk.StringVar(value="Quiz")
    game_select_combo = ttk.Combobox(game_select_row, textvariable=game_select_var,
                                      values=list(juegos_disponibles.keys()),
                                      state="readonly", width=12, font=("Segoe UI", 8))
    game_select_combo.pack(side="left", fill="x", expand=True)

    game_panel_frame = tk.Frame(gameFrame, bg=PANEL_BG)
    game_panel_frame.grid(row=1, column=0, columnspan=2, sticky="ew")
    gameFrame.rowconfigure(1, weight=1)

    juego_actual = {"obj": None}

    def cambiar_juego(nombre):
        juego_nuevo = juegos_disponibles.get(nombre)
        if juego_nuevo is None:
            print(f"cambiar_juego: '{nombre}' no es un juego válido")
            return

        # Detener y limpiar el panel del juego anterior
        juego_anterior = juego_actual["obj"]
        if juego_anterior is not None and hasattr(juego_anterior, 'detener'):
            juego_anterior.detener()

        for widget in game_panel_frame.winfo_children():
            widget.destroy()

        # Construir el panel del nuevo juego
        if hasattr(juego_nuevo, 'construir_panel'):
            juego_nuevo.construir_panel(game_panel_frame, root)
        else:
            tk.Label(game_panel_frame, text=f"'{nombre}'\nno implementa construir_panel",
                     bg=PANEL_BG, fg="#c0392b", font=("Segoe UI", 8)).pack(padx=4, pady=4)

        juego_actual["obj"] = juego_nuevo
        print(f"Juego activo: {nombre}")

    def on_game_select(event=None):
        cambiar_juego(game_select_var.get())

    game_select_combo.bind("<<ComboboxSelected>>", on_game_select)

    # Cargar el juego por defecto (Quiz) al construir la ventana
    cambiar_juego(game_select_var.get())

    # ─────────────────────────────────────────────────────────────────────────
    # 4. OPCIONES  ← ahora con ToggleSwitches estilizados
    # ─────────────────────────────────────────────────────────────────────────
    OptionFrame = styled_lf(leftFrame, "Opciones", 3)
    OptionFrame.config(padx=0, pady=0)

    toggle_sim  = ToggleSwitch(OptionFrame, "Simulación",  "",
                               dron.toggleSimulation,  initial=dron.simulation)
    toggle_sim.grid(row=0, column=0, columnspan=2, sticky="ew", padx=2, pady=1)

    toggle_fish = ToggleSwitch(OptionFrame, "Ojo de pez",  "",
                               camera.toggleFishCamera, initial=camera.fishcamera)
    toggle_fish.grid(row=1, column=0, columnspan=2, sticky="ew", padx=2, pady=1)

    # ── selector de cámara: etiqueta y botón en filas separadas para que no
    # se solapen aunque el texto crezca con más cámaras detectadas ──────────
    cam_row = tk.Frame(OptionFrame, bg=PANEL_BG)
    cam_row.grid(row=2, column=0, columnspan=2, sticky="ew", padx=2, pady=1)
    cam_row.columnconfigure(0, weight=1)

    cam_label_var = tk.StringVar(value=f"Cámara {camera.camera_mode}")
    tk.Label(cam_row, textvariable=cam_label_var, bg=PANEL_BG, fg=TEXT_CLR,
             font=("Segoe UI", 8, "bold"), anchor="w"
             ).grid(row=0, column=0, sticky="ew", padx=4, pady=(2, 0))

    def on_cambiar_camara():
        idx, total = camera.siguienteCamara()
        cam_label_var.set(f"Cámara {idx} ({total} disp.)")

    tk.Button(cam_row, text="Cambiar cámara", bg=ACCENT, fg="white",
              font=("Segoe UI", 8, "bold"), relief="flat", padx=6, pady=3,
              cursor="hand2", command=on_cambiar_camara
              ).grid(row=1, column=0, sticky="ew", padx=4, pady=(2, 4))

    # sliders de dron en Opciones
    sep = tk.Frame(OptionFrame, bg="#bbbbbb", height=1)
    sep.grid(row=3, column=0, columnspan=2, sticky="ew", padx=6, pady=4)

    tk.Label(OptionFrame, text="Dist. al Fence:", bg=PANEL_BG, fg=SUBTEXT,
             font=("Segoe UI", 8)).grid(row=4, column=0, sticky="w", padx=6)
    DistanceBrr = tk.Scale(OptionFrame, from_=1, to=10, orient=tk.HORIZONTAL,
                           command=dron.setDistance,
                           bg=PANEL_BG, fg=TEXT_CLR, highlightthickness=0,
                           troughcolor="#cccccc", activebackground=ACCENT, showvalue=True)
    DistanceBrr.grid(row=5, column=0, columnspan=2, sticky="ew", padx=6, pady=(0, 2))
    DistanceBrr.set(dron.distance)

    tk.Label(OptionFrame, text="Velocidad dron:", bg=PANEL_BG, fg=SUBTEXT,
             font=("Segoe UI", 8)).grid(row=6, column=0, sticky="w", padx=6)
    SpeedBrr = tk.Scale(OptionFrame, from_=1, to=5, orient=tk.HORIZONTAL,
                        command=dron.setSpeed,
                        bg=PANEL_BG, fg=TEXT_CLR, highlightthickness=0,
                        troughcolor="#cccccc", activebackground=ACCENT, showvalue=True)
    SpeedBrr.grid(row=7, column=0, columnspan=2, sticky="ew", padx=6, pady=(0, 4))
    SpeedBrr.set(dron.speed)

    # ─────────────────────────────────────────────────────────────────────────
    # VISTA PRINCIPAL (mapa + cámara)
    # ─────────────────────────────────────────────────────────────────────────
    viewFrame = tk.Frame(root, bg=DARK_BG)
    viewFrame.grid(row=0, column=4, rowspan=40, sticky="nsew")
    mapaFrame   = tk.Frame(viewFrame, bg=DARK_BG)
    cameraFrame = tk.Frame(viewFrame, bg="black")
    mapaFrame.grid(row=0, column=0, sticky="nsew")
    cameraFrame.grid(row=0, column=0, sticky="nsew")

    camera_label = tk.Label(cameraFrame, bg="black")
    camera_label.grid(row=0, column=0, sticky="nsew")
    camera_label.pack_propagate(False)
    camera_label.grid_propagate(False)

    viewFrame.rowconfigure(0, weight=1)
    viewFrame.columnconfigure(0, weight=1)

    map_widget = tkintermapview.TkinterMapView(mapaFrame, width=900, height=600, corner_radius=0)
    map_widget.grid(row=0, column=0, sticky="nsew")
    map_widget.set_tile_server("https://mt0.google.com/vt/lyrs=s&hl=en&x={x}&y={y}&z={z}&s=Ga", max_zoom=22)
    map_widget.set_position(float(41.2764496), float(1.9881981))
    map_widget.set_zoom(19)
    mapaFrame.rowconfigure(0, weight=1)
    mapaFrame.columnconfigure(0, weight=1)
    cameraFrame.rowconfigure(0, weight=1)
    cameraFrame.columnconfigure(0, weight=1)

    # ── iconos ────────────────────────────────────────────────────────────────
    ruta_actual = os.path.dirname(os.path.abspath(__file__))

    def load_icon(name, size=(20, 20)):
        pic = Image.open(ruta_actual + f"/images/{name}.png").resize(size, Image.LANCZOS)
        return ImageTk.PhotoImage(pic)

    dronPicture  = load_icon("drone")
    dronIcon     = None
    person_green  = load_icon("green")
    person_yellow = load_icon("yellow")
    person_red    = load_icon("red")
    person_blue   = load_icon("blue")
    homePicture   = load_icon("home")
    i_wp          = load_icon("i_wp")

    # ── menú ──────────────────────────────────────────────────────────────────
    map_widget.add_right_click_menu_command(label="Azul",     command=lambda c: broker.asignarcolor(c, "blue"),   pass_coords=True)
    map_widget.add_right_click_menu_command(label="Amarillo", command=lambda c: broker.asignarcolor(c, "yellow"), pass_coords=True)
    map_widget.add_right_click_menu_command(label="Verde",    command=lambda c: broker.asignarcolor(c, "green"),  pass_coords=True)
    map_widget.add_right_click_menu_command(label="Rojo",     command=lambda c: broker.asignarcolor(c, "red"),    pass_coords=True)

    barra_menu = Menu(root)
    menu_fence = Menu(barra_menu, tearoff=0)
    menu_fence.add_command(label="Cargar Escenario",       command=dron.getEscenario)
    menu_fence.add_command(label="Guardar EETAC Escenario", command=lambda: dron.setEscenario(ESCENARIO_INICIAL))
    barra_menu.add_cascade(label="Geofence", menu=menu_fence)

    menu_colores = Menu(barra_menu, tearoff=0)
    menu_colores.add_command(label="Eliminar Colores", command=broker.EliminarColor)
    menu_colores.add_separator()
    menu_colores.add_command(label="Dron a Rojo",      foreground="White",  background="red",
                              command=lambda: dron._IniciarThreadParaPruebas(dron.Enviar, (broker.users["red"]["lat"],    broker.users["red"]["long"])))
    menu_colores.add_command(label="Dron a Amarillo",  foreground="Black",  background="yellow",
                              command=lambda: dron._IniciarThreadParaPruebas(dron.Enviar, (broker.users["yellow"]["lat"], broker.users["yellow"]["long"])))
    menu_colores.add_command(label="Dron a Azul",      foreground="White",  background="blue",
                              command=lambda: dron._IniciarThreadParaPruebas(dron.Enviar, (broker.users["blue"]["lat"],   broker.users["blue"]["long"])))
    menu_colores.add_command(label="Dron a Verde",     foreground="White",  background="green",
                              command=lambda: dron._IniciarThreadParaPruebas(dron.Enviar, (broker.users["green"]["lat"],  broker.users["green"]["long"])))
    menu_colores.add_separator()
    menu_colores.add_command(label="Movimiento",  command=lambda: dron._IniciarThreadParaPruebas(dron.MovimientoPrueba))
    menu_colores.add_command(label="Recolocar",   command=lambda: dron._IniciarThreadParaPruebas(dron.recolocarDronX))
    barra_menu.add_cascade(label="GameTest", menu=menu_colores)
    root.config(menu=barra_menu)

    show_camera()
    show_map()

    return root


# =========================
# ENTRY POINT
# =========================

if __name__ == "__main__":
    config = load_config()
    camera = CameraController(config)
    broker = MQTTController()
    dron   = DroneController(camera)
    random_game = Random(dron, broker, camera)
    quiz   = Quiz(dron, broker, camera)
    root   = Ventana(dron, broker, camera)
    root.mainloop()

    print("Parando Dron...")
    dron.disconnect()