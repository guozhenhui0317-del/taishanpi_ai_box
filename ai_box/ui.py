"""! @brief Shared native-resolution text, menu and face rendering for the MIPI display."""

import os

from PIL import Image, ImageDraw, ImageFont


class Screen:
    """! @brief Draw application views using one display and its Chinese font."""

    def __init__(self, display, font):
        """! @brief Store the display and font used to render application views.
        @param display Display interface accepting Pillow frames.
        @param font Pillow font used for text.
        """
        self.display = display
        self.font = font
        self.thinking_font = font.font_variant(size=max(1, font.size - 4))
        self.voice_mode = False

    def set_voice_mode(self, enabled):
        """! @brief Show a return control while the voice assistant owns the screen.
        @param enabled True while voice mode is active.
        """
        self.voice_mode = enabled

    def _with_back(self, image):
        """! @brief Add a return bar above an application page.
        @param image Page content, excluding the return bar.
        @return Full-size RGB frame.
        """
        width, height = self.display.width, self.display.height
        frame = Image.new("RGB", (width, height), "#101a2c")
        draw = ImageDraw.Draw(frame)
        draw.line((20, 17, 10, 27, 20, 37), fill="white", width=3)
        draw.text((32, 7), "返回", font=self.font, fill="white")
        frame.paste(image, (0, 54))
        return frame

    def text(self, text):
        """! @brief Display wrapped text at the screen's native resolution.
        @param text Text to render.
        """
        width, height = self.display.width, self.display.height
        image = text_frame(width, height - 54 if self.voice_mode else height, text, self.font)
        self.display.display(self._with_back(image) if self.voice_mode else image)

    def weather(self, text):
        """! @brief Display weather readings below a return bar.
        @param text Online weather forecast.
        """
        image = text_frame(self.display.width, self.display.height - 54, text, self.font)
        self.display.display(self._with_back(image))

    def response(self, question, stage, content):
        """! @brief Keep the response stage visible while the latest content scrolls.
        @param question Recognized user question, shown on one header line.
        @param stage Thinking or final-answer status.
        @param content Accumulated thinking text or final answer.
        """
        width, height = self.display.width, self.display.height
        if self.voice_mode:
            height -= 54
        thinking = "思考" in stage
        header_height = 2 * (self.font.size + 6) + 16
        image = Image.new("RGB", (width, height))
        draw = ImageDraw.Draw(image)
        draw.text((8, 8), stage, font=self.font, fill="yellow" if thinking else "white")
        question_line = "识别：" + question
        while question_line and draw.textbbox((0, 0), question_line, font=self.font)[2] > width - 16:
            question_line = question_line[:-1]
        if question_line != "识别：" + question:
            question_line = question_line[:-1] + "…"
        draw.text((8, self.font.size + 14), question_line, font=self.font, fill="white")
        body = text_frame(width, max(1, height - header_height), content[-800:],
                          self.thinking_font if thinking else self.font, italic=thinking)
        image.paste(body, (0, header_height))
        self.display.display(self._with_back(image) if self.voice_mode else image)

    def menu(self, items, index):
        """! @brief Display all available apps as a touchable grid.
        @param items Sequence of menu labels.
        @param index Index of the selected item.
        """
        self.display.display(menu_frame(self.display.width, self.display.height, items, index, self.font))

    def face(self, state=0):
        """! @brief Display one frame of the listening animation.
        @param state Mouth state: 0 for a line, 1 for an arc, otherwise an ellipse.
        """
        width, height = self.display.width, self.display.height
        image = face_frame(width, height - 54 if self.voice_mode else height, state)
        self.display.display(self._with_back(image) if self.voice_mode else image)


def load_font():
    """! @brief Load the configured Chinese font with an actionable missing-file error.
    @return Loaded Pillow font.
    @exception OSError If the configured font cannot be opened.
    """
    path = os.environ.get("AI_BOX_FONT", "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc")
    try:
        return ImageFont.truetype(path, int(os.environ.get("AI_BOX_FONT_SIZE", "24")))
    except OSError as error:
        raise OSError("Set AI_BOX_FONT to an installed Chinese TTF/TTC font: " + path) from error


def text_frame(width, height, text, font, italic=False):
    """! @brief Wrap text by pixel width and show the last page when it overflows.
    @param width Frame width in pixels.
    @param height Frame height in pixels.
    @param text Text to render.
    @param font Pillow font used for wrapping and drawing.
    @param italic Apply a per-line oblique style, including for Chinese glyphs.
    @return RGB Pillow image containing the text.
    """
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
        if italic:
            mask = Image.new("L", (width, line_height + 16))
            ImageDraw.Draw(mask).text((8, 0), line, font=font, fill=255)
            mask = mask.transform(mask.size, getattr(Image, "Transform", Image).AFFINE,
                                  (1, 0.2, -int(0.2 * line_height), 0, 1, 0),
                                  resample=getattr(Image, "Resampling", Image).BICUBIC)
            image.paste("white", (0, 8 + row * line_height), mask)
        else:
            draw.text((8, 8 + row * line_height), line, font=font, fill="white")
    return image


def menu_boxes(width, height, count):
    """! @brief Calculate the same app tile bounds for drawing and touch handling.
    @param width Frame width in pixels.
    @param height Frame height in pixels.
    @param count Number of apps.
    @return App tile rectangles in menu order.
    """
    if count == 0:
        return []
    columns = 4 if width > height else 2
    rows = (count + columns - 1) // columns
    gap = max(8, min(width, height) // 30)
    top = max(52, min(80, height // 6))
    tile_width = (width - (columns + 1) * gap) // columns
    tile_height = min(280, (height - top - (rows + 1) * gap) // rows)
    grid_height = rows * tile_height + (rows - 1) * gap
    top += max(0, (height - top - gap - grid_height) // 2)
    return [(gap + (i % columns) * (tile_width + gap),
             top + (i // columns) * (tile_height + gap),
             gap + (i % columns) * (tile_width + gap) + tile_width,
             top + (i // columns) * (tile_height + gap) + tile_height)
            for i in range(count)]


def menu_index_at(width, height, count, x, y):
    """! @brief Find the app tile touched at a drawing coordinate.
    @param width Frame width in pixels.
    @param height Frame height in pixels.
    @param count Number of apps.
    @param x Horizontal touch coordinate.
    @param y Vertical touch coordinate.
    @return App index, or None when the touch is outside all tiles.
    """
    for index, (left, top, right, bottom) in enumerate(menu_boxes(width, height, count)):
        if left <= x < right and top <= y < bottom:
            return index
    return None


def menu_frame(width, height, items, index, font):
    """! @brief Draw a phone-style app grid at the actual screen size.
    @param width Frame width in pixels.
    @param height Frame height in pixels.
    @param items Sequence of menu labels.
    @param index Index of the selected item.
    @param font Pillow font used for the label.
    @return RGB Pillow image containing the menu.
    """
    image = Image.new("RGB", (width, height), "#101a2c")
    draw = ImageDraw.Draw(image)
    draw.text((max(10, width // 30), 10), "AI BOX", font=font, fill="white")
    colors = {"AI助手": "#4388e8", "天气": "#e6a63d",
              "旋转屏幕": "#8867d9", "网络设置": "#28a88b", "小智联网": "#d56490"}
    for i, (item, box) in enumerate(zip(items, menu_boxes(width, height, len(items)))):
        left, top, right, bottom = box
        draw.rounded_rectangle(box, radius=16, fill="#1c2b43",
                               outline="#669fe8" if i == index else "#34445b", width=2)
        size = int(min((right - left) * 0.57, (bottom - top) * 0.58, 112))
        cx = (left + right) // 2
        icon_top = top + max(8, (bottom - top - size - font.size - 12) // 2)
        icon = (cx - size // 2, icon_top, cx + size // 2, icon_top + size)
        draw.rounded_rectangle(icon, radius=max(8, size // 5), fill=colors.get(item, "#6383a7"))
        x, y, s = icon[0], icon[1], size
        stroke = max(2, size // 24)
        if item in ("AI助手", "小智联网"):
            draw.rounded_rectangle((x+s//5, y+s//4, x+4*s//5, y+3*s//4),
                                   radius=s//8, outline="white", width=stroke)
            for px in (x+2*s//5, x+3*s//5):
                draw.ellipse((px-stroke, y+2*s//5-stroke, px+stroke, y+2*s//5+stroke), fill="white")
            draw.arc((x+s//3, y+2*s//5, x+2*s//3, y+7*s//10), 0, 180, fill="white", width=stroke)
        elif item == "天气":
            draw.ellipse((x+s//4, y+s//5, x+3*s//5, y+11*s//20), outline="white", width=stroke)
            draw.rounded_rectangle((x+s//4, y+s//2, x+4*s//5, y+7*s//10),
                                   radius=s//10, fill="white")
            draw.ellipse((x+2*s//5, y+2*s//5, x+7*s//10, y+7*s//10), fill="white")
        elif item == "旋转屏幕":
            draw.arc((x+s//4, y+s//4, x+3*s//4, y+3*s//4), 200, 495, fill="white", width=stroke)
            draw.polygon(((x+3*s//4, y+s//3), (x+3*s//4, y+s//8),
                          (x+9*s//10, y+s//4)), fill="white")
        elif item == "网络设置":
            for inset in (s//5, 3*s//10, 2*s//5):
                draw.arc((x+inset, y+inset, x+s-inset, y+s-inset), 200, 340,
                         fill="white", width=stroke)
            draw.ellipse((x+s//2-stroke, y+3*s//5-stroke,
                          x+s//2+stroke, y+3*s//5+stroke), fill="white")
        text_box = draw.textbbox((0, 0), item, font=font)
        text_width = text_box[2] - text_box[0]
        draw.text((cx - text_width // 2 - text_box[0], icon_top + size + 8),
                  item, font=font, fill="white")
    return image


def face_frame(width, height, mouth_state=0):
    """! @brief Scale the original three-state face animation to the screen size.
    @param width Frame width in pixels.
    @param height Frame height in pixels.
    @param mouth_state Mouth state: 0 for a line, 1 for an arc, otherwise an ellipse.
    @return RGB Pillow image containing the face.
    """
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
