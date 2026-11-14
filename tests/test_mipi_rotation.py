"""! @brief Verify four screen orientations, touch mapping and saved state."""

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from ai_box import app, mipi


class MipiRotationTests(unittest.TestCase):
    def test_four_rotations_map_frames_touch_and_restore_saved_orientation(self):
        with TemporaryDirectory() as directory, \
                patch.object(mipi, "ORIENTATION_PATH", Path(directory) / "orientation"), \
                patch.object(mipi.tk, "Label"), \
                patch.object(mipi.ImageTk, "PhotoImage", side_effect=lambda image, master: image):
            root = Mock()
            root.winfo_screenwidth.return_value = 480
            root.winfo_screenheight.return_value = 800
            display = mipi.TouchDisplay(root)
            positions = ((0, (480, 800), 30, (0, 0)),
                         (90, (800, 480), 99, (0, 799)),
                         (180, (480, 800), 449, (479, 799)),
                         (270, (800, 480), 700, (479, 0)))
            for angle, size, touch_x, pixel in positions:
                self.assertEqual((display.orientation, display.width, display.height), (angle, *size))
                self.assertEqual(display.touch_x(SimpleNamespace(x=30, y=700)), touch_x)
                expected_y = {0: 700, 90: 30, 180: 99, 270: 449}[angle]
                self.assertEqual(display.touch_point(SimpleNamespace(x=30, y=700)), (touch_x, expected_y))
                frame = Image.new("RGB", size)
                frame.putpixel((0, 0), (255, 0, 0))
                display.display(frame)
                display.refresh()
                self.assertEqual(display.image.size, (480, 800))
                self.assertEqual(display.image.getpixel(pixel), (255, 0, 0))
                display.rotate()
                self.assertEqual(mipi.TouchDisplay(root).orientation, (angle + 90) % 360)
            self.assertEqual(display.orientation, 0)

    def test_previous_landscape_setting_is_preserved(self):
        with TemporaryDirectory() as directory, \
                patch.object(mipi, "ORIENTATION_PATH", Path(directory) / "orientation"), \
                patch.object(mipi.tk, "Label"):
            root = Mock()
            root.winfo_screenwidth.return_value = 480
            root.winfo_screenheight.return_value = 800
            mipi.ORIENTATION_PATH.write_text("landscape\n")
            display = mipi.TouchDisplay(root)
            self.assertEqual(display.orientation, 90)
            display.rotate()
            self.assertEqual(mipi.ORIENTATION_PATH.read_text(), "180\n")
            mipi.ORIENTATION_PATH.write_text("portrait\n")
            self.assertEqual(mipi.TouchDisplay(root).orientation, 0)

    def test_failed_save_does_not_change_orientation(self):
        with TemporaryDirectory() as directory, \
                patch.object(mipi, "ORIENTATION_PATH", Path(directory) / "orientation"), \
                patch.object(mipi.tk, "Label"), \
                patch.object(Path, "write_text", side_effect=OSError("read only")):
            root = Mock()
            root.winfo_screenwidth.return_value = 480
            root.winfo_screenheight.return_value = 800
            display = mipi.TouchDisplay(root)
            with self.assertRaises(OSError):
                display.rotate()
            self.assertEqual((display.orientation, display.width, display.height), (0, 480, 800))

    def test_rotation_menu_has_no_light_and_invokes_callback(self):
        rotate = Mock()
        application = app.Application(Mock(), [], rotate=rotate)
        self.assertEqual(application.main_menu, ("AI助手", "天气", "小智联网", "旋转屏幕"))
        application.move(3)
        application.select()
        application.select()
        self.assertEqual(rotate.call_count, 2)
        self.assertFalse(application.weather)


if __name__ == "__main__":
    unittest.main()
