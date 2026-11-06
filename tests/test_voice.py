"""@brief Exercise voice lifecycle and cancellation without AI packages or hardware."""

import subprocess
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch

from ai_box.voice import VoiceAssistant


class VoiceTests(unittest.TestCase):
    """@brief Test public voice behavior against microphone and model substitutes."""

    def setUp(self):
        """@brief Provide optional packages without importing their native extensions."""
        self.audio = Mock()
        self.client = Mock()
        self.recognizer = Mock()
        self.packages = {
            "pyaudio": SimpleNamespace(paInt16=8, PyAudio=Mock(return_value=self.audio)),
            "ollama": SimpleNamespace(Client=Mock(return_value=self.client)),
            "vosk": SimpleNamespace(
                Model=Mock(), KaldiRecognizer=Mock(return_value=self.recognizer)
            ),
        }
        self.patch = patch.dict("sys.modules", self.packages)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.screen = Mock()
        self.assistant = VoiceAssistant(self.screen)
        self.addCleanup(self.assistant.close)
        self.stop = threading.Event()

    def test_close_is_idempotent(self):
        """@brief Closing twice releases native and network resources exactly once."""
        self.assistant.close()
        self.assistant.close()
        self.audio.terminate.assert_called_once_with()
        self.client.close.assert_called_once_with()
        self.packages["ollama"].Client.assert_called_once_with(timeout=15.0)

    def test_audio_initialization_failure_closes_client(self):
        """@brief An unavailable microphone backend does not leak the created client."""
        self.packages["pyaudio"].PyAudio.side_effect = OSError("audio unavailable")
        self.client.close.reset_mock()
        with self.assertRaisesRegex(OSError, "audio unavailable"):
            VoiceAssistant(self.screen)
        self.client.close.assert_called_once_with()

    def test_recognized_command_closes_stream_and_skips_model(self):
        """@brief Hardware commands use the callback and release the recording stream."""
        self.recognizer.Result.return_value = '{"text": "开启"}'
        handler = Mock(side_effect=lambda text: self.stop.set() or True)
        self.assistant.run(self.stop, handler)
        handler.assert_called_once_with("开启")
        self.client.chat.assert_not_called()
        stream = self.audio.open.return_value
        stream.read.assert_called_once_with(2048, exception_on_overflow=False)
        stream.stop_stream.assert_called_once_with()
        stream.close.assert_called_once_with()
        self.screen.face.assert_called_once_with(0)

    def test_recording_error_releases_stream(self):
        """@brief A failed audio read leaves no active recording stream."""
        stream = self.audio.open.return_value
        stream.read.side_effect = OSError("microphone disconnected")
        with self.assertRaisesRegex(OSError, "microphone disconnected"):
            self.assistant.run(self.stop)
        stream.stop_stream.assert_called_once_with()
        stream.close.assert_called_once_with()

    def test_display_error_releases_stream(self):
        """@brief A failed face frame stops recording without a background animation."""
        self.screen.face.side_effect = OSError("screen disconnected")
        with self.assertRaisesRegex(OSError, "screen disconnected"):
            self.assistant.run(self.stop)
        stream = self.audio.open.return_value
        stream.stop_stream.assert_called_once_with()
        stream.close.assert_called_once_with()

    def test_cancelled_recording_does_not_recognize_or_reply(self):
        """@brief Cancellation during a read drops the sample and releases the stream."""
        stream = self.audio.open.return_value
        stream.read.side_effect = lambda *args, **kwargs: self.stop.set() or b"sample"
        self.assistant.run(self.stop)
        self.recognizer.AcceptWaveform.assert_not_called()
        self.client.chat.assert_not_called()
        stream.stop_stream.assert_called_once_with()
        stream.close.assert_called_once_with()

    def test_reply_accumulates_dict_like_chunks(self):
        """@brief Dict-like model responses display cumulative text and retain history."""
        class Chunk:
            """@brief Mimic the subscript API of Ollama response models."""

            def __init__(self, content):
                """@brief Store one response fragment."""
                self.content = content

            def __getitem__(self, key):
                """@brief Expose message content without dictionary-only methods."""
                return {"content": self.content}

        self.client.chat.return_value = iter([Chunk("你好"), Chunk(None), Chunk("世界")])
        self.assistant.speak = Mock()
        self.assistant.reply("您好", self.stop)
        self.assertEqual(self.screen.text.call_args_list, [call("你好"), call("你好世界")])
        self.assertEqual(self.assistant.speak.call_args_list, [call("你好"), call("世界")])
        self.assertEqual(self.assistant.history[-1], {"role": "assistant", "content": "你好世界"})

    def test_cancelled_reply_closes_iterator_without_requesting_another_chunk(self):
        """@brief Stopping during speech closes the request before another network read."""
        closed = Mock()

        def response():
            """@brief Fail if cancellation still requests another fragment."""
            try:
                yield {"message": {"content": "你好"}}
                self.fail("read another chunk after cancellation")
            finally:
                closed()

        self.client.chat.return_value = response()
        self.assistant.speak = Mock(side_effect=lambda text: self.stop.set())
        self.assistant.reply("您好", self.stop)
        closed.assert_called_once_with()
        self.assertEqual(len(self.assistant.history), 1)

    def test_reply_error_closes_iterator(self):
        """@brief A display failure releases a partially consumed network response."""
        closed = Mock()

        def response():
            """@brief Record when the network response is closed."""
            try:
                yield {"message": {"content": "你好"}}
            finally:
                closed()

        self.client.chat.return_value = response()
        self.screen.text.side_effect = OSError("screen disconnected")
        with self.assertRaises(OSError):
            self.assistant.reply("您好", self.stop)
        closed.assert_called_once_with()

    @patch("ai_box.voice.subprocess.Popen")
    def test_speech_cancellation_terminates_and_reaps_process(self, popen):
        """@brief Cancellation kills an unresponsive speaker and retains numeric readings."""
        process = popen.return_value
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired("espeak-ng", 1), 0]
        stop = Mock()
        stop.is_set.side_effect = [False, False, True]
        self.assistant._stop_event = stop
        self.assistant.speak("温度 **25.5** 摄氏度")
        popen.assert_called_once_with(["espeak-ng", "-v", "zh", "温度 25.5 摄氏度"])
        process.terminate.assert_called_once_with()
        process.kill.assert_called_once_with()
        self.assertEqual(process.wait.call_args_list, [call(timeout=1), call()])


if __name__ == "__main__":
    unittest.main()
