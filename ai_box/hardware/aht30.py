"""@brief AHT30 I2C measurements with CRC, calibrated-status checks and timeout."""

import fcntl
import os
import threading
import time


def crc8(data):
    """@brief Calculate the AHT30 CRC-8 (polynomial 0x31, initial value 0xFF)."""
    crc = 0xFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ (0x31 if crc & 0x80 else 0)) & 0xFF
    return crc


class AHT30:
    """@brief Read an AHT30 at 7-bit address 0x38 through Linux i2c-dev."""

    def __init__(self, device=None):
        device = device or os.environ.get("AI_BOX_I2C_DEVICE", "/dev/i2c-2")
        self._lock = threading.Lock()
        self._sample = None
        self._sample_time = 0.0
        self._fd = os.open(device, os.O_RDWR)
        try:
            fcntl.ioctl(self._fd, 0x0703, 0x38)
            time.sleep(0.005)
        except Exception:
            os.close(self._fd)
            self._fd = None
            raise

    def read(self):
        """@brief Return (degrees Celsius, percent RH), caching for two seconds."""
        with self._lock:
            if self._fd is None:
                raise ValueError("AHT30 is closed")
            if self._sample is not None and time.monotonic() - self._sample_time < 2:
                return self._sample
            if os.write(self._fd, b"\xac\x33\x00") != 3:
                raise OSError("Short AHT30 measurement command")
            deadline = time.monotonic() + 0.25
            time.sleep(0.080)
            while True:
                data = os.read(self._fd, 7)
                if len(data) != 7:
                    raise OSError("Short AHT30 measurement response")
                if not data[0] & 0x80:
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError("AHT30 measurement remained busy")
                time.sleep(0.010)
            if crc8(data[:6]) != data[6]:
                raise OSError("AHT30 measurement CRC mismatch")
            if data[0] & 0x18 != 0x18:
                raise OSError("AHT30 calibration or OTP integrity check failed")
            humidity = ((data[1] << 12) | (data[2] << 4) | (data[3] >> 4)) * 100 / 1048576
            temperature = (((data[3] & 0x0F) << 16) | (data[4] << 8) | data[5]) * 200 / 1048576 - 50
            self._sample = temperature, humidity
            self._sample_time = time.monotonic()
            return self._sample

    def close(self):
        """@brief Close the I2C descriptor after any in-progress read."""
        with self._lock:
            if self._fd is not None:
                os.close(self._fd)
                self._fd = None
