"""@brief Read paired AHT30 measurements without AI or display dependencies."""

from contextlib import closing
import time

from aht30 import AHT30


def main():
    """@brief Print temperature/humidity every two seconds and close I2C on exit."""
    try:
        with closing(AHT30()) as sensor:
            while True:
                temperature, humidity = sensor.read()
                print("Temperature: {:.1f} C  Humidity: {:.1f} %".format(temperature, humidity), flush=True)
                time.sleep(2)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
