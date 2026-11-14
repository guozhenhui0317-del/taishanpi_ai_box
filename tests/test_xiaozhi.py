"""! @brief Check cloud activation, Opus audio and session flow without hardware."""

import json
import sys
import threading
import types
import unittest
from unittest.mock import Mock, patch

from ai_box import xiaozhi


class XiaoZhiTests(unittest.TestCase):
    def test_activation_waits_for_binding_and_refreshes_configuration(self):
        screen = Mock()
        stop = Mock()
        stop.is_set.return_value = False
        config = {"websocket": {"url": "wss://example.invalid", "token": "secret"}}
        replies = [(200, {"activation": {"code": "123456"}}), TimeoutError(), (200, {}), (200, config)]
        with patch.object(xiaozhi, "identity", return_value=("00:11:22:33:44:55", "client")), \
                patch.object(xiaozhi, "post_ota", side_effect=replies) as post:
            self.assertEqual(xiaozhi.connection_config(screen, stop), (config["websocket"], "00:11:22:33:44:55", "client"))
        self.assertEqual([call.args[0] for call in post.call_args_list], ["", "activate", "activate", ""])
        self.assertIn("123456", screen.text.call_args.args[0])

    def test_opus_round_trip(self):
        codec = xiaozhi.Opus(24000)
        try:
            packet = codec.encode(bytes(1920))
            self.assertEqual(len(codec.decode(packet)), 2880)
        finally:
            codec.close()

    def test_online_turn_uploads_and_plays_without_local_models(self):
        stop = threading.Event()
        screen = Mock()
        streams = []
        callback = []
        output = Mock()
        input_stream = Mock()
        audio = Mock()

        def open_stream(**kwargs):
            if kwargs.get("input"):
                callback.append(kwargs["stream_callback"])
                streams.append(input_stream)
                return input_stream
            streams.append(output)
            return output

        audio.open.side_effect = open_stream
        pyaudio = types.ModuleType("pyaudio")
        pyaudio.PyAudio = lambda: audio
        pyaudio.paInt16 = 8
        pyaudio.paInputOverflow = 2
        pyaudio.paAbort = 2
        pyaudio.paContinue = 0
        codec = xiaozhi.Opus(24000)
        packet = codec.encode(bytes(1920))
        codec.close()

        class Socket:
            def __init__(self):
                self.sent = []
                self.messages = [json.dumps({"type": "hello", "transport": "websocket", "session_id": "s",
                                             "audio_params": {"sample_rate": 24000, "channels": 1}}),
                                 json.dumps({"type": "stt", "text": "你好"}),
                                 json.dumps({"type": "tts", "state": "start"}), packet,
                                 json.dumps({"type": "tts", "state": "sentence_start", "text": "你好"}),
                                 json.dumps({"type": "tts", "state": "stop"})]
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def send(self, data):
                self.sent.append(data)
                if isinstance(data, str) and json.loads(data).get("state") == "start":
                    if sum(isinstance(x, str) and json.loads(x).get("state") == "start" for x in self.sent) == 2:
                        stop.set()
                    else:
                        callback[0](bytes(3840), 960, None, 0)
            def recv(self, timeout):
                return self.messages.pop(0)

        ws = Socket()
        client = types.ModuleType("websockets.sync.client")
        client.connect = lambda *args, **kwargs: ws
        with patch.object(xiaozhi, "connection_config", return_value=({"url": "wss://example.invalid", "token": "x"}, "mac", "id")), \
                patch.dict(sys.modules, {"pyaudio": pyaudio, "websockets": types.ModuleType("websockets"),
                                         "websockets.sync": types.ModuleType("websockets.sync"),
                                         "websockets.sync.client": client}):
            xiaozhi.XiaozhiAssistant(screen).run(stop)
        self.assertTrue(any(isinstance(item, bytes) for item in ws.sent))
        output.write.assert_called_once()
        self.assertEqual(len(output.write.call_args.args[0]), 2880)
        input_stream.close.assert_called_once()
        output.close.assert_called_once()
        audio.terminate.assert_called_once()
        screen.response.assert_called_with("你好", "小智正在回答", "你好")


if __name__ == "__main__":
    unittest.main()
