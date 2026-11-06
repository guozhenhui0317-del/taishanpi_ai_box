"""@brief ST7789 240x320 display on SPI3 CS0, using the confirmed TSPI wiring."""

from array import array
from contextlib import ExitStack
import os
from pathlib import Path
import re
import sys
import threading
import time

from linux_gpio import GPIO


SPI_DEVICES = Path("/sys/bus/spi/devices")
SPI_BUFFER_SIZE = Path("/sys/module/spidev/parameters/bufsiz")


def spi3_device():
    """@brief Find SPI3 CS0 by its device-tree controller, not its Linux bus ID."""
    matches = [device for device in SPI_DEVICES.glob("spi*.0")
               if (device / "of_node").resolve().parent.name == "spi@fe640000"
               and (device / "driver").resolve().name == "spidev"]
    if len(matches) != 1:
        raise OSError("Cannot uniquely find SPI3 CS0 bound to spidev; boot scheme B")
    return "/dev/spidev" + matches[0].name[3:]


def rgb565(rgb):
    """@brief Encode RGB888 bytes into the display's big-endian RGB565 stream."""
    if len(rgb) % 3:
        raise ValueError("RGB888 data must contain complete pixels")
    pixels = array("H", (((rgb[i] & 0xF8) << 8) | ((rgb[i + 1] & 0xFC) << 3)
                         | (rgb[i + 2] >> 3) for i in range(0, len(rgb), 3)))
    if sys.byteorder == "little":
        pixels.byteswap()
    return pixels.tobytes()


class ST7789:
    """@brief Serialize complete frames and own DC, reset and backlight GPIOs."""

    def __init__(self):
        import spidev

        rotation = int(os.environ.get("AI_BOX_ROTATION", "0"))
        bgr = int(os.environ.get("AI_BOX_BGR", "0"))
        invert = int(os.environ.get("AI_BOX_INVERT", "0"))
        self._bl_low = int(os.environ.get("AI_BOX_BL_ACTIVE_LOW", "0"))
        self._x = int(os.environ.get("AI_BOX_X_OFFSET", "0"))
        self._y = int(os.environ.get("AI_BOX_Y_OFFSET", "0"))
        speed = int(os.environ.get("AI_BOX_SPI_HZ", "10000000"))
        if rotation not in (0, 90, 180, 270):
            raise ValueError("AI_BOX_ROTATION must be 0, 90, 180 or 270")
        if any(value not in (0, 1) for value in (bgr, invert, self._bl_low)):
            raise ValueError("BGR, INVERT and BL_ACTIVE_LOW must be 0 or 1")
        self.width, self.height = (320, 240) if rotation in (90, 270) else (240, 320)
        if not (0 <= self._x <= 65536 - self.width and 0 <= self._y <= 65536 - self.height) or speed <= 0:
            raise ValueError("Invalid display offset or SPI frequency")
        device = os.environ.get("AI_BOX_SPI_DEVICE") or spi3_device()
        match = re.fullmatch(r"/dev/spidev(\d+)\.(\d+)", device)
        if not match:
            raise ValueError("AI_BOX_SPI_DEVICE must be /dev/spidevB.C")
        if int(match[2]) != 0:
            raise ValueError("The screen is wired to hardware CS0")
        try:
            self._chunk = min(4096, int(SPI_BUFFER_SIZE.read_text()))
        except FileNotFoundError:
            self._chunk = 4096
        if self._chunk <= 0:
            raise ValueError("Invalid spidev buffer size")
        self._lock = threading.Lock()
        self._resources = ExitStack()
        self._closed = False
        try:
            self._spi = spidev.SpiDev()
            self._spi.open(int(match[1]), 0)
            self._resources.callback(self._spi.close)
            self._spi.mode = 0
            self._spi.bits_per_word = 8
            self._spi.max_speed_hz = speed
            self._spi.no_cs = False
            self._dc = GPIO(4, 21, initial=False)
            self._resources.callback(self._dc.close)
            self._reset = GPIO(1, 4, initial=True)
            self._resources.callback(self._reset.close)
            self._bl = GPIO(3, 20, initial=bool(self._bl_low))
            self._resources.callback(self._bl.close)
            self._reset.value = False
            time.sleep(0.010)
            self._reset.value = True
            time.sleep(0.120)
            self._command(0x11)
            time.sleep(0.120)
            for command, data in (
                (0x3A, b"\x05"), (0xB2, b"\x08\x08\x00\x22\x22"),
                (0xB7, b"\x35"), (0xC2, b"\x01\xff"), (0xC3, b"\x0b"),
                (0xC4, b"\x20"), (0xBB, b"\x20"), (0xC5, b"\x20"),
                (0xD0, b"\xa4\xa1"),
            ):
                self._command(command, data)
            madctl = {0: 0, 90: 0xA0, 180: 0xC0, 270: 0x60}[rotation] | (bgr << 3)
            self._command(0x36, bytes([madctl]))
            gamma = bytes.fromhex("70 2c 2e 15 10 09 48 33 53 0b 19 18 20 25")
            self._command(0xE0, gamma)
            self._command(0xE1, gamma)
            self._command(0x21 if invert else 0x20)
            self._command(0x29)
            self.clear()
            self._bl.value = not self._bl_low
        except Exception:
            self.close()
            raise

    def _write(self, data):
        for start in range(0, len(data), self._chunk):
            self._spi.writebytes(list(data[start:start + self._chunk]))

    def _command(self, command, data=b""):
        self._dc.value = False
        self._write(bytes([command]))
        if data:
            self._dc.value = True
            self._write(data)

    def _frame(self, pixels):
        if self._closed:
            raise ValueError("Display is closed")
        self._command(0x2A, self._x.to_bytes(2, "big") + (self._x + self.width - 1).to_bytes(2, "big"))
        self._command(0x2B, self._y.to_bytes(2, "big") + (self._y + self.height - 1).to_bytes(2, "big"))
        self._command(0x2C)
        self._dc.value = True
        self._write(pixels)

    def display(self, image):
        """@brief Send one native-size Pillow image as an atomic RGB565 frame."""
        if image.size != (self.width, self.height):
            raise ValueError("Image must match the display's current dimensions")
        pixels = rgb565(image.convert("RGB").tobytes())
        with self._lock:
            self._frame(pixels)

    def clear(self):
        """@brief Clear the display to black."""
        self.fill((0, 0, 0))

    def fill(self, color):
        """@brief Show a solid RGB color without requiring Pillow."""
        if len(color) != 3:
            raise ValueError("Color must contain three RGB channels")
        pixels = rgb565(bytes(color)) * (self.width * self.height)
        with self._lock:
            self._frame(pixels)

    def close(self):
        """@brief Switch backlight off and release all resources, including on error."""
        with self._lock:
            if not self._closed:
                self._closed = True
                try:
                    if hasattr(self, "_bl"):
                        self._bl.value = bool(self._bl_low)
                finally:
                    self._resources.close()
