"""@brief Menu, buttons and application lifecycle for the Taishanpi AI Box."""

from contextlib import ExitStack
import threading
import time

from .hardware.aht30 import AHT30
from .hardware.gpio import GPIO
from .hardware.st7789 import ST7789
from .ui import Screen, load_font
from .voice import VoiceAssistant


MAIN_MENU = ("手电筒", "AI助手", "天气")
LIGHT_MENU = ("开启", "关闭", "返回")


class Application:
    """@brief Own menu state and coordinate the button, display and voice tasks."""

    def __init__(self, screen, sensor, led, buttons):
        self.screen = screen
        self.sensor = sensor
        self.led = led
        self.buttons = buttons
        self.index = 0
        self.light_index = 0
        self.in_light_menu = False
        self.weather = False
        self.dirty = True
        self._last_sample = float("-inf")
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._voice_stop = threading.Event()
        self._voice_running = threading.Event()
        self._button_thread = None
        self._voice_thread = None
        self._voice = None
        self._button_error = None

    def move(self, delta):
        """@brief Move left/right in the menu, leaving the weather page if open."""
        with self._lock:
            if self._voice_running.is_set():
                return
            self.weather = False
            if self.in_light_menu:
                self.light_index = max(0, min(len(LIGHT_MENU) - 1, self.light_index + delta))
            else:
                self.index = max(0, min(len(MAIN_MENU) - 1, self.index + delta))
            self.dirty = True

    def select(self):
        """@brief Handle the center button without measuring the sensor or loading AI."""
        with self._lock:
            if self._voice_running.is_set():
                self._voice_stop.set()
            elif self.in_light_menu:
                if self.light_index == 2:
                    self.in_light_menu = False
                else:
                    self.led.value = self.light_index == 0
            elif self.index == 0:
                self.in_light_menu = True
                self.light_index = 0
            elif self.index == 1:
                self._voice_stop.clear()
                self._voice_running.set()
                self._voice_thread = threading.Thread(target=self._run_voice, daemon=True)
                try:
                    self._voice_thread.start()
                except Exception:
                    self._voice_thread = None
                    self._voice_running.clear()
                    raise
            else:
                self.weather = not self.weather
            self.dirty = True

    def weather_text(self):
        """@brief Format one paired sensor measurement or a visible failure message."""
        try:
            temperature, humidity = self.sensor.read()
            return "温度: {:.1f} C\n湿度: {:.1f} %".format(temperature, humidity)
        except OSError as error:
            print("AHT30: {}".format(error))
            return "温湿度读取失败"

    def handle_voice_command(self, text):
        """@brief Handle the original LED/weather commands; return False for chat."""
        if "开启" in text:
            self.led.value = True
            reply = "开灯"
        elif "停止" in text:
            self.led.value = False
            reply = "关灯"
        elif any(word in text for word in ("天气", "温度", "湿度")):
            reply = self.weather_text()
        else:
            return False
        self.screen.text(reply)
        self._voice.speak(reply)
        return True

    def _run_voice(self):
        """@brief Load AI on demand and restore the menu when the session ends."""
        try:
            with ExitStack() as cleanup:
                self._voice = VoiceAssistant(self.screen)
                cleanup.callback(self._voice.close)
                self._voice.run(self._voice_stop, self.handle_voice_command)
        except Exception as error:
            print("语音助手: {}".format(error))
        finally:
            self._voice = None
            with self._lock:
                self._voice_running.clear()
                self.dirty = True

    def _poll_buttons(self):
        """@brief Detect debounced rising edges independently of sensor and AI work."""
        previous = [False] * len(self.buttons)
        last_action = float("-inf")
        try:
            while not self._stop.is_set():
                for index, button in enumerate(self.buttons):
                    pressed = button.value
                    now = time.monotonic()
                    if pressed and not previous[index] and now - last_action >= 0.05:
                        if index == 1:
                            self.select()
                        else:
                            self.move(-1 if index == 0 else 1)
                        last_action = now
                    previous[index] = pressed
                self._stop.wait(0.01)
        except Exception as error:
            self._button_error = error
            self._stop.set()

    def render(self):
        """@brief Refresh a changed menu or sample the weather page every two seconds."""
        with self._lock:
            if self._voice_running.is_set():
                return
            weather, dirty = self.weather, self.dirty
            items = LIGHT_MENU if self.in_light_menu else MAIN_MENU
            index = self.light_index if self.in_light_menu else self.index
            self.dirty = False
        if weather:
            if not dirty and time.monotonic() - self._last_sample < 2:
                return
            text = self.weather_text()
            self._last_sample = time.monotonic()
        elif not dirty:
            return
        with self._lock:
            current_items = LIGHT_MENU if self.in_light_menu else MAIN_MENU
            current_index = self.light_index if self.in_light_menu else self.index
            if self._voice_running.is_set() or (weather, items, index) != (
                    self.weather, current_items, current_index):
                return
            if weather:
                self.screen.text(text)
            else:
                self.screen.menu(items, index)

    def run(self):
        """@brief Poll buttons and render views until interrupted or a GPIO read fails."""
        self._button_thread = threading.Thread(target=self._poll_buttons, daemon=True)
        self._button_thread.start()
        try:
            while not self._stop.is_set():
                self.render()
                self._stop.wait(0.1)
            if self._button_error is not None:
                raise self._button_error
        finally:
            self.close()

    def close(self):
        """@brief Stop and join workers before their hardware resources are released."""
        self._stop.set()
        if self._button_thread is not None and self._button_thread.ident is not None:
            self._button_thread.join()
        self._voice_stop.set()
        if self._voice_thread is not None and self._voice_thread.ident is not None:
            self._voice_thread.join()


def main(voice_only=False):
    """@brief Open the required hardware once and release it even on startup failure."""
    font = load_font()
    with ExitStack() as cleanup:
        display = ST7789()
        cleanup.callback(display.close)
        screen = Screen(display, font)
        if voice_only:
            stop = threading.Event()
            voice = VoiceAssistant(screen)
            cleanup.callback(voice.close)
            try:
                voice.run(stop)
            finally:
                stop.set()
        else:
            sensor = AHT30()
            cleanup.callback(sensor.close)
            led = GPIO(0, 15, initial=False)
            cleanup.callback(led.close)
            cleanup.callback(setattr, led, "value", False)
            buttons = []
            for offset in (1, 2, 3):
                button = GPIO(3, offset)
                cleanup.callback(button.close)
                buttons.append(button)
            app = Application(screen, sensor, led, buttons)
            cleanup.callback(app.close)
            app.run()
