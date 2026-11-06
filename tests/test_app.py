"""@brief Check menu behavior, lazy imports and application resource ownership."""

from contextlib import ExitStack
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
        self.sensor = Mock()
        self.led = Mock(value=False)
        self.application = app.Application(self.screen, self.sensor, self.led, [])

    def test_light_menu_and_voice_commands_share_the_same_led(self):
        self.application.select()
        self.application.select()
        self.assertTrue(self.led.value)
        self.application.move(1)
        self.application.select()
        self.assertFalse(self.led.value)
        self.application.move(1)
        self.application.select()
        self.assertFalse(self.application.in_light_menu)
        self.application._voice = Mock()
        self.assertTrue(self.application.handle_voice_command("开启灯"))
        self.assertTrue(self.led.value)
        self.assertTrue(self.application.handle_voice_command("停止"))
        self.assertFalse(self.led.value)
        self.assertFalse(self.application.handle_voice_command("你好"))

    def test_weather_button_is_nonblocking_and_navigation_leaves_weather(self):
        self.application.move(2)
        self.application.select()
        self.assertTrue(self.application.weather)
        self.sensor.read.assert_not_called()
        self.application.select()
        self.assertFalse(self.application.weather)
        self.application.select()
        self.application.move(-1)
        self.assertFalse(self.application.weather)
        self.assertEqual(self.application.index, 1)

    def test_weather_render_uses_paired_samples_at_two_second_intervals(self):
        self.sensor.read.return_value = (25.0, 50.0)
        self.application.move(2)
        self.application.select()
        with patch.object(app.time, "monotonic", return_value=10):
            self.application.render()
            self.application.render()
        self.sensor.read.assert_called_once()
        self.screen.text.assert_called_once_with("温度: 25.0 C\n湿度: 50.0 %")
        with patch.object(app.time, "monotonic", return_value=12):
            self.application.render()
        self.assertEqual(self.sensor.read.call_count, 2)

    def test_sensor_failure_is_visible_and_does_not_break_navigation(self):
        self.sensor.read.side_effect = OSError("CRC mismatch")
        with patch("builtins.print"):
            self.assertEqual(self.application.weather_text(), "温湿度读取失败")
        self.application.move(1)
        self.application.render()
        self.screen.menu.assert_called_once_with(app.MAIN_MENU, 1)

    def test_slow_weather_sample_does_not_overwrite_a_new_voice_view(self):
        self.application.move(2)
        self.application.select()

        def sample():
            self.application._voice_running.set()
            return 25.0, 50.0

        self.sensor.read.side_effect = sample
        self.application.render()
        self.screen.text.assert_not_called()

    def test_ai_owns_the_screen_until_center_button_requests_stop(self):
        self.application._voice_running.set()
        self.application.render()
        self.application.move(1)
        self.assertEqual(self.application.index, 0)
        self.screen.menu.assert_not_called()
        self.application.select()
        self.assertTrue(self.application._voice_stop.is_set())

    def test_failed_voice_session_releases_audio_and_restores_menu(self):
        voice = Mock()
        voice.run.side_effect = OSError("microphone unavailable")
        self.application._voice_running.set()
        with patch.object(app, "VoiceAssistant", return_value=voice), patch("builtins.print"):
            self.application._run_voice()
        voice.close.assert_called_once()
        self.assertFalse(self.application._voice_running.is_set())
        self.assertTrue(self.application.dirty)

    def test_startup_failure_releases_previously_opened_hardware(self):
        display, sensor, led = Mock(), Mock(), Mock()
        with ExitStack() as patches:
            patches.enter_context(patch.object(app, "load_font"))
            patches.enter_context(patch.object(app, "Screen"))
            patches.enter_context(patch.object(app, "ST7789", return_value=display))
            patches.enter_context(patch.object(app, "AHT30", return_value=sensor))
            patches.enter_context(patch.object(app, "GPIO", side_effect=[led, OSError("button busy")]))
            with self.assertRaisesRegex(OSError, "button busy"):
                app.main()
        display.close.assert_called_once()
        sensor.close.assert_called_once()
        led.close.assert_called_once()
        self.assertFalse(led.value)


class EntryPointTests(unittest.TestCase):
    def test_help_and_sensor_dispatch_do_not_import_optional_dependencies(self):
        root = Path(__file__).resolve().parents[1]
        script = """
import sys
from unittest.mock import patch
for name in ('PIL', 'spidev', 'vosk', 'ollama', 'pyaudio'):
    sys.modules[name] = None
from ai_box.__main__ import main
try:
    main(['--help'])
except SystemExit as error:
    assert error.code == 0
with patch('ai_box.diagnostics.check_sensor') as check:
    main(['sensor'])
    check.assert_called_once_with()
"""
        result = subprocess.run([sys.executable, "-c", script], cwd=str(root), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rendering_uses_native_rgb_frames(self):
        from PIL import ImageFont
        from ai_box.ui import face_frame, menu_frame, text_frame

        font = ImageFont.truetype(os.environ.get("AI_BOX_TEST_FONT", "DejaVuSans.ttf"), 24)
        frames = [text_frame(240, 320, "Temperature\nHumidity", font),
                  menu_frame(240, 320, ["Light", "AI", "Weather"], 1, font)]
        frames.extend(face_frame(240, 320, state) for state in range(3))
        for frame in frames:
            self.assertEqual(frame.mode, "RGB")
            self.assertEqual(frame.size, (240, 320))
            self.assertIsNotNone(frame.getbbox())


if __name__ == "__main__":
    unittest.main()
