"""@brief Independent hardware checks without UI, font or AI dependencies."""

from contextlib import closing
import time


def check_sensor():
    """@brief Print a paired AHT30 measurement every two seconds."""
    from .hardware.aht30 import AHT30

    with closing(AHT30()) as sensor:
        while True:
            temperature, humidity = sensor.read()
            print("Temperature: {:.1f} C  Humidity: {:.1f} %".format(
                temperature, humidity), flush=True)
            time.sleep(2)


def check_screen():
    """@brief Display red, green, blue and white, then switch the backlight off."""
    from .hardware.st7789 import ST7789

    with closing(ST7789()) as display:
        for name, color in (("red", (255, 0, 0)), ("green", (0, 255, 0)),
                            ("blue", (0, 0, 255)), ("white", (255, 255, 255))):
            print("Screen should be " + name, flush=True)
            display.fill(color)
            time.sleep(2)


def check_led():
    """@brief Blink the original GPIO0_B7 LED and leave it off when exiting."""
    from .hardware.gpio import GPIO

    with closing(GPIO(0, 15, initial=False)) as led:
        try:
            while True:
                for enabled in (True, False):
                    led.value = enabled
                    print("on" if enabled else "off", flush=True)
                    time.sleep(5)
        finally:
            led.value = False
