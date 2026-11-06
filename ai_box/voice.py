"""@brief Synchronous speech recognition, local model replies and Chinese speech."""

from contextlib import ExitStack
import json
import os
import re
import subprocess
import threading
import time


class VoiceAssistant:
    """@brief Share one voice implementation between the menu and voice-only modes."""

    def __init__(self, screen):
        """@brief Load optional AI dependencies only when voice mode is selected."""
        import ollama
        import pyaudio
        import vosk

        self.screen = screen
        self._closed = False
        self._stop_event = threading.Event()
        self._cleanup = ExitStack()
        self._format = pyaudio.paInt16
        model_path = os.environ.get(
            "VOSK_MODEL_PATH", "/home/lckfb/vosk-model-small-cn-0.22"
        )
        model = vosk.Model(model_path)
        self.recognizer = vosk.KaldiRecognizer(model, 16000)
        self.history = [{
            "role": "system",
            "content": "你是嘉立创EDA-小嘉，是一个运行在泰山派上的离线本地大模型语音助手。",
        }]
        try:
            self.client = ollama.Client(timeout=15.0)
            close_client = getattr(self.client, "close", None)
            if close_client is not None:
                self._cleanup.callback(close_client)
            self.audio = pyaudio.PyAudio()
            self._cleanup.callback(self.audio.terminate)
        except BaseException:
            self._cleanup.close()
            raise

    def _stopped(self):
        """@brief Check both caller cancellation and explicit resource closure."""
        return self._closed or self._stop_event.is_set()

    def _listen(self):
        """@brief Recognize one utterance and close its microphone stream on exit."""
        self.recognizer.Reset()
        with ExitStack() as cleanup:
            stream = self.audio.open(
                format=self._format, channels=1, rate=16000,
                input=True, frames_per_buffer=2048,
            )
            cleanup.callback(stream.close)
            cleanup.callback(stream.stop_stream)
            frame, next_frame = 0, 0.0
            while not self._stopped():
                now = time.monotonic()
                if now >= next_frame:
                    self.screen.face(frame % 3)
                    frame += 1
                    next_frame = now + 0.2
                data = stream.read(2048, exception_on_overflow=False)
                if self._stopped():
                    break
                if self.recognizer.AcceptWaveform(data):
                    text = json.loads(self.recognizer.Result()).get("text", "").strip()
                    if text:
                        return text
        return ""

    def speak(self, text):
        """@brief Speak Chinese text and stop the child process when cancelled."""
        spoken = re.sub(r"[*#`]", "", text).strip()
        if not spoken or self._stopped():
            return
        process = subprocess.Popen(["espeak-ng", "-v", "zh", spoken])
        try:
            while process.poll() is None and not self._stopped():
                self._stop_event.wait(0.1)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
            process.wait()

    def reply(self, text, stop_event):
        """@brief Display the cumulative streamed answer and release cancelled requests."""
        self._stop_event = stop_event
        if self._stopped():
            return
        self.screen.face(1)
        messages = self.history + [{"role": "user", "content": text}]
        response = self.client.chat(model="qwen2:0.5b", messages=messages, stream=True)
        generated = ""
        try:
            chunks = iter(response)
            while not self._stopped():
                try:
                    chunk = next(chunks)
                except StopIteration:
                    break
                if self._stopped():
                    break
                content = chunk["message"]["content"] or ""
                if content:
                    generated += content
                    self.screen.text(generated)
                    self.speak(content)
        finally:
            close_response = getattr(response, "close", None)
            if close_response is not None:
                close_response()
        if not self._stopped():
            self.history = messages + [{"role": "assistant", "content": generated}]

    def run(self, stop_event, handle_command=None):
        """@brief Listen until cancelled; let the application consume hardware commands."""
        self._stop_event = stop_event
        while not self._stopped():
            text = self._listen()
            if not text or self._stopped():
                continue
            if handle_command is None or not handle_command(text):
                self.reply(text, stop_event)

    def close(self):
        """@brief Release audio and supported client resources once after run returns."""
        if not self._closed:
            self._closed = True
            self._cleanup.close()
