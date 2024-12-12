from kivy.app import App
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.button import Button
from kivy.uix.boxlayout import BoxLayout
from kivy.clock import Clock
from kivy.graphics.texture import Texture
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label

import cv2
import numpy as np
from pyzbar.pyzbar import decode
import base64
import time
import requests


key = 42
SERVER_URL = "http://192.168.1.102:5000"
vsechny = []
vpustene = []

def load_lists_from_server():
    try:
        response = requests.get(f"{SERVER_URL}/get_lists")
        if response.status_code == 200:
            data = response.json()
            global vsechny, vpustene
            vsechny = data.get("vsechny", [])
            vpustene = data.get("vpustene", [])
    except Exception as e:
        pass

def save_list_to_server(list_name, values):
    try:
        requests.post(f"{SERVER_URL}/update_list", json={"list_name": list_name, "values": values})
    except Exception as e:
        pass

# Jednoduché dešifrování čísla (XOR)
def simple_decrypt(encrypted_number, key):
    try:
        decoded = base64.urlsafe_b64decode(encrypted_number.encode()).decode()
        decrypted = ''.join(chr(ord(c) ^ key) for c in decoded)
        return decrypted
    except Exception as e:
        return None
    

class InitializationScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.layout = BoxLayout(orientation="vertical", padding=10, spacing=10)
        self.label = Label(text="Připojte se k síti a spusťte server...", font_size=24)
        self.layout.add_widget(self.label)
        self.add_widget(self.layout)
        Clock.schedule_interval(self.try_load_lists, 10)  # Opakovaný pokus každých 10 vteřin

    def try_load_lists(self, dt):
        global vsechny, vpustene
        try:
            response = requests.get(f"{SERVER_URL}/get_lists")
            if response.status_code == 200:
                data = response.json()
                vsechny = data.get("vsechny", [])
                vpustene = data.get("vpustene", [])
                self.manager.current = "camera"  # Přepnutí na kamerovou obrazovku
                Clock.unschedule(self.try_load_lists)  # Zastavení opakovaných pokusů
            else:
                self.label.text = "Server nedostupný. Zkontrolujte připojení."
        except Exception as e:
            self.label.text = "Nelze načíst seznamy lístků. Zkuste znovu."


# Třída CameraScreen pro kameru (z původní třídy CameraApp)
class CameraScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.img_widget = Image()
        self.add_widget(self.img_widget)
        self.capture = cv2.VideoCapture(0)
        self.last_bboxes = []
        self.stable_start_time = None
        self.detection_active = True
        Clock.schedule_interval(self.update, 1.0 / 30.0)

    def is_bbox_stable(self, last_bboxes, threshold=40):
        if len(last_bboxes) < 3:
            return False
        for i in range(1, len(last_bboxes)):
            diff = np.abs(last_bboxes[i] - last_bboxes[i - 1])
            if np.any(diff > threshold):
                return False
        return True

    def process_qr_code(self, decrypted_number):
        # Načíst aktuální data ze serveru
        load_lists_from_server()

        if decrypted_number:
            if (int(decrypted_number) in vsechny) and not (int(decrypted_number) in vpustene):
                self.show_message("green", "Lístek vpuštěn", lambda: None)
                self.add_to_vpustene(int(decrypted_number))
            elif not (int(decrypted_number) in vsechny):
                self.show_message("red", "Neplatný QR kód", lambda: None)
            elif (int(decrypted_number) in vpustene):
                self.show_message("red", "QR kód již byl použitý", lambda: None)
        else:
            self.show_message("red", "Neplatný QR kód", lambda: None)

    def add_to_vpustene(self, number):
        vpustene.append(number)
        save_list_to_server("vpustene", vpustene)

    def show_message(self, color, message, callback):
        self.detection_active = False
        layout = BoxLayout(orientation='vertical', padding=10, spacing=10)
        label = Label(text=message, size_hint=(1, 0.8), color=[1, 1, 1, 1])
        button = Button(text="Zpět na detekci", size_hint=(1, 0.2))
        layout.add_widget(label)
        layout.add_widget(button)

        # Nastavení barvy pozadí podle stavu
        if color == "green":
            bg_color = [0, 1, 0, 1]  # Zelená (RGBA)
        elif color == "red":
            bg_color = [1, 0, 0, 1]  # Červená (RGBA)
        else:
            bg_color = [0.5, 0.5, 0.5, 1]  # Výchozí šedá (pro jistotu)

        popup = Popup(
            title="Výsledek QR kódu",
            content=layout,
            size_hint=(0.8, 0.6),
            background_color=bg_color,
        )
        button.bind(on_press=lambda *args: (popup.dismiss(), callback(), self.resume_detection()))
        popup.open()


    def resume_detection(self):
        self.detection_active = True

    def update(self, dt):
        if not self.detection_active:
            return

        ret, frame = self.capture.read()
        if not ret:
            return

        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        qr_detector = cv2.QRCodeDetector()
        decoded_text, bbox, _ = qr_detector.detectAndDecode(frame)

        if bbox is not None:
            bbox = bbox.astype(int)
            self.last_bboxes.append(bbox)
            if len(self.last_bboxes) > 3:
                self.last_bboxes.pop(0)

            if self.is_bbox_stable(self.last_bboxes):
                if self.stable_start_time is None:
                    self.stable_start_time = time.time()
                elif time.time() - self.stable_start_time >= 1.0:
                    decoded_objects = decode(frame)
                    if decoded_objects:
                        for obj in decoded_objects:
                            data = obj.data.decode()
                            encrypted_number = data.split("#")[-1]
                            decrypted_number = simple_decrypt(encrypted_number, key)
                            self.process_qr_code(decrypted_number)
                            self.last_bboxes = []
                            self.stable_start_time = None
                            break
                cv2.polylines(frame, [bbox], isClosed=True, color=(0, 255, 0), thickness=3)
            else:
                self.stable_start_time = None
        else:
            self.last_bboxes = []
            self.stable_start_time = None

        buf = frame.tobytes()
        texture = Texture.create(size=(frame.shape[1], frame.shape[0]), colorfmt='rgb')
        texture.blit_buffer(buf, colorfmt='rgb', bufferfmt='ubyte')
        self.img_widget.texture = texture

    def on_stop(self):
        self.capture.release()


class CameraApp(App):
    def build(self):
        # Vytvoření ScreenManager
        self.sm = ScreenManager()

        # Přidání inicializační obrazovky
        self.init_screen = InitializationScreen(name="init")
        self.sm.add_widget(self.init_screen)

        # Přidání obrazovky kamery
        self.camera_screen = CameraScreen(name="camera")
        self.sm.add_widget(self.camera_screen)

        # Nastavení výchozí obrazovky
        self.sm.current = "init"

        return self.sm
    

if __name__ == '__main__':
    CameraApp().run()
