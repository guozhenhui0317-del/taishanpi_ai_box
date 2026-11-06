"""@brief Shared native-resolution text, menu and face rendering for ST7789."""

import os

from PIL import Image, ImageDraw, ImageFont


class Screen:
    """@brief Draw application views using one display and its Chinese font."""

    def __init__(self, display, font):
        self.display = display
        self.font = font

    def text(self, text):
        """@brief Display wrapped text at the screen's native resolution."""
        self.display.display(text_frame(self.display.width, self.display.height, text, self.font))

    def menu(self, items, index):
        """@brief Display the selected menu item and navigation arrows."""
        self.display.display(menu_frame(self.display.width, self.display.height, items, index, self.font))

    def face(self, state=0):
        """@brief Display one frame of the listening animation."""
        self.display.display(face_frame(self.display.width, self.display.height, state))


def load_font():
    """@brief Load the configured Chinese font with an actionable missing-file error."""
    path = os.environ.get("AI_BOX_FONT", "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc")
    try:
        return ImageFont.truetype(path, int(os.environ.get("AI_BOX_FONT_SIZE", "24")))
    except OSError as error:
        raise OSError("Set AI_BOX_FONT to an installed Chinese TTF/TTC font: " + path) from error


def text_frame(width, height, text, font):
    """@brief Wrap text by pixel width and show the last page when it overflows."""
    image = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(image)
    lines = []
    for paragraph in str(text).split("\n"):
        line = ""
        for character in paragraph:
            left, _, right, _ = draw.textbbox((0, 0), line + character, font=font)
            if line and right - left > width - 16:
                lines.append(line)
                line = ""
            line += character
        lines.append(line)
    line_height = font.size + 6
    for row, line in enumerate(lines[-max(1, (height - 16) // line_height):]):
        draw.text((8, 8 + row * line_height), line, font=font, fill="white")
    return image


def menu_frame(width, height, items, index, font):
    """@brief Center a menu item and navigation arrows on the actual screen."""
    image = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(image)
    text = items[index]
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    draw.text(((width - (right - left)) / 2 - left,
               (height - (bottom - top)) / 2 - top), text, font=font, fill="white")
    middle = height // 2
    if index > 0:
        draw.polygon((10, middle, 20, middle - 10, 20, middle + 10), fill="white")
    if index < len(items) - 1:
        draw.polygon((width - 10, middle, width - 20, middle - 10,
                      width - 20, middle + 10), fill="white")
    return image


def face_frame(width, height, mouth_state=0):
    """@brief Scale the original three-state face animation to the screen size."""
    image = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(image)
    for x in (width // 4, width * 3 // 4):
        draw.ellipse((x - width // 30, height // 3 - height // 20,
                      x + width // 30, height // 3 + height // 20), fill="white")
    mouth = (width // 3, height * 3 // 5, width * 2 // 3, height * 3 // 4)
    if mouth_state == 0:
        draw.line((mouth[0], mouth[3], mouth[2], mouth[3]), fill="white", width=3)
    elif mouth_state == 1:
        draw.arc(mouth, 0, 180, fill="white", width=3)
    else:
        draw.ellipse(mouth, fill="white")
    return image
