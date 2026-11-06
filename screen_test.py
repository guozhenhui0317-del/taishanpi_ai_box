"""@brief Display red, green, blue and white using only spidev and the stdlib."""

from contextlib import closing
import time

from st7789 import ST7789


def main():
    """@brief Check wiring/color order and release backlight/GPIOs on exit."""
    try:
        with closing(ST7789()) as display:
            for name, color in (("red", (255, 0, 0)), ("green", (0, 255, 0)),
                                ("blue", (0, 0, 255)), ("white", (255, 255, 255))):
                print("Screen should be " + name, flush=True)
                display.fill(color)
                time.sleep(2)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
