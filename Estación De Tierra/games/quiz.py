import random
import threading
import os
import json
import base64
import io
import numpy as np
from pydub import AudioSegment
import time
import tkinter as tk

# Parámetros
fs = 16000
duracion = 5

PRERESPUESTA_1 = "He entendido esto: "
PRERESPUESTA_2 = "¿Es correcto?"
PRELUDIO = ""
PREGUNTA_RESPUEST = {
    "preg1": {"Pregunta": "¿Cual es la capital de Francia?", "Respuesta": ["París", "Paris"]},
    "preg2": {"Pregunta": "¿Cuál es la capital de España?", "Respuesta": ["Madrid"]},
    "preg3": {"Pregunta": "¿Cuál es el planeta más grande del sistema solar?", "Respuesta": ["Júpiter"]},
    "preg4": {"Pregunta": "¿Quién escribió Don Quijote de la Mancha?", "Respuesta": ["Cervantes"]},
    "preg5": {"Pregunta": "¿Cuál es el océano más grande del mundo?", "Respuesta": ["Pacífico", "Pacifico"]},
    "preg6": {"Pregunta": "¿Cuántos continentes hay en la Tierra?", "Respuesta": ["7","Siete"]},
    "preg7": {"Pregunta": "¿Cuál es el río más largo del mundo?", "Respuesta": ["Amazonas"]},
    "preg8": {"Pregunta": "¿En qué año llegó el hombre a la Luna?", "Respuesta": ["1969"]},

    # Cultura general extra
    "preg9":  {"Pregunta": "¿Cuál es el país más grande del mundo?", "Respuesta": ["Rusia"]},
    "preg10": {"Pregunta": "¿Quién pintó la Mona Lisa?", "Respuesta": ["Leonardo da Vinci", "da Vinci"]},
    "preg11": {"Pregunta": "¿Cuál es el elemento químico con símbolo O?", "Respuesta": ["Oxígeno"]},
    "preg12": {"Pregunta": "¿Cuántos lados tiene un hexágono?", "Respuesta": ["6", "Seis"]},
    "preg13": {"Pregunta": "¿Quién formuló la teoría de la relatividad?", "Respuesta": ["Albert Einstein", "Einstein"]},
    "preg14": {"Pregunta": "¿Cuál es la montaña más alta del mundo?", "Respuesta": ["Everest"]},
    "preg15": {"Pregunta": "¿Cuál es el tratado que puso fin a la Primera Guerra Mundial en 1919?", "Respuesta": ["Versalles"]}
}

ruta_actual = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ruta_IA_Audio_Pregunta_mp3  = os.path.join(ruta_actual, "audios", "IAAudioPreg.mp3")
ruta_User_Audio_wav          = os.path.join(ruta_actual, "audios", "UserAudio.wav")
ruta_IA_Audio_Respuesta_mp3  = os.path.join(ruta_actual, "audios", "IAAudioResp.mp3")


# Paleta compartida con el resto de la estación de tierra para que el panel
# del juego no desentone visualmente. Si la estación de tierra cambia su
# paleta, basta actualizar estas constantes aquí.
PANEL_BG = "#e8e8e8"
TEXT_CLR = "#1a1a1a"
SUBTEXT  = "#555555"


class Quiz:

    def __init__(self, dron, broker,camera):
        self.dron = dron
        self.broker = broker
        self.camera = camera
        self.random = None
        self.dron2user = None
        self.sendcolor = "Rnd"
        self.usuarios_pendientes = []
        self.preguntas_pendientes = []
        self.partidas = 3

        # Referencias a los labels del UI (creados por construir_panel)
        self.game_label     = None
        self.partidas_label = None
        self.timer_label    = None
        self.jugador_label  = None
        self.pregunta_label = None
        self.respuesta_label = None
        self.scores_label   = None
        self.leader_label   = None
        self.root           = None

        self.TimerEnd = False

    # ─────────────────────────────────────────────────────────────────────────
    # Ciclo de vida (llamado desde la estación de tierra al cerrar la app)
    # ─────────────────────────────────────────────────────────────────────────

    def detener(self):
        """
        Punto único de cierre del juego. La estación de tierra solo llama a
        este método al cerrar la aplicación; Quiz decide qué limpiar (en este
        caso, detener cualquier timer en marcha).
        """
        try:
            self.TimerEnd = True
            time.sleep(1)  # Pequeña espera para asegurar que el timer se detenga antes de reiniciar el estado
            self.TimerEnd = False 
        except Exception as e:
            print(f"Error en detener: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # Construcción del panel de UI propio del juego
    # ─────────────────────────────────────────────────────────────────────────

    def construir_panel(self, parent, root=None):
        """
        Construye dentro de `parent` (un LabelFrame "Juego" ya creado por la
        estación de tierra) todos los widgets que este juego necesita:
        estado, contador de partidas, timer, jugador seleccionado, pregunta
        actual, última respuesta, puntuaciones, líder y botones de
        Iniciar/Reiniciar. La estación de tierra no conoce ninguno de estos
        nombres ni su disposición interna; solo entrega el contenedor.

        `root` se guarda para poder usar `root.after(...)` desde threads
        (actualizaciones de labels thread-safe).
        """
        self.root = root

        self.game_label = tk.Label(parent, text="SelectMode", bg=PANEL_BG, fg="#cc6600",
                                    font=("Segoe UI", 9, "bold"))
        self.game_label.grid(row=0, column=0, columnspan=2, sticky="ew", padx=4, pady=(0, 4))

        # ── partidas ─────────────────────────────────────────────────────────
        tk.Label(parent, text="Partidas restantes:", bg=PANEL_BG, fg=SUBTEXT,
                 font=("Segoe UI", 8)).grid(row=1, column=0, sticky="w", padx=4)
        partidas_frame = tk.Frame(parent, bg=PANEL_BG)
        partidas_frame.grid(row=1, column=1, sticky="ew", padx=4, pady=2)

        self.partidas_label = tk.Label(partidas_frame, text=str(self.partidas), bg=PANEL_BG, fg="#1a6faf",
                                        font=("Segoe UI", 10, "bold"))
        self.partidas_label.pack(side="left", padx=4)

        tk.Button(partidas_frame, text="−", bg="#cccccc", fg="#1a1a1a", font=("Segoe UI", 9, "bold"),
                  relief="flat", padx=4, command=self.decrementar_partidas
                  ).pack(side="left", padx=1)
        tk.Button(partidas_frame, text="+", bg="#cccccc", fg="#1a1a1a", font=("Segoe UI", 9, "bold"),
                  relief="flat", padx=4, command=self.incrementar_partidas
                  ).pack(side="left", padx=1)

        # ── timer ────────────────────────────────────────────────────────────
        tk.Label(parent, text="Tiempo restante:", bg=PANEL_BG, fg=SUBTEXT,
                 font=("Segoe UI", 8)).grid(row=2, column=0, sticky="w", padx=4)
        self.timer_label = tk.Label(parent, text="--", bg=PANEL_BG, fg="#cc2200",
                                     font=("Segoe UI", 12, "bold"))
        self.timer_label.grid(row=2, column=1, sticky="ew", padx=4, pady=2)

        # ── jugador seleccionado ─────────────────────────────────────────────
        tk.Label(parent, text="Jugador actual:", bg=PANEL_BG, fg=SUBTEXT,
                 font=("Segoe UI", 8)).grid(row=3, column=0, sticky="w", padx=4)
        self.jugador_label = tk.Label(parent, text="--", bg=PANEL_BG, fg="#1a1a1a",
                                       font=("Segoe UI", 9, "bold"))
        self.jugador_label.grid(row=3, column=1, sticky="ew", padx=4, pady=2)

        # ── pregunta actual ──────────────────────────────────────────────────
        tk.Label(parent, text="Pregunta:", bg=PANEL_BG, fg=SUBTEXT,
                 font=("Segoe UI", 8)).grid(row=4, column=0, columnspan=2, sticky="w", padx=4)
        self.pregunta_label = tk.Label(parent, text="--", bg=PANEL_BG, fg="#1a1a1a",
                                        font=("Segoe UI", 8), wraplength=180, justify="left")
        self.pregunta_label.grid(row=5, column=0, columnspan=2, sticky="ew", padx=4, pady=(0, 2))

        # ── última respuesta recibida ────────────────────────────────────────
        tk.Label(parent, text="Respuesta recibida:", bg=PANEL_BG, fg=SUBTEXT,
                 font=("Segoe UI", 8)).grid(row=6, column=0, columnspan=2, sticky="w", padx=4)
        self.respuesta_label = tk.Label(parent, text="--", bg=PANEL_BG, fg="#1a1a1a",
                                         font=("Segoe UI", 8), wraplength=180, justify="left")
        self.respuesta_label.grid(row=7, column=0, columnspan=2, sticky="ew", padx=4, pady=(0, 4))

        # ── puntuaciones ─────────────────────────────────────────────────────
        tk.Label(parent, text="Puntuaciones:", bg=PANEL_BG, fg=SUBTEXT,
                 font=("Segoe UI", 8, "bold")).grid(row=8, column=0, columnspan=2, sticky="w", padx=4)
        scores_frame = tk.Frame(parent, bg=PANEL_BG)
        scores_frame.grid(row=9, column=0, columnspan=2, sticky="ew", padx=4)
        self.scores_label = tk.Label(scores_frame, text="Aguardando inicio…", bg=PANEL_BG, fg=SUBTEXT,
                                      font=("Segoe UI", 8), justify="left")
        self.scores_label.pack(fill="both", expand=True)

        # ── líder ────────────────────────────────────────────────────────────
        tk.Label(parent, text="Liderando:", bg=PANEL_BG, fg=SUBTEXT,
                 font=("Segoe UI", 8)).grid(row=10, column=0, sticky="w", padx=4)
        self.leader_label = tk.Label(parent, text="--", bg=PANEL_BG, fg="#1a7a3c",
                                      font=("Segoe UI", 10, "bold"))
        self.leader_label.grid(row=10, column=1, sticky="ew", padx=4, pady=2)

        # ── botones Iniciar / Reiniciar ──────────────────────────────────────
        game_btn_row = tk.Frame(parent, bg=PANEL_BG)
        game_btn_row.grid(row=11, column=0, columnspan=2, sticky="ew", padx=4, pady=(4, 2))
        tk.Button(game_btn_row, text="▶  Iniciar", bg="#27ae60", fg="white",
                  font=("Segoe UI", 9, "bold"), relief="flat", padx=6, pady=4,
                  cursor="hand2", command=self.broker.IniciarJuego
                  ).pack(side="left", expand=True, fill="x", padx=(0, 2))
        tk.Button(game_btn_row, text="↺  Reiniciar", bg="#c0392b", fg="white",
                  font=("Segoe UI", 9, "bold"), relief="flat", padx=6, pady=4,
                  cursor="hand2", command=self.reiniciar_juego
                  ).pack(side="left", expand=True, fill="x")

        self.actualizar_partidas_label()
        self.actualizar_scores_label()

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers de UI (thread-safe)
    # ─────────────────────────────────────────────────────────────────────────

    def _app_is_closing(self):
        """
        Devuelve True si la aplicación Tkinter está en proceso de cierre.
        Importa el flag del módulo principal en tiempo de ejecución para
        evitar dependencias circulares en la importación.
        """
        try:
            import __main__
            return getattr(__main__, '_app_closing', False)
        except Exception:
            return False

    def _actualizar_label_seguro(self, label, text, fg=None):
        """Actualiza un label de forma thread-safe. No hace nada si la app está cerrando."""
        if self._app_is_closing():
            return

        def update():
            # Segunda comprobación dentro del callback, por si el flag cambió
            # entre que se programó y se ejecutó.
            if self._app_is_closing():
                return
            if label:
                try:
                    if fg:
                        label.config(text=text, fg=fg)
                    else:
                        label.config(text=text)
                except Exception as e:
                    print(f"Error actualizando label: {e}")

        try:
            if self.root:
                self.root.after(0, update)
            else:
                update()
        except Exception as e:
            print(f"Error en _actualizar_label_seguro: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # Gestión de partidas
    # ─────────────────────────────────────────────────────────────────────────

    def actualizar_partidas_label(self):
        try:
            self._actualizar_label_seguro(self.partidas_label, str(self.partidas))
        except Exception as e:
            print(f"Error en actualizar_partidas_label: {e}")

    def decrementar_partidas(self):
        try:
            if self.partidas > 0:
                self.partidas -= 1
                self.actualizar_partidas_label()
                print(f"Partidas reducidas a: {self.partidas}")
        except Exception as e:
            print(f"Error en decrementar_partidas: {e}")

    def incrementar_partidas(self):
        try:
            self.partidas += 1
            self.actualizar_partidas_label()
            print(f"Partidas aumentadas a: {self.partidas}")
        except Exception as e:
            print(f"Error en incrementar_partidas: {e}")

    def reiniciar_juego(self):
        print("Reiniciando juego...")
        try:
            self.partidas = 3
            self.actualizar_partidas_label()

            for color in self.broker.users:
                self.broker.users[color]["puntos"] = 0

            # Detener el timer si está corriendo
            self.TimerEnd = True
            time.sleep(1)  # Pequeña espera para asegurar que el timer se detenga antes de reiniciar el estado
            self.TimerEnd = False 
            

            self.actualizar_game_state("SelectMode")
            self.actualizar_scores_label()
            self.actualizar_leader_label()
            self._actualizar_label_seguro(self.timer_label, "--")
            self._actualizar_label_seguro(self.jugador_label, "--")
            self._actualizar_label_seguro(self.pregunta_label, "--")
            self._actualizar_label_seguro(self.respuesta_label, "--")

            self.broker.ChangeGameState("SelectMode")
            print("Juego reiniciado correctamente")
        except Exception as e:
            print(f"Error en reiniciar_juego: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # Actualización de labels
    # ─────────────────────────────────────────────────────────────────────────

    def actualizar_game_state(self, state):
        try:
            self._actualizar_label_seguro(self.game_label, f"Estado: {state}")
        except Exception as e:
            print(f"Error en actualizar_game_state: {e}")

    def actualizar_timer_label(self, seconds):
        try:
            if seconds > 10:
                color = "green"
            elif seconds > 5:
                color = "orange"
            else:
                color = "red"
            self._actualizar_label_seguro(self.timer_label, f"{seconds}s", fg=color)
        except Exception as e:
            print(f"Error en actualizar_timer_label: {e}")

    def actualizar_scores_label(self):
        try:
            if self.scores_label and self.broker.users:
                scores_text = "\n".join([
                    f"{color}: {data['puntos']} pts"
                    for color, data in sorted(
                        self.broker.users.items(),
                        key=lambda x: x[1]['puntos'],
                        reverse=True
                    )
                ])
                self._actualizar_label_seguro(
                    self.scores_label,
                    scores_text if scores_text else "Sin jugadores"
                )
        except Exception as e:
            print(f"Error en actualizar_scores_label: {e}")

    def actualizar_leader_label(self):
        try:
            if self.leader_label and self.broker.users:
                ganador = max(
                    self.broker.users,
                    key=lambda user: self.broker.users[user]["puntos"]
                )
                puntos = self.broker.users[ganador]["puntos"]
                self._actualizar_label_seguro(self.leader_label, f"{ganador} ({puntos} pts)")
        except Exception as e:
            print(f"Error actualizando líder: {e}")
            self._actualizar_label_seguro(self.leader_label, "--")

    # ─────────────────────────────────────────────────────────────────────────
    # Punto único de entrada para mensajes MQTT relacionados con el juego
    # ─────────────────────────────────────────────────────────────────────────

    def handle_message(self, command, payload):
        """
        Único punto de entrada desde la estación de tierra (broker) para todo
        lo relacionado con el juego. La estación de tierra solo hace routing
        genérico (extrae 'command' y 'payload' del topic/mensaje MQTT) y
        delega aquí; Quiz decide qué hacer y lanza sus propios threads.
        """
        try:
            if command == 'Respuesta':
                # Procesamos Respuesta recibida del dispositivo móvil.
                threading.Thread(target=lambda: self.J5RespuestaRecibida(payload),
                                 daemon=True, name="QuizThread_parte2").start()

            elif command == 'PedirState':
                self.broker.client.publish('demoDash/mobileFlask/GameState', self.broker.GameState)

            elif command == 'PedirDron':
                self.sendcolor = payload
                if self.partidas > 0:
                    self.broker.IniciarJuego()

            elif command == 'PedirFoto':
                threading.Thread(target=lambda: self.J2PedirFoto(),
                                 daemon=True, name="QuizThread_parte2").start()

            elif command == 'PedirPregunta':
                threading.Thread(target=lambda: self.J3PedirPregunta(),
                                 daemon=True, name="QuizThread_parte3").start()
                
            elif command == 'PedirStartTimer':
                threading.Thread(target=lambda: self.J4iniciarTiempo(),
                                 daemon=True, name="QuizThread_parte4").start()

            elif command == 'PedirStopTimer':
                self.TimerEnd = True

            else:
                print(f"handle_message: comando no reconocido '{command}'")

        except Exception as e:
            print(f"Error en handle_message: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # Lógica de juego
    # ─────────────────────────────────────────────────────────────────────────

    def EnviarDron(self):
        print("Iniciando juego random")
        try:
            self.dron.takeoff()
            time.sleep(2)

            if self.sendcolor == "Rnd":
                if not self.usuarios_pendientes:
                    self.usuarios_pendientes = list(self.broker.users.keys())
                    random.shuffle(self.usuarios_pendientes)
                self.dron2user = self.usuarios_pendientes.pop()
            else:
                print("Enviando Dron al usuario con color seleccionado:", self.sendcolor)
                self.dron2user = self.sendcolor

            print(f"Color seleccionado: {self.dron2user}")
            self._actualizar_label_seguro(self.jugador_label, self.dron2user)
            usuario = self.broker.users[self.dron2user]

            try:
                if self.broker.connected:
                    self.broker.client.publish('demoDash/mobileFlask/JuegoEmpieza', self.dron2user)
            except Exception as e:
                print(f"Error publicando JuegoEmpieza: {e}")

            try:
                self.dron.Enviar(usuario["lat"], usuario["long"], alt=2)
                self.dron.recolocarDronX()
                self.broker.client.publish('demoDash/mobileFlask/DronPreparado', self.dron2user)
            except Exception as e:
                print(f"Error controlando el dron: {e}")


        except Exception as e:
            print(f"Error en EnviarDron: {e}")

    def es_respuesta_correcta(self, respuesta_usuario, respuestas_correctas):
        try:
            print(respuesta_usuario," ", respuestas_correctas)
            respuesta_usuario = respuesta_usuario.lower().strip()

            # respuesta ahora es una lista
            for r in respuestas_correctas:
                if r.lower().strip() in respuesta_usuario  :
                    return True

            return False

        except Exception as e:
            print(f"Error en es_respuesta_correcta: {e}")
            return False

    def CreamosPregunta(self):
        try:
            if not self.preguntas_pendientes:
                self.preguntas_pendientes = list(range(1, len(PREGUNTA_RESPUEST) + 1))
                random.shuffle(self.preguntas_pendientes)

            self.random = self.preguntas_pendientes.pop()
            print(f"Pregunta {self.random}: {PREGUNTA_RESPUEST[f'preg{self.random}']['Pregunta']}")
            return PREGUNTA_RESPUEST[f"preg{self.random}"]["Pregunta"]
        except Exception as e:
            print(f"Error en CreamosPregunta: {e}")
            return None

    def PedirPregunta(self, pregunta):
        try:
            self._actualizar_label_seguro(self.pregunta_label, pregunta)
            self._actualizar_label_seguro(self.respuesta_label, "Esperando respuesta…", fg=SUBTEXT)
            self.broker.EnviarMensaje(
                'demoDash/mobileFlask/Pregunta',
                self.dron2user + "," + pregunta
            )
        except Exception as e:
            print(f"Error en PedirPregunta: {e}")

    def EnviarAudioBrokerRespuesta(self, respuesta):
        try:
            print("Respuesta Escuchada:", respuesta)

            self.partidas -= 1

            try:
                if self.es_respuesta_correcta(respuesta, PREGUNTA_RESPUEST[f"preg{self.random}"]["Respuesta"]):
                    print("¡Respuesta correcta! usuario:", self.dron2user)
                    self.broker.users[self.dron2user]["puntos"] += 1
                    self._actualizar_label_seguro(self.respuesta_label, f"{respuesta}  ✓ Correcta", fg="#1a7a3c")
                    self.broker.EnviarMensaje(
                        'demoDash/mobileFlask/Correcta',
                        self.dron2user + "/" + PREGUNTA_RESPUEST[f"preg{self.random}"]["Respuesta"][0]
                    )
                else:
                    print("Respuesta incorrecta.")
                    self._actualizar_label_seguro(self.respuesta_label, f"{respuesta}  ✗ Incorrecta", fg="#c0392b")
                    self.broker.EnviarMensaje(
                        'demoDash/mobileFlask/Incorrecta',
                        self.dron2user + "/" + PREGUNTA_RESPUEST[f"preg{self.random}"]["Respuesta"][0]
                    )
                self.actualizar_scores_label()
                self.actualizar_leader_label()
            except Exception as e:
                print(f"Error evaluando respuesta: {e}")

            self.actualizar_partidas_label()

            if self.partidas > 0:
                print(f"Quedan {self.partidas} partidas.")
            else:
                try:
                    print("¡Juego terminado! Enviando resultados...")
                    ganador = max(
                        self.broker.users,
                        key=lambda user: self.broker.users[user]["puntos"]
                    )
                    puntos_ganador = self.broker.users[ganador]["puntos"]
                    print(f"Ganador: {ganador} con {puntos_ganador} puntos")

                    scoreboard = {
                        color: data["puntos"]
                        for color, data in self.broker.users.items()
                    }

                    self.actualizar_game_state("Juego Terminado")
                    self.actualizar_leader_label()

                    self.broker.EnviarMensaje(
                        'demoDash/mobileFlask/Resultados',
                        json.dumps({"ganador": ganador, "users": scoreboard})
                    )
                    self.broker.ChangeGameState("SelectMode")
                except Exception as e:
                    print(f"Error enviando resultados finales: {e}")

        except Exception as e:
            print(f"Error en EnviarAudioBrokerRespuesta: {e}")

    def start_timer(self, seconds=30):
        """Inicia un timer en background. Se detiene limpiamente si la app se cierra."""
        def timer_loop():
            try:
                for i in range(seconds):
                    # ── salir si la app está cerrando o si se pidió parar ──
                    if self.TimerEnd or self._app_is_closing():
                        print("Timer detenido. ", self.TimerEnd )
                        self.TimerEnd = False
                        break

                    remaining = seconds - i
                    self.actualizar_timer_label(remaining)

                    try:
                        self.broker.EnviarMensaje(
                            'demoDash/mobileFlask/TimeActulizer',
                            remaining
                        )
                    except Exception as e:
                        print(f"Error enviando tick del timer: {e}")

                    time.sleep(1)

                # Timer terminado de forma natural
                # Comprobar de nuevo antes del envío final
                if self._app_is_closing():
                    return

                self.actualizar_timer_label(0)

                try:
                    self.broker.EnviarMensaje('demoDash/mobileFlask/StopRecording', self.dron2user)
                except Exception as e:
                    print(f"Error enviando StopRecording: {e}")

                print(f"Timer de {seconds}s terminado")
            except Exception as e:
                print(f"Error en timer_loop: {e}")

        try:
            timer_thread = threading.Thread(target=timer_loop, daemon=True, name="TimerThread")
            timer_thread.start()
        except Exception as e:
            print(f"Error iniciando timer thread: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # Flujo principal del juego
    # ─────────────────────────────────────────────────────────────────────────

    def J1IniciarJuego(self):
        try:
            self.actualizar_game_state("En Juego")
            self.actualizar_scores_label()
            self.actualizar_leader_label()
            self.EnviarDron()
            # self.J3PedirPregunta()
        except Exception as e:
            print(f"Error en J1IniciarJuego: {e}")

    def J2PedirFoto(self):
        try:
            img_base64 = self.camera.TomarFoto(self.dron2user)
            if self.broker.connected and img_base64:
                self.broker.client.publish("demoDash/mobileFlask/Foto", self.dron2user + "," + img_base64)
        except Exception as e:
            print(f"Error publicando foto: {e}")

    def J3PedirPregunta(self):
        print("Creamos Pregunta")
        Pregunta = self.CreamosPregunta()
        print("Enviamos la pregunta al usuario...")
        self.PedirPregunta(Pregunta)
        # self.J4iniciarTiempo()

    def J4iniciarTiempo(self):
        print("Iniciamos el temporizador de 15 segundos")
        self.start_timer(15)

    def J5RespuestaRecibida(self, Respuesta):
        try:
            print("Procesando respuesta del usuario...")
            print("Enviamos respuesta al broker: ", Respuesta)
            self.EnviarAudioBrokerRespuesta(Respuesta)
        except Exception as e:
            print(f"Error en J5RespuestaRecibida: {e}")