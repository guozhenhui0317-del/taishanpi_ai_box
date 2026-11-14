"""! @brief Synchronous speech recognition, local model replies and Chinese speech."""

from contextlib import ExitStack
import json
import os
from pathlib import Path
import queue
import re
import signal
import subprocess
import threading
import time


MODEL_CARD = Path("/mnt/modelsd")
MAX_HISTORY_TURNS = 2


def log(message):
    """! @brief Print a timestamped diagnostic message without buffering.
    @param message Human-readable diagnostic message.
    """
    print("[{}] {}".format(time.strftime("%Y-%m-%d %H:%M:%S"), message), flush=True)


def check_models(model_name=None):
    """! @brief Require a mounted SD card with the configured AI and speech models.
    @param model_name Ollama model name; defaults to AI_BOX_LLM_MODEL.
    @exception OSError If the card is not mounted or a required model is incomplete.
    """
    if not os.path.ismount(MODEL_CARD):
        raise OSError("请插入并挂载 SD 卡")
    model_name = model_name or os.environ.get("AI_BOX_LLM_MODEL", "qwen2:0.5b")
    if model_name not in ("qwen2:0.5b", "deepseek-r1:1.5b"):
        raise OSError("不支持的 AI 模型：" + model_name)
    models = MODEL_CARD / "ollama-models"
    try:
        manifest = models / "manifests/registry.ollama.ai/library" / model_name.replace(":", "/")
        with manifest.open(encoding="utf-8") as file:
            metadata = json.load(file)
        for entry in [metadata["config"], *metadata["layers"]]:
            digest = entry["digest"]
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
                raise ValueError("invalid model digest")
            blob = models / "blobs" / digest.replace(":", "-")
            if blob.stat().st_size != entry["size"]:
                raise ValueError("invalid model size")
    except (OSError, ValueError, TypeError, KeyError):
        raise OSError("SD 卡中的 AI 模型缺失或不完整") from None
    vosk_model = MODEL_CARD / "vosk-model-small-cn-0.22"
    if not (vosk_model / "am/final.mdl").is_file():
        raise OSError("SD 卡中的语音识别模型缺失")
    return vosk_model


def split_reasoning(text):
    """! @brief Separate streamed reasoning tags without showing partial tag fragments.
    @param text Accumulated model output.
    @return Thinking text and final-answer text, without the enclosing tags.
    """
    text = text.lstrip()
    if "<think>".startswith(text):
        return "", ""
    if not text.startswith("<think>"):
        return "", text
    thinking, separator, answer = text[len("<think>"):].partition("</think>")
    if not separator:
        for length in range(1, len("</think>")):
            if thinking.endswith("</think>"[:length]):
                thinking = thinking[:-length]
                break
    return thinking.strip(), answer.lstrip()


def split_speech(text, final=False):
    """! @brief Split streamed answer text into short, ordered speech segments.
    @param text Unspoken answer text accumulated so far.
    @param final Flush any remaining text when the model finishes.
    @return Pair of complete speech segments and unconsumed text.
    """
    segments = []
    while text:
        end = None
        for index, character in enumerate(text):
            if character in "。！？!?；;\n" or (character in "，," and index >= 7):
                end = index + 1
                break
        if end is None and len(text) >= 48:
            end = text.rfind(" ", 0, 48)
            if end < 24:
                end = 48
        if end is None:
            if not final:
                break
            end = len(text)
        segment, text = text[:end].strip(), text[end:]
        if re.search(r"\w", segment):
            segments.append(segment)
    return segments, text


class VoiceAssistant:
    """! @brief Share one voice implementation between the menu and voice-only modes."""

    def __init__(self, screen):
        """! @brief Load optional AI dependencies only when voice mode is selected.
        @param screen Display interface used for the face and replies.
        """
        log("正在检查 SD 卡和模型")
        self.model_name = os.environ.get("AI_BOX_LLM_MODEL", "qwen2:0.5b")
        model_path = check_models(self.model_name)
        import ollama
        import pyaudio
        import vosk

        self.screen = screen
        self._closed = False
        self._stop_event = threading.Event()
        self._speech_abort = None
        self._cleanup = ExitStack()
        self._format = pyaudio.paInt16
        log("正在加载语音识别模型：{}".format(model_path))
        started = time.monotonic()
        model = vosk.Model(str(model_path))
        log("语音识别模型加载完成，耗时 {:.1f} 秒".format(time.monotonic() - started))
        self.recognizer = vosk.KaldiRecognizer(model, 16000)
        self.history = [{
            "role": "system",
            "content": "你是嘉立创EDA-小嘉，是一个运行在泰山派上的离线本地大模型语音助手。",
        }]
        try:
            self.client = ollama.Client(timeout=180.0 if self.model_name == "deepseek-r1:1.5b" else 90.0)
            close_client = getattr(self.client, "close", None)
            if close_client is not None:
                self._cleanup.callback(close_client)
            self.audio = pyaudio.PyAudio()
            self._cleanup.callback(self.audio.terminate)
        except BaseException:
            self._cleanup.close()
            raise

    def _stopped(self):
        """! @brief Check both caller cancellation and explicit resource closure.
        @return True if the voice session has been stopped or closed.
        """
        return (self._closed or self._stop_event.is_set() or
                (self._speech_abort is not None and self._speech_abort.is_set()))

    def _listen(self):
        """! @brief Recognize one utterance and close its microphone stream on exit.
        @return Recognized text, or an empty string if cancelled.
        """
        import pyaudio

        self.recognizer.Reset()
        audio_queue = queue.Queue(maxsize=128)
        overflow = threading.Event()

        def capture(data, frame_count, time_info, status):
            """! @brief Buffer microphone audio independently of recognition."""
            if status & pyaudio.paInputOverflow:
                overflow.set()
                return (None, pyaudio.paAbort)
            try:
                audio_queue.put_nowait(data)
            except queue.Full:
                overflow.set()
                return (None, pyaudio.paAbort)
            return (None, pyaudio.paContinue)

        with ExitStack() as cleanup:
            try:
                stream = self.audio.open(
                    format=self._format, channels=2, rate=16000,
                    input=True, frames_per_buffer=2048, stream_callback=capture,
                )
                stereo = True
            except OSError:
                stream = self.audio.open(
                    format=self._format, channels=1, rate=16000,
                    input=True, frames_per_buffer=2048, stream_callback=capture,
                )
                stereo = False
            cleanup.callback(stream.close)
            cleanup.callback(stream.stop_stream)
            log("麦克风已打开（{}），等待说话".format("左声道" if stereo else "单声道"))
            started = time.monotonic()
            frame, next_frame = 0, 0.0
            while not self._stopped():
                now = time.monotonic()
                if now >= next_frame:
                    self.screen.face(frame % 3)
                    frame += 1
                    next_frame = now + 0.2
                if overflow.is_set():
                    raise OSError("麦克风音频缓冲区溢出，识别速度跟不上录音")
                try:
                    data = audio_queue.get(timeout=0.2)
                except queue.Empty:
                    continue
                if self._stopped():
                    break
                if stereo:
                    data = memoryview(data).cast("h")[::2].tobytes()
                recognized = self.recognizer.AcceptWaveform(data)
                if overflow.is_set():
                    raise OSError("麦克风音频缓冲区溢出，识别速度跟不上录音")
                if recognized:
                    text = json.loads(self.recognizer.Result()).get("text", "").strip()
                    if text:
                        log("本轮听音和识别耗时 {:.1f} 秒，待处理音频约 {:.1f} 秒".format(
                            time.monotonic() - started, audio_queue.qsize() * 2048 / 16000))
                        return text
        return ""

    def speak(self, text):
        """! @brief Speak Chinese text and stop the child process when cancelled.
        @param text Text to speak after removing supported formatting characters.
        """
        spoken = re.sub(r"[*#`]", "", text).strip()
        if not spoken or self._stopped():
            return
        if os.environ.get("AI_BOX_SPEECH", "1") == "0":
            log("语音播报已关闭，继续等待说话")
            return
        log("开始语音播报：{}".format(spoken))
        process = subprocess.Popen(["/opt/ai-box/deployment/ai-box-speak", spoken], start_new_session=True)
        try:
            while process.poll() is None and not self._stopped():
                self._stop_event.wait(0.1)
        finally:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                except ProcessLookupError:
                    pass
            returncode = process.wait()
        if returncode and not self._stopped():
            raise OSError("语音合成进程退出，状态码 {}".format(returncode))
        log("语音播报结束")

    def _request_reply(self, messages):
        """! @brief Stream the selected model using the installed Ollama server API.
        @param messages Conversation containing only completed assistant answers.
        @return Closable iterator of streamed response chunks.
        """
        if self.model_name != "deepseek-r1:1.5b":
            return self.client.chat(model=self.model_name, messages=messages, stream=True)
        prompt = "<｜begin▁of▁sentence｜>"
        for message in messages:
            if message["role"] == "system":
                prompt += message["content"]
            elif message["role"] == "user":
                prompt += "<｜User｜>" + message["content"]
            else:
                prompt += "<｜Assistant｜>" + message["content"] + "<｜end▁of▁sentence｜>"
        prompt += "<｜Assistant｜>"
        return self.client.generate(
            model=self.model_name, prompt=prompt, raw=True, stream=True, keep_alive=0,
            options={"num_thread": 4, "num_ctx": 1024, "num_predict": 512},
        )

    def reply(self, text, stop_event):
        """! @brief Display the cumulative streamed answer and release cancelled requests.
        @param text User message to send to the local model.
        @param stop_event Event used to cancel the response.
        """
        self._stop_event = stop_event
        if self._stopped():
            return
        deepseek = self.model_name == "deepseek-r1:1.5b"
        if deepseek:
            self.screen.response(text, "正在思考", "模型加载中，请稍候…")
        else:
            self.screen.text("识别：{}\n正在思考…".format(text))
        if self._stopped():
            return
        log("正在请求模型 " + self.model_name)
        started = time.monotonic()
        messages = self.history + [{"role": "user", "content": text}]
        response = self._request_reply(messages)
        generated, answer = "", ""
        finish_reason = None
        pending, spoken_length = "", 0
        speech_queue = queue.Queue(maxsize=8)
        speech_errors = []
        self._speech_abort = threading.Event()

        def play_segments():
            """! @brief Play completed answer segments in order while the model continues."""
            try:
                while not self._stopped():
                    try:
                        segment = speech_queue.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    if segment is None:
                        return
                    self.speak(segment)
            except Exception as error:
                speech_errors.append(error)
                self._speech_abort.set()

        def enqueue(segments):
            """! @brief Queue speech without blocking cancellation if playback is slower."""
            for segment in segments:
                while not self._stopped():
                    try:
                        speech_queue.put(segment, timeout=0.1)
                        break
                    except queue.Full:
                        continue

        speech_thread = threading.Thread(target=play_segments, daemon=True)
        complete = False
        try:
            speech_thread.start()
            chunks = iter(response)
            while not self._stopped():
                try:
                    chunk = next(chunks)
                except StopIteration:
                    break
                if self._stopped():
                    break
                if deepseek:
                    content = chunk["response"] or ""
                    finish_reason = chunk.get("done_reason") or finish_reason
                else:
                    content = chunk["message"]["content"] or ""
                if content:
                    generated += content
                    if deepseek:
                        thinking, answer = split_reasoning(generated)
                        stage = "正在回答" if answer else "正在思考"
                        self.screen.response(text, stage, answer or thinking or "正在思考…")
                    else:
                        answer = generated
                        self.screen.text("识别：{}\n回答：{}".format(text, answer))
                    pending += answer[spoken_length:]
                    spoken_length = len(answer)
                    segments, pending = split_speech(pending)
                    enqueue(segments)
            if not self._stopped():
                if deepseek:
                    if finish_reason == "length":
                        raise OSError("模型输出达到上限，请简化问题后重试")
                    if not answer.strip():
                        raise OSError("模型没有生成完整回答，请重试")
                    self.screen.response(text, "回答完成", answer)
                log("模型回复（{:.1f} 秒）：{}".format(time.monotonic() - started, answer))
                segments, pending = split_speech(pending, final=True)
                enqueue(segments)
                complete = not self._stopped()
        finally:
            if not complete:
                self._speech_abort.set()
            try:
                close_response = getattr(response, "close", None)
                if close_response is not None:
                    close_response()
            finally:
                if complete:
                    enqueue([None])
                if speech_thread.ident is not None:
                    speech_thread.join()
                self._speech_abort = None
        if speech_errors:
            raise OSError("语音播报失败：{}".format(speech_errors[0])) from speech_errors[0]
        if not self._stopped():
            history = messages + [{"role": "assistant", "content": answer}]
            self.history = [history[0]] + history[1:][-MAX_HISTORY_TURNS * 2:]

    def run(self, stop_event, handle_command=None):
        """! @brief Listen until cancelled; let the application consume hardware commands.
        @param stop_event Event used to cancel the voice session.
        @param handle_command Optional callback returning True for locally handled text.
        """
        self._stop_event = stop_event
        while not self._stopped():
            text = self._listen()
            if not text or self._stopped():
                continue
            log("识别结果：{}".format(text))
            if handle_command is None or not handle_command(text):
                self.reply(text, stop_event)
            else:
                log("已处理本地指令")

    def close(self):
        """! @brief Release audio and supported client resources once after run returns."""
        if not self._closed:
            self._closed = True
            self._cleanup.close()
