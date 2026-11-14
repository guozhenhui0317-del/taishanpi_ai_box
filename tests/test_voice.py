"""! @brief Exercise voice lifecycle and cancellation without AI packages or hardware."""

import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch

from ai_box import voice
from ai_box.voice import VoiceAssistant


class ModelCardTests(unittest.TestCase):
    def test_deepseek_checks_its_own_model_without_requiring_qwen(self):
        """! @brief The selected DeepSeek model can run on a card without Qwen."""
        with TemporaryDirectory() as directory, patch.object(voice, "MODEL_CARD", Path(directory)), \
                patch.object(voice.os.path, "ismount", return_value=True):
            models = Path(directory) / "ollama-models"
            manifest = models / "manifests/registry.ollama.ai/library/deepseek-r1/1.5b"
            manifest.parent.mkdir(parents=True)
            digest = "b" * 64
            manifest.write_text(json.dumps({"config": {"digest": "sha256:" + digest, "size": 2}, "layers": []}))
            blob = models / "blobs" / ("sha256-" + digest)
            blob.parent.mkdir()
            blob.write_bytes(b"ok")
            speech = Path(directory) / "vosk-model-small-cn-0.22/am/final.mdl"
            speech.parent.mkdir(parents=True)
            speech.write_bytes(b"model")
            self.assertEqual(voice.check_models("deepseek-r1:1.5b"), speech.parent.parent)
            with self.assertRaisesRegex(OSError, "AI 模型缺失或不完整"):
                voice.check_models("qwen2:0.5b")

    def test_sd_card_and_complete_model_are_required(self):
        with TemporaryDirectory() as directory, patch.object(voice, "MODEL_CARD", Path(directory)), \
                patch.object(voice.os.path, "ismount", return_value=False) as mounted:
            with self.assertRaisesRegex(OSError, "请插入并挂载 SD 卡"):
                voice.check_models()
            mounted.return_value = True
            with self.assertRaisesRegex(OSError, "AI 模型缺失或不完整"):
                voice.check_models()
            models = Path(directory) / "ollama-models"
            manifest = models / "manifests/registry.ollama.ai/library/qwen2/0.5b"
            manifest.parent.mkdir(parents=True)
            digest = "a" * 64
            manifest.write_text(json.dumps({"config": {"digest": "sha256:" + digest, "size": 2}, "layers": []}))
            blob = models / "blobs" / ("sha256-" + digest)
            blob.parent.mkdir()
            blob.write_bytes(b"ab")
            with self.assertRaisesRegex(OSError, "语音识别模型缺失"):
                voice.check_models()
            speech = Path(directory) / "vosk-model-small-cn-0.22/am/final.mdl"
            speech.parent.mkdir(parents=True)
            speech.write_bytes(b"model")
            self.assertEqual(voice.check_models(), speech.parent.parent)
            blob.write_bytes(b"a")
            with self.assertRaisesRegex(OSError, "AI 模型缺失或不完整"):
                voice.check_models()


class VoiceTests(unittest.TestCase):
    """! @brief Test public voice behavior against microphone and model substitutes."""

    def setUp(self):
        """! @brief Provide optional packages without importing their native extensions."""
        self.audio = Mock()
        self.client = Mock()
        self.recognizer = Mock()
        self.packages = {
            "pyaudio": SimpleNamespace(paInt16=8, paInputOverflow=2, paAbort=2, paContinue=0,
                                       PyAudio=Mock(return_value=self.audio)),
            "ollama": SimpleNamespace(Client=Mock(return_value=self.client)),
            "vosk": SimpleNamespace(
                Model=Mock(), KaldiRecognizer=Mock(return_value=self.recognizer)
            ),
        }
        self.patch = patch.dict("sys.modules", self.packages)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.screen = Mock()
        self.model_check = patch("ai_box.voice.check_models", return_value="/mnt/modelsd/vosk-model-small-cn-0.22")
        self.model_check.start()
        self.addCleanup(self.model_check.stop)
        self.assistant = VoiceAssistant(self.screen)
        self.addCleanup(self.assistant.close)
        self.stop = threading.Event()

    def test_close_is_idempotent(self):
        """! @brief Closing twice releases native and network resources exactly once."""
        self.assistant.close()
        self.assistant.close()
        self.audio.terminate.assert_called_once_with()
        self.client.close.assert_called_once_with()
        self.packages["ollama"].Client.assert_called_once_with(timeout=90.0)

    def test_audio_initialization_failure_closes_client(self):
        """! @brief An unavailable microphone backend does not leak the created client."""
        self.packages["pyaudio"].PyAudio.side_effect = OSError("audio unavailable")
        self.client.close.reset_mock()
        with self.assertRaisesRegex(OSError, "audio unavailable"):
            VoiceAssistant(self.screen)
        self.client.close.assert_called_once_with()

    def test_recognized_command_closes_stream_and_skips_model(self):
        """! @brief Hardware commands use the callback and release the recording stream."""
        self.recognizer.Result.return_value = '{"text": "开启"}'
        stream = Mock()
        def open_stream(**kwargs):
            kwargs["stream_callback"](b"\x01\x00\x10\x00\x02\x00\x20\x00", 2, None, 0)
            return stream
        self.audio.open.side_effect = open_stream
        handler = Mock(side_effect=lambda text: self.stop.set() or True)
        with patch.object(voice, "log") as log:
            self.assistant.run(self.stop, handler)
        log.assert_any_call("识别结果：开启")
        log.assert_any_call("已处理本地指令")
        handler.assert_called_once_with("开启")
        self.client.chat.assert_not_called()
        self.recognizer.AcceptWaveform.assert_called_once_with(b"\x01\x00\x02\x00")
        self.assertEqual(self.audio.open.call_args.kwargs["channels"], 2)
        stream.stop_stream.assert_called_once_with()
        stream.close.assert_called_once_with()
        self.screen.face.assert_called_once_with(0)

    def test_mono_input_fallback_is_preserved(self):
        """! @brief Mono-only capture devices continue to pass their input unchanged."""
        stream = Mock()
        def open_stream(**kwargs):
            if kwargs["channels"] == 2:
                raise OSError("stereo unavailable")
            kwargs["stream_callback"](b"\x01\x00\x02\x00", 2, None, 0)
            return stream
        self.audio.open.side_effect = open_stream
        self.recognizer.Result.return_value = '{"text": "你好"}'
        with patch.object(voice, "log"):
            self.assistant.run(self.stop, lambda text: self.stop.set() or True)
        self.assertEqual([call.kwargs["channels"] for call in self.audio.open.call_args_list], [2, 1])
        self.recognizer.AcceptWaveform.assert_called_once_with(b"\x01\x00\x02\x00")
        stream.close.assert_called_once_with()

    def test_recording_overflow_releases_stream(self):
        """! @brief An input overflow is reported instead of recognizing missing audio."""
        stream = Mock()
        def open_stream(**kwargs):
            kwargs["stream_callback"](b"", 0, None, self.packages["pyaudio"].paInputOverflow)
            return stream
        self.audio.open.side_effect = open_stream
        with self.assertRaisesRegex(OSError, "音频缓冲区溢出"):
            self.assistant.run(self.stop)
        stream.stop_stream.assert_called_once_with()
        stream.close.assert_called_once_with()

    def test_full_capture_queue_reports_overflow(self):
        """! @brief An overloaded recognizer cannot silently discard microphone audio."""
        stream = Mock()
        def open_stream(**kwargs):
            callback = kwargs["stream_callback"]
            for _ in range(129):
                status = callback(b"\x00\x00\x00\x00", 1, None, 0)
            self.assertEqual(status, (None, self.packages["pyaudio"].paAbort))
            return stream
        self.audio.open.side_effect = open_stream
        with self.assertRaisesRegex(OSError, "音频缓冲区溢出"):
            self.assistant.run(self.stop)
        self.recognizer.AcceptWaveform.assert_not_called()
        stream.close.assert_called_once_with()

    def test_display_error_releases_stream(self):
        """! @brief A failed face frame stops recording without a background animation."""
        self.screen.face.side_effect = OSError("screen disconnected")
        with self.assertRaisesRegex(OSError, "screen disconnected"):
            self.assistant.run(self.stop)
        stream = self.audio.open.return_value
        stream.stop_stream.assert_called_once_with()
        stream.close.assert_called_once_with()

    def test_cancelled_recording_does_not_recognize_or_reply(self):
        """! @brief Cancellation drops buffered samples and releases the stream."""
        stream = Mock()
        def open_stream(**kwargs):
            kwargs["stream_callback"](b"sample", 1, None, 0)
            self.stop.set()
            return stream
        self.audio.open.side_effect = open_stream
        self.assistant.run(self.stop)
        self.recognizer.AcceptWaveform.assert_not_called()
        self.client.chat.assert_not_called()
        stream.stop_stream.assert_called_once_with()
        stream.close.assert_called_once_with()

    def test_capture_continues_during_recognition(self):
        """! @brief Audio arriving while Vosk is busy remains available for recognition."""
        stream = Mock()
        callbacks = []
        def open_stream(**kwargs):
            callbacks.append(kwargs["stream_callback"])
            callbacks[0](b"\x01\x00\x10\x00", 1, None, 0)
            return stream
        def recognize(data):
            if data == b"\x01\x00":
                callbacks[0](b"\x02\x00\x20\x00", 1, None, 0)
                return False
            return True
        self.audio.open.side_effect = open_stream
        self.recognizer.AcceptWaveform.side_effect = recognize
        self.recognizer.Result.return_value = '{"text": "你好"}'
        self.assistant.run(self.stop, lambda text: self.stop.set() or True)
        self.assertEqual(self.recognizer.AcceptWaveform.call_args_list,
                         [call(b"\x01\x00"), call(b"\x02\x00")])

    def test_reply_accumulates_dict_like_chunks(self):
        """! @brief Dict-like model responses display cumulative text and retain history."""
        class Chunk:
            """! @brief Mimic the subscript API of Ollama response models."""

            def __init__(self, content):
                """! @brief Store one response fragment."""
                self.content = content

            def __getitem__(self, key):
                """! @brief Expose message content without dictionary-only methods."""
                return {"content": self.content}

        self.client.chat.return_value = iter([Chunk("你好"), Chunk(None), Chunk("世界")])
        self.assistant.speak = Mock()
        with patch.object(voice, "log") as log:
            self.assistant.reply("您好", self.stop)
        log.assert_any_call("正在请求模型 qwen2:0.5b")
        self.assertTrue(any("模型回复（" in args.args[0] and "你好世界" in args.args[0]
                            for args in log.call_args_list))
        self.assertEqual(self.screen.text.call_args_list,
                         [call("识别：您好\n正在思考…"), call("识别：您好\n回答：你好"),
                          call("识别：您好\n回答：你好世界")])
        self.assistant.speak.assert_called_once_with("你好世界")
        self.assertEqual(self.assistant.history[-1], {"role": "assistant", "content": "你好世界"})

    def test_cancelled_reply_closes_iterator_without_requesting_another_chunk(self):
        """! @brief Stopping during streaming closes the request before another network read."""
        closed = Mock()

        def response():
            """! @brief Fail if cancellation still requests another fragment."""
            try:
                yield {"message": {"content": "你好"}}
                self.fail("read another chunk after cancellation")
            finally:
                closed()

        self.client.chat.return_value = response()
        self.screen.text.side_effect = lambda text: self.stop.set() if "回答：" in text else None
        self.assistant.speak = Mock()
        self.assistant.reply("您好", self.stop)
        closed.assert_called_once_with()
        self.assistant.speak.assert_not_called()
        self.assertEqual(len(self.assistant.history), 1)

    def test_reply_error_closes_iterator(self):
        """! @brief A display failure releases a partially consumed network response."""
        closed = Mock()

        def response():
            """! @brief Record when the network response is closed."""
            try:
                yield {"message": {"content": "你好"}}
            finally:
                closed()

        self.client.chat.return_value = response()
        def fail_on_reply(text):
            if "回答：" in text:
                raise OSError("screen disconnected")
        self.screen.text.side_effect = fail_on_reply
        with self.assertRaises(OSError):
            self.assistant.reply("您好", self.stop)
        closed.assert_called_once_with()

    def test_history_keeps_system_and_two_recent_turns(self):
        """! @brief Bound the context while retaining the system message and recent turns."""
        self.assistant.speak = Mock()
        self.client.chat.side_effect = lambda **kwargs: iter([{"message": {"content": "答"}}])
        for text in ("一", "二", "三"):
            self.assistant.reply(text, self.stop)
        self.assertEqual([entry["content"] for entry in self.assistant.history],
                         [self.assistant.history[0]["content"], "二", "答", "三", "答"])
        self.assertEqual(self.assistant.history[0]["role"], "system")

    def test_deepseek_streams_thinking_and_only_speaks_and_remembers_answer(self):
        """! @brief Split tags across chunks without leaking thinking into speech or history."""
        self.assistant.model_name = "deepseek-r1:1.5b"
        self.client.generate.side_effect = lambda **kwargs: iter([
            {"response": fragment} for fragment in ("<thi", "nk>分析问题", "</thi", "nk>你好", "。")
        ] + [{"response": "", "done_reason": "stop"}])
        self.assistant.speak = Mock()
        self.assistant.reply("您好", self.stop)
        calls = self.screen.response.call_args_list
        self.assertIn(call("您好", "正在思考", "分析问题"), calls)
        self.assertIn(call("您好", "正在回答", "你好。"), calls)
        self.assertEqual(calls[-1], call("您好", "回答完成", "你好。"))
        self.assertFalse(any("<" in args.args[2] for args in calls))
        self.assistant.speak.assert_called_once_with("你好。")
        self.assertEqual(self.assistant.history[-1]["content"], "你好。")
        self.client.chat.assert_not_called()
        request = self.client.generate.call_args.kwargs
        self.assertTrue(request["raw"])
        self.assertTrue(request["stream"])
        self.assertEqual(request["options"], {"num_thread": 4, "num_ctx": 1024, "num_predict": 512})
        self.assistant.reply("再问一句", self.stop)
        prompt = self.client.generate.call_args.kwargs["prompt"]
        self.assertIn("<｜Assistant｜>你好。<｜end▁of▁sentence｜>", prompt)
        self.assertNotIn("分析问题", prompt)

    def test_completed_sentence_is_spoken_before_model_finishes(self):
        """! @brief Speak answer sentences concurrently without reading the thinking text."""
        self.assistant.model_name = "deepseek-r1:1.5b"
        started = threading.Event()
        spoken = []

        def speak(text):
            spoken.append(text)
            started.set()

        def response():
            yield {"response": "<think>内部分析。</think>第一句话。"}
            self.assertTrue(started.wait(2), "speech waited until the model completed")
            yield {"response": "第二句话。"}
            yield {"response": "", "done_reason": "stop"}

        self.assistant.speak = speak
        self.client.generate.return_value = response()
        self.assistant.reply("您好", self.stop)
        self.assertEqual(spoken, ["第一句话。", "第二句话。"])
        self.assertEqual(self.assistant.history[-1]["content"], "第一句话。第二句话。")

    def test_cancelling_streaming_speech_stops_later_segments(self):
        """! @brief Cancellation closes the response and discards queued answer text."""
        self.assistant.model_name = "deepseek-r1:1.5b"
        started, closed = threading.Event(), Mock()
        spoken = []

        def speak(text):
            spoken.append(text)
            started.set()
            self.stop.wait(2)

        def response():
            try:
                yield {"response": "<think>分析</think>第一句话。"}
                self.assertTrue(started.wait(2))
                self.stop.set()
                yield {"response": "不要播报。"}
            finally:
                closed()

        self.assistant.speak = speak
        self.client.generate.return_value = response()
        self.assistant.reply("您好", self.stop)
        self.assertEqual(spoken, ["第一句话。"])
        closed.assert_called_once()
        self.assertEqual(len(self.assistant.history), 1)

    def test_speech_failure_closes_stream_and_surfaces_error(self):
        """! @brief Playback errors end the stream rather than silently losing the audio."""
        failed, closed = threading.Event(), Mock()

        def speak(text):
            failed.set()
            raise OSError("speaker unavailable")

        def response():
            try:
                yield {"message": {"content": "第一句话。"}}
                self.assertTrue(failed.wait(2))
                yield {"message": {"content": "后续内容。"}}
            finally:
                closed()

        self.assistant.speak = speak
        self.client.chat.return_value = response()
        with self.assertRaisesRegex(OSError, "语音播报失败"):
            self.assistant.reply("您好", self.stop)
        closed.assert_called_once()

    def test_cancelling_deepseek_thinking_closes_stream_without_speaking(self):
        """! @brief Touch cancellation closes an active reasoning stream and keeps history intact."""
        self.assistant.model_name = "deepseek-r1:1.5b"
        closed = Mock()

        def response():
            """! @brief Detect an unexpected read after the display requests cancellation."""
            try:
                yield {"response": "<think>分析问题"}
                self.fail("read another chunk after cancellation")
            finally:
                closed()

        self.client.generate.return_value = response()
        self.screen.response.side_effect = lambda question, stage, text: self.stop.set() if "分析" in text else None
        self.assistant.speak = Mock()
        self.assistant.reply("您好", self.stop)
        closed.assert_called_once_with()
        self.assistant.speak.assert_not_called()
        self.assertEqual(len(self.assistant.history), 1)

    def test_truncated_deepseek_thinking_is_reported_without_playback(self):
        """! @brief An output limit produces an error instead of reading unfinished thinking aloud."""
        self.assistant.model_name = "deepseek-r1:1.5b"
        self.client.generate.return_value = iter([
            {"response": "<think>分析问题"},
            {"response": "", "done_reason": "length"},
        ])
        self.assistant.speak = Mock()
        with self.assertRaisesRegex(OSError, "输出达到上限"):
            self.assistant.reply("您好", self.stop)
        self.assistant.speak.assert_not_called()
        self.assertEqual(len(self.assistant.history), 1)

    @patch("ai_box.voice.subprocess.Popen")
    def test_disabled_speech_does_not_start_playback(self, popen):
        """! @brief Without a speaker, skip playback and resume listening immediately."""
        with patch.dict("os.environ", {"AI_BOX_SPEECH": "0"}), patch.object(voice, "log"):
            self.assistant.speak("你好")
        popen.assert_not_called()

    @patch("ai_box.voice.os.killpg")
    @patch("ai_box.voice.subprocess.Popen")
    def test_speech_cancellation_terminates_and_reaps_process(self, popen, killpg):
        """! @brief Cancellation kills an unresponsive speaker and retains numeric readings."""
        process = popen.return_value
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired("espeak-ng", 1), 0]
        stop = Mock()
        stop.is_set.side_effect = [False, False, True]
        self.assistant._stop_event = stop
        self.assistant.speak("温度 **25.5** 摄氏度")
        popen.assert_called_once_with(["/opt/ai-box/deployment/ai-box-speak", "温度 25.5 摄氏度"], start_new_session=True)
        self.assertEqual(killpg.call_args_list, [
            call(process.pid, voice.signal.SIGTERM), call(process.pid, voice.signal.SIGKILL)])
        self.assertEqual(process.wait.call_args_list, [call(timeout=1), call()])

    @patch("ai_box.voice.subprocess.Popen")
    def test_speech_process_failure_is_reported(self, popen):
        """! @brief A failed speech process is not reported as successful playback."""
        popen.return_value.poll.return_value = 1
        popen.return_value.wait.return_value = 1
        with self.assertRaisesRegex(OSError, "状态码 1"):
            self.assistant.speak("你好")


if __name__ == "__main__":
    unittest.main()
