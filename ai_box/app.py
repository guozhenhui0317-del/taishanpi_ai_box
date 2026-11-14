"""! @brief Menu, buttons and application lifecycle for the Taishanpi AI Box."""

from contextlib import ExitStack
import threading
import time
import traceback

from .voice import VoiceAssistant, log
from .weather import Forecast, forecast_text


MAIN_MENU = ("AI助手", "天气")


class Application:
    """! @brief Own menu state and coordinate the button, display and voice tasks."""

    def __init__(self, screen, buttons, rotate=None, network=None):
        """! @brief Initialize the application with its hardware interfaces.
        @param screen Display interface used for menus and messages.
        @param buttons GPIO inputs ordered left, center, and right.
        @param rotate Optional callback that switches the display orientation.
        @param network Optional touch-operated network settings panel.
        """
        self.screen = screen
        self.buttons = buttons
        self.rotate = rotate
        self.main_menu = MAIN_MENU + ("小智联网",)
        self.network = network
        if network:
            self.main_menu += ("网络设置",)
        if rotate:
            self.main_menu += ("旋转屏幕",)
        self.index = 0
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
        self._error_visible = False
        self._forecast = Forecast()
        self._forecast_text = "成都天气获取中…"
        self._forecast_next = 0
        self._forecast_thread = None

    def move(self, delta):
        """! @brief Move left/right in the menu, leaving the weather page if open.
        @param delta Signed change in the selected menu index.
        """
        with self._lock:
            if self._voice_running.is_set():
                return
            self.weather = False
            self._error_visible = False
            self.index = max(0, min(len(self.main_menu) - 1, self.index + delta))
            self.dirty = True

    def select(self, index=None, touch=False):
        """! @brief Open a selected app, or return from an active page.
        @param index App tile index, or None for the selected hardware-button item.
        @param touch True when invoked by a screen tap rather than a hardware button.
        """
        with self._lock:
            if self._voice_running.is_set():
                self._voice_stop.set()
            elif self.weather:
                self.weather = False
            elif self._error_visible:
                self._error_visible = False
            elif touch and index is None:
                return
            else:
                if index is not None:
                    if not 0 <= index < len(self.main_menu):
                        return
                    self.index = index
                self._open_selected()
            self.dirty = not self._error_visible

    def _open_selected(self):
        """! @brief Open the selected app while the application lock is held."""
        if self.main_menu[self.index] in ("AI助手", "小智联网"):
            mode = self.main_menu[self.index]
            self.screen.set_voice_mode(True)
            self.screen.text("语音助手启动中，请稍候")
            self._voice_stop.clear()
            self._voice_running.set()
            self._voice_thread = threading.Thread(target=self._run_voice, args=(mode,), daemon=True)
            try:
                self._voice_thread.start()
            except Exception:
                self._voice_thread = None
                self._voice_running.clear()
                self.screen.set_voice_mode(False)
                raise
        elif self.index == 1:
            self.weather = True
        elif self.main_menu[self.index] == "网络设置":
            self.network.open()
        else:
            try:
                self.rotate()
            except OSError as error:
                print("屏幕方向保存失败: {}".format(error))
                self.screen.text("屏幕方向保存失败\n点击屏幕返回")
                self._error_visible = True

    def handle_voice_command(self, text):
        """! @brief Answer online weather commands without invoking the language model.
        @param text Recognized speech to inspect for a hardware command.
        @return True if handled locally, or False if the text should go to chat.
        """
        words = text.replace(" ", "")
        if any(word in words for word in ("室内", "传感器")):
            return False
        if any(word in words for word in ("天气", "下雨", "温度", "湿度")):
            self.screen.text("正在查询成都天气…")
            reply = forecast_text(self._forecast.get(), tomorrow="明天" in words)
            if self._voice_stop.is_set():
                return True
        else:
            return False
        log("天气查询结果：{}".format(reply.replace("\n", "，")))
        self.screen.text("识别：{}\n{}".format(text, reply))
        self._voice.speak(reply)
        return True

    def _update_forecast(self):
        """! @brief Refresh the weather page without blocking touch navigation."""
        data = self._forecast.get()
        text = forecast_text(data)
        with self._lock:
            self._forecast_text = text
            self._forecast_next = time.monotonic() + (60 if data is not None else 15)
            if self.weather and not self._voice_running.is_set():
                self.dirty = True

    def _start_forecast(self):
        """! @brief Start at most one background weather refresh at a time."""
        with self._lock:
            if time.monotonic() < self._forecast_next or (
                    self._forecast_thread is not None and self._forecast_thread.is_alive()):
                return
            self._forecast_next = time.monotonic() + 60
            self._forecast_thread = threading.Thread(target=self._update_forecast, daemon=True)
            self._forecast_thread.start()

    def _run_voice(self, mode="AI助手"):
        """! @brief Load AI on demand and restore the menu when the session ends."""
        error_message = None
        log("语音助手启动")
        try:
            with ExitStack() as cleanup:
                if mode == "小智联网":
                    from .xiaozhi import XiaozhiAssistant
                    self._voice = XiaozhiAssistant(self.screen)
                else:
                    self._voice = VoiceAssistant(self.screen)
                cleanup.callback(self._voice.close)
                self._voice.run(self._voice_stop, self.handle_voice_command)
        except Exception as error:
            error_message = "语音助手出错：{}\n点击屏幕返回".format(error)
            log("语音助手出错：{}: {}".format(type(error).__name__, error))
            traceback.print_exc()
        finally:
            log("语音助手退出")
            self._voice = None
            with self._lock:
                self._voice_running.clear()
                self.screen.set_voice_mode(False)
                if error_message:
                    self.screen.text(error_message)
                    self._error_visible = True
                    self.dirty = False
                else:
                    self.dirty = True

    def _poll_buttons(self):
        """! @brief Detect debounced rising edges independently of weather and AI work."""
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
        """! @brief Refresh a changed menu or sample the weather page every two seconds."""
        with self._lock:
            if self._voice_running.is_set() or (self.network and self.network.active):
                return
            weather, dirty = self.weather, self.dirty
            items, index = self.main_menu, self.index
            self.dirty = False
        if weather:
            if not dirty and time.monotonic() - self._last_sample < 2:
                return
            self._start_forecast()
            text = self._forecast_text
            self._last_sample = time.monotonic()
        elif not dirty:
            return
        with self._lock:
            current_items, current_index = self.main_menu, self.index
            if self._voice_running.is_set() or (self.network and self.network.active) or (weather, items, index) != (
                    self.weather, current_items, current_index):
                return
            if weather:
                self.screen.weather(text)
            else:
                self.screen.menu(items, index)

    def refresh_menu(self):
        """! @brief Redraw the menu after a touch-operated settings panel closes."""
        with self._lock:
            self.dirty = True

    def run(self):
        """! @brief Poll buttons and render views until interrupted or a GPIO read fails."""
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
        """! @brief Stop and join workers before their hardware resources are released."""
        self._stop.set()
        if self._button_thread is not None and self._button_thread.ident is not None:
            self._button_thread.join()
        self._voice_stop.set()
        if self._voice_thread is not None and self._voice_thread.ident is not None:
            self._voice_thread.join()
