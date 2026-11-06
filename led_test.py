import board
import digitalio
import time

led = digitalio.DigitalInOut(board.GPIO0_B7)
led.direction = digitalio.Direction.OUTPUT

try:
    while True:
        led.value=1
        print("on")
        time.sleep(5)
        print("off")
        led.value=0
        time.sleep(5)

finally:
    led.value = False
    led.deinit()
