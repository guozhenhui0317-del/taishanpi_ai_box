"""! @brief Verify that streamed content preserves its header in both screen orientations."""

import os
import unittest
from unittest.mock import Mock

from PIL import ImageChops, ImageFont

from ai_box.ui import Screen


class ResponseScreenTests(unittest.TestCase):
    """! @brief Check the pinned header when thinking text exceeds a page."""

    def test_streaming_overflow_preserves_header_in_portrait_and_landscape(self):
        """! @brief Scrolling changes the body while preserving the question and stage."""
        font = ImageFont.truetype(os.environ.get("AI_BOX_TEST_FONT", "DejaVuSans.ttf"), 24)
        for width, height in ((480, 800), (800, 480)):
            with self.subTest(size=(width, height)):
                display = Mock(width=width, height=height)
                screen = Screen(display, font)
                screen.response("Question", "Thinking", "A\n" * 100)
                first = display.display.call_args.args[0]
                screen.response("Question", "Thinking", "B\n" * 100)
                second = display.display.call_args.args[0]
                header_height = 2 * (font.size + 6) + 16
                area = (0, 0, width, header_height)
                self.assertIsNone(ImageChops.difference(first.crop(area), second.crop(area)).getbbox())
                self.assertIsNotNone(ImageChops.difference(first, second).getbbox())
                self.assertEqual(second.size, (width, height))


if __name__ == "__main__":
    unittest.main()
