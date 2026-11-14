"""! @brief Verify direct app selection and rotation-aware touch coordinates."""

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import ImageFont

from ai_box.app import Application
from ai_box.mipi import TouchDisplay
from ai_box.ui import Screen, menu_boxes, menu_index_at


class LauncherTests(unittest.TestCase):
    def test_each_rotated_touch_hits_its_visible_tile(self):
        with TemporaryDirectory() as directory, \
                patch("ai_box.mipi.ORIENTATION_PATH", Path(directory) / "orientation"), \
                patch("ai_box.mipi.tk.Label"):
            root = Mock()
            root.winfo_screenwidth.return_value = 480
            root.winfo_screenheight.return_value = 800
            display = TouchDisplay(root)
            for angle in (0, 90, 180, 270):
                display.orientation = angle
                display._set_size()
                for index, (left, top, right, bottom) in enumerate(
                        menu_boxes(display.width, display.height, 5)):
                    x, y = (left + right) // 2, (top + bottom) // 2
                    physical = {0: (x, y), 90: (y, 799 - x),
                                180: (479 - x, 799 - y), 270: (479 - y, x)}[angle]
                    point = display.touch_point(SimpleNamespace(x=physical[0], y=physical[1]))
                    self.assertEqual(menu_index_at(display.width, display.height, 5, *point), index)
                self.assertIsNone(menu_index_at(display.width, display.height, 5, 0, 0))

    def test_taps_open_apps_and_return_without_using_neighboring_tiles(self):
        screen, network, rotate = Mock(), Mock(), Mock()
        network.active = False
        app = Application(screen, [], rotate=rotate, network=network)
        self.assertEqual(app.main_menu, ("AI助手", "天气", "小智联网", "网络设置", "旋转屏幕"))
        app.select(None, touch=True)
        network.open.assert_not_called()
        app.select(1, touch=True)
        self.assertTrue(app.weather)
        app.select(None, touch=True)
        self.assertFalse(app.weather)
        app.select(3, touch=True)
        network.open.assert_called_once()
        app.select(4, touch=True)
        rotate.assert_called_once()
        with patch("ai_box.app.threading.Thread"):
            app.select(0, touch=True)
        screen.set_voice_mode.assert_called_with(True)
        app.select(None, touch=True)
        self.assertTrue(app._voice_stop.is_set())

    def test_app_frames_include_a_return_bar(self):
        font = ImageFont.truetype("DejaVuSans.ttf", 32)
        for width, height in ((480, 800), (800, 480)):
            display = Mock(width=width, height=height)
            screen = Screen(display, font)
            screen.weather("Temperature")
            self.assertEqual(display.display.call_args.args[0].size, (width, height))
            screen.set_voice_mode(True)
            screen.response("Question", "Thinking", "content")
            frame = display.display.call_args.args[0]
            self.assertEqual(frame.size, (width, height))
            self.assertEqual(frame.getpixel((0, 0)), (16, 26, 44))


if __name__ == "__main__":
    unittest.main()
