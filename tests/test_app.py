"""! @brief Check menu behavior, lazy imports and application resource ownership."""

import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

from ai_box import app


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.screen = Mock()
        self.application = app.Application(self.screen, [])
        self.application._start_forecast = Mock()

    def test_weather_page_does_not_require_a_sensor(self):
        self.application.move(1)
        self.application.select()
        self.application.render()
        self.screen.weather.assert_called_once_with("成都天气获取中…")
        self.application.select()
        self.assertFalse(self.application.weather)

    def test_ai_owns_the_screen_until_center_button_requests_stop(self):
        self.application._voice_running.set()
        self.application.render()
        self.application.move(1)
        self.assertEqual(self.application.index, 0)
        self.screen.menu.assert_not_called()
        self.application.select()
        self.assertTrue(self.application._voice_stop.is_set())

    def test_failed_voice_session_releases_audio_and_shows_error(self):
        voice = Mock()
        voice.run.side_effect = OSError("microphone unavailable")
        self.application._voice_running.set()
        with patch.object(app, "VoiceAssistant", return_value=voice), patch("builtins.print"), \
                patch.object(app.traceback, "print_exc") as print_exc:
            self.application._run_voice()
        print_exc.assert_called_once_with()
        voice.close.assert_called_once()
        self.assertFalse(self.application._voice_running.is_set())
        self.assertFalse(self.application.dirty)
        self.screen.text.assert_called_once_with("语音助手出错：microphone unavailable\n点击屏幕返回")
        self.application.move(1)
        self.assertTrue(self.application.dirty)


class EntryPointTests(unittest.TestCase):
    def test_help_does_not_import_optional_dependencies(self):
        root = Path(__file__).resolve().parents[1]
        script = """
import sys
from unittest.mock import patch
for name in ('PIL', 'vosk', 'ollama', 'pyaudio'):
    sys.modules[name] = None
from ai_box.__main__ import main
try:
    main(['--help'])
except SystemExit as error:
    assert error.code == 0

"""
        result = subprocess.run([sys.executable, "-c", script], cwd=str(root), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rendering_uses_native_rgb_frames(self):
        from PIL import ImageFont
        from ai_box.ui import face_frame, menu_frame, text_frame

        font = ImageFont.truetype(os.environ.get("AI_BOX_TEST_FONT", "DejaVuSans.ttf"), 24)
        frames = [text_frame(240, 320, "Temperature\nHumidity", font),
                  menu_frame(240, 320, ["AI", "Weather", "Rotate"], 1, font)]
        frames.extend(face_frame(240, 320, state) for state in range(3))
        for frame in frames:
            self.assertEqual(frame.mode, "RGB")
            self.assertEqual(frame.size, (240, 320))
            self.assertIsNotNone(frame.getbbox())


if __name__ == "__main__":
    unittest.main()
