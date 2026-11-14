"""! @brief XiaoZhi cloud voice sessions for the MIPI touchscreen."""

import audioop
import ctypes
import ctypes.util
import json
from pathlib import Path
import queue
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .voice import log


OTA_URL = "https://api.tenclass.net/xiaozhi/ota/"
CLIENT_ID = Path("/var/lib/ai-box/xiaozhi-client-id")


def identity():
    """! @brief Read the Wi-Fi MAC and retain one random client ID across restarts.
    @return Device MAC and client UUID used for official service activation.
    """
    mac = Path("/sys/class/net/wlan0/address").read_text().strip().lower()
    try:
        client = str(uuid.UUID(CLIENT_ID.read_text().strip()))
    except FileNotFoundError:
        CLIENT_ID.parent.mkdir(parents=True, exist_ok=True)
        client = str(uuid.uuid4())
        CLIENT_ID.write_text(client + "\n")
        CLIENT_ID.chmod(0o600)
    return mac, client


def post_ota(path, headers, payload):
    """! @brief Submit a JSON configuration or activation request.
    @param path Suffix of the official OTA URL.
    @param headers Device identity headers.
    @param payload JSON object to send.
    @return HTTP status and parsed response object.
    """
    request = Request(OTA_URL + path, data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        with urlopen(request, timeout=8) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        if error.code == 202:
            return 202, {}
        raise


def connection_config(screen, stop):
    """! @brief Get official WebSocket settings and wait for any device binding.
    @param screen Display used to show a binding code.
    @param stop Event used to cancel activation.
    @return Connection settings and identity, or None when cancelled.
    """
    mac, client = identity()
    headers = {"Device-Id": mac, "Client-Id": client, "Activation-Version": "1",
               "User-Agent": "ai-box-rk3566/1.0.0", "Accept-Language": "zh-CN",
               "Content-Type": "application/json"}
    payload = {"version": 2, "uuid": client, "mac_address": mac,
               "application": {"name": "ai-box", "version": "1.0.0"},
               "board": {"type": "linux", "name": "rk3566", "mac": mac}}
    while not stop.is_set():
        status, config = post_ota("", headers, payload)
        if status != 200:
            raise OSError("小智服务配置获取失败：{}".format(status))
        activation = config.get("activation")
        if not activation:
            websocket = config.get("websocket") or {}
            if not websocket.get("url"):
                raise OSError("官方服务未提供 WebSocket 接入地址")
            return websocket, mac, client
        code = activation.get("code")
        if not code:
            raise OSError("小智服务没有返回设备激活码")
        screen.text("请访问 xiaozhi.me\n添加设备，输入激活码：\n{}\n点击屏幕退出".format(code))
        log("等待小智设备激活")
        while not stop.is_set():
            try:
                status, _ = post_ota("activate", headers, {})
            except TimeoutError:
                status = 202
            if status == 200:
                break
            if status != 202:
                raise OSError("小智设备激活失败：{}".format(status))
            stop.wait(3)
    return None


class Opus:
    """! @brief Encode microphone PCM and decode received Opus audio."""

    def __init__(self, output_rate):
        """! @brief Initialize mono encoders for 16 kHz input and server output.
        @param output_rate Server playback sample rate.
        """
        name = ctypes.util.find_library("opus")
        if not name:
            raise OSError("缺少 libopus 音频库")
        self.lib = ctypes.CDLL(name)
        self.lib.opus_encoder_create.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
        self.lib.opus_encoder_create.restype = ctypes.c_void_p
        self.lib.opus_decoder_create.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
        self.lib.opus_decoder_create.restype = ctypes.c_void_p
        self.lib.opus_encode.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
        self.lib.opus_decode.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        self.lib.opus_encoder_destroy.argtypes = [ctypes.c_void_p]
        self.lib.opus_decoder_destroy.argtypes = [ctypes.c_void_p]
        error = ctypes.c_int()
        self.encoder = self.lib.opus_encoder_create(16000, 1, 2048, ctypes.byref(error))
        if not self.encoder or error.value:
            raise OSError("Opus 编码器初始化失败：{}".format(error.value))
        self.decoder = self.lib.opus_decoder_create(output_rate, 1, ctypes.byref(error))
        if not self.decoder or error.value:
            self.lib.opus_encoder_destroy(self.encoder)
            raise OSError("Opus 解码器初始化失败：{}".format(error.value))
        self.output_rate = output_rate

    def encode(self, pcm):
        """! @brief Compress one 60 ms mono PCM frame.
        @param pcm 16-bit little-endian input samples.
        @return Encoded Opus packet.
        """
        output = ctypes.create_string_buffer(4000)
        size = self.lib.opus_encode(self.encoder, pcm, 960, output, len(output))
        if size < 0:
            raise OSError("Opus 编码失败：{}".format(size))
        return output.raw[:size]

    def decode(self, packet):
        """! @brief Decode one server Opus packet to 16-bit PCM.
        @param packet Encoded Opus packet.
        @return Decoded mono samples.
        """
        max_samples = self.output_rate * 120 // 1000
        output = ctypes.create_string_buffer(max_samples * 2)
        size = self.lib.opus_decode(self.decoder, packet, len(packet), output, max_samples, 0)
        if size < 0:
            raise OSError("Opus 解码失败：{}".format(size))
        return output.raw[:size * 2]

    def close(self):
        """! @brief Free the native codec state."""
        self.lib.opus_encoder_destroy(self.encoder)
        self.lib.opus_decoder_destroy(self.decoder)


class XiaozhiAssistant:
    """! @brief Run one half-duplex XiaoZhi conversation over secure WebSocket."""

    def __init__(self, screen):
        """! @brief Retain the display without loading any local AI model.
        @param screen Display used for conversation and activation.
        """
        self.screen = screen

    def run(self, stop, handle_command=None):
        """! @brief Connect, stream microphone audio and play server responses.
        @param stop Event used to exit the session.
        @param handle_command Unused; online service handles its own dialogue.
        """
        import pyaudio
        from websockets.sync.client import connect

        config = connection_config(self.screen, stop)
        if config is None or stop.is_set():
            return
        websocket, mac, client = config
        url = websocket["url"]
        if not url.startswith("wss://"):
            raise OSError("小智服务器未提供安全的 WSS 地址")
        token = websocket.get("token", "")
        if token and " " not in token:
            token = "Bearer " + token
        headers = {"Authorization": token, "Protocol-Version": "1", "Device-Id": mac, "Client-Id": client}
        self.screen.text("正在连接小智…")
        with connect(url, additional_headers=headers, open_timeout=10, close_timeout=2,
                     proxy=None, compression=None, max_size=1024 * 1024) as ws:
            ws.send(json.dumps({"type": "hello", "version": 1, "transport": "websocket",
                                "audio_params": {"format": "opus", "sample_rate": 16000,
                                                 "channels": 1, "frame_duration": 60}}))
            hello = json.loads(ws.recv(timeout=10))
            if hello.get("type") != "hello" or hello.get("transport") != "websocket":
                raise OSError("小智服务握手失败")
            params = hello.get("audio_params") or {}
            rate = int(params.get("sample_rate", 24000))
            if rate not in (8000, 12000, 16000, 24000, 48000) or params.get("channels", 1) != 1:
                raise OSError("小智服务返回不支持的音频格式")
            session = hello.get("session_id", "")
            codec = Opus(rate)
            audio = pyaudio.PyAudio()
            input_stream = output_stream = None
            frames = queue.Queue(maxsize=128)
            overflow = []
            listening = False
            try:
                def capture(data, frame_count, time_info, status):
                    """! @brief Buffer microphone frames without blocking the audio callback."""
                    if status & pyaudio.paInputOverflow:
                        overflow.append(True)
                        return None, pyaudio.paAbort
                    if listening:
                        try:
                            frames.put_nowait(data)
                        except queue.Full:
                            overflow.append(True)
                            return None, pyaudio.paAbort
                    return None, pyaudio.paContinue

                try:
                    input_stream = audio.open(format=pyaudio.paInt16, channels=2, rate=16000,
                                              input=True, frames_per_buffer=960, stream_callback=capture)
                    stereo = True
                except OSError:
                    input_stream = audio.open(format=pyaudio.paInt16, channels=1, rate=16000,
                                              input=True, frames_per_buffer=960, stream_callback=capture)
                    stereo = False
                output_stream = audio.open(format=pyaudio.paInt16, channels=1, rate=rate,
                                           output=True, frames_per_buffer=rate * 60 // 1000)

                def start_listening():
                    """! @brief Begin a server-controlled turn after playback."""
                    nonlocal listening
                    while not frames.empty():
                        frames.get_nowait()
                    listening = True
                    ws.send(json.dumps({"session_id": session, "type": "listen", "state": "start", "mode": "auto"}))
                    self.screen.text("小智正在听，请说话\n点击屏幕退出")
                    log("小智正在听")

                start_listening()
                heard, answer = "", ""
                while not stop.is_set():
                    if overflow:
                        raise OSError("麦克风音频缓冲区溢出")
                    if listening:
                        try:
                            data = frames.get_nowait()
                            if stereo:
                                data = audioop.tomono(data, 2, 1, 0)
                            ws.send(codec.encode(data))
                        except queue.Empty:
                            pass
                    try:
                        message = ws.recv(timeout=0.01)
                    except TimeoutError:
                        continue
                    if isinstance(message, bytes):
                        if not listening:
                            output_stream.write(codec.decode(message))
                        continue
                    event = json.loads(message)
                    kind, state = event.get("type"), event.get("state")
                    if kind == "stt":
                        heard = event.get("text", "")
                        log("小智识别：" + heard)
                        self.screen.response(heard, "小智正在回答", "请稍候…")
                    elif kind == "tts" and state == "start":
                        listening = False
                        answer = ""
                    elif kind == "tts" and state == "sentence_start":
                        answer += event.get("text", "")
                        log("小智回复：" + event.get("text", ""))
                        self.screen.response(heard, "小智正在回答", answer)
                    elif kind == "tts" and state == "stop":
                        start_listening()
                    elif kind == "alert":
                        raise OSError(event.get("message", "小智服务出错"))
            finally:
                listening = False
                if input_stream is not None:
                    input_stream.close()
                if output_stream is not None:
                    output_stream.close()
                audio.terminate()
                codec.close()

    def close(self):
        """! @brief Session resources are released when run returns."""
