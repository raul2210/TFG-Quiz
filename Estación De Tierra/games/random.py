import random
import threading

from tkinter import messagebox
import tkinter as tk

# Paleta compartida con el resto de la estación de tierra (misma que usa Quiz)
# para que el panel de este juego no desentone visualmente.
PANEL_BG = "#e8e8e8"
TEXT_CLR = "#1a1a1a"
SUBTEXT  = "#555555"


class Random:

    def __init__(self, dron, broker, camera):
        self.dron = dron
        self.broker = broker
        self.camera = camera

        # Referencias a los labels del UI (creados por construir_panel)
        self.game_label    = None
        self.jugador_label = None
        self.root          = None

    # ─────────────────────────────────────────────────────────────────────────
    # Ciclo de vida (llamado desde la estación de tierra al cambiar de juego
    # o al cerrar la app)
    # ─────────────────────────────────────────────────────────────────────────

    def detener(self):
        """
        Punto único de cierre del juego. Random no mantiene ningún proceso en
        background que deba pararse.
        """
        pass

    # ─────────────────────────────────────────────────────────────────────────
    # Construcción del panel de UI propio del juego
    # ─────────────────────────────────────────────────────────────────────────

    def construir_panel(self, parent, root=None):
        """
        Construye dentro de `parent` (el mismo LabelFrame "Juego" que usa
        Quiz) el panel de este juego: estado, jugador seleccionado y botón
        de Jugar. La estación de tierra no conoce nada de esto; solo entrega
        el contenedor, igual que hace con Quiz.
        """
        self.root = root

        self.game_label = tk.Label(parent, text="Esperando", bg=PANEL_BG, fg="#cc6600",
                                    font=("Segoe UI", 9, "bold"))
        self.game_label.grid(row=0, column=0, columnspan=2, sticky="ew", padx=4, pady=(0, 4))

        tk.Label(parent, text="Jugador seleccionado:", bg=PANEL_BG, fg=SUBTEXT,
                 font=("Segoe UI", 8)).grid(row=1, column=0, sticky="w", padx=4)
        self.jugador_label = tk.Label(parent, text="--", bg=PANEL_BG, fg="#1a1a1a",
                                       font=("Segoe UI", 9, "bold"))
        self.jugador_label.grid(row=1, column=1, sticky="ew", padx=4, pady=2)

        tk.Button(parent, text="▶  Jugar", bg="#27ae60", fg="white",
                  font=("Segoe UI", 9, "bold"), relief="flat", padx=6, pady=4,
                  cursor="hand2", command=self.iniciar_juego
                  ).grid(row=2, column=0, columnspan=2, sticky="ew", padx=4, pady=(4, 2))

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers de UI (thread-safe, mismo patrón que Quiz)
    # ─────────────────────────────────────────────────────────────────────────

    def _actualizar_label_seguro(self, label, text, fg=None):
        def update():
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
    # Lógica de juego
    # ─────────────────────────────────────────────────────────────────────────

    def iniciar_juego(self):
        """Lanza run() en un hilo aparte para no bloquear la UI, igual que
        Quiz hace con broker.IniciarJuego -> J1IniciarJuego."""
        threading.Thread(target=self.run, daemon=True, name="RandomThread").start()

    def run(self):
        print("Iniciando juego random")

        if not self.dron.connected:
            return messagebox.showinfo("showinfo", "Por favor, conecta el dron antes de iniciar el juego.")
        if not self.broker.connected:
            return messagebox.showinfo("showinfo", "Por favor, conecta el broker antes de iniciar el juego.")
        if not self.broker.users:
            return messagebox.showinfo("showinfo", "Por favor, introduce a los jugadores.")

        self._actualizar_label_seguro(self.game_label, "En Juego", fg="#cc6600")

        color_aleatorio = random.choice(list(self.broker.users.keys()))
        print(f"Color aleatorio seleccionado: {color_aleatorio}")
        self._actualizar_label_seguro(self.jugador_label, color_aleatorio)
        usuario = self.broker.users[color_aleatorio]

        # comprobar que el usuario tiene coordenadas
        if usuario.get('lat') is None or usuario.get('long') is None:
            self._actualizar_label_seguro(self.game_label, "Esperando", fg="#cc6600")
            return messagebox.showerror("Error", "El jugador seleccionado no tiene coordenadas.")

        # ── mensaje al móvil: el juego ha empezado con este jugador ─────────
        try:
            if self.broker.connected:
                self.broker.client.publish('demoDash/mobileFlask/juegoEmpezando', color_aleatorio)
        except Exception as e:
            print(f"Error publicando juegoEmpezando: {e}")

        print(f"Enviar dron a: lat={usuario['lat']}, lon={usuario['long']}")
        self.dron.Enviar(usuario["lat"], usuario["long"], alt=2)
        self.dron.recolocarDronX()

        # ── foto: antes llamaba a self.dron.TomarFoto, que no existe en
        # DroneController (TomarFoto vive en CameraController) ──────────────
        img_base64 = self.camera.TomarFoto(color_aleatorio)

        # ── mensaje al móvil: foto tomada, igual que hace Quiz en J2EnviarFoto ─
        try:
            if self.broker.connected and img_base64:
                self.broker.client.publish("demoDash/mobileFlask/FotoTomadaFoto", color_aleatorio + "," + img_base64)
        except Exception as e:
            print(f"Error publicando foto: {e}")

        self._actualizar_label_seguro(self.game_label, "Finalizado", fg="#1a7a3c")
        print("Juego random finalizado")