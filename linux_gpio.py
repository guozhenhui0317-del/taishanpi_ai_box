"""@brief Linux sysfs GPIO access using bank labels and bank-local offsets."""

import errno
import os
from pathlib import Path


GPIO_ROOT = Path("/sys/class/gpio")


def gpio_number(bank, offset):
    """@brief Resolve a Rockchip bank/offset without assuming gpiochip numbering."""
    matches = [chip for chip in GPIO_ROOT.glob("gpiochip*")
               if (chip / "label").read_text().strip() == "gpio{}".format(bank)]
    if len(matches) != 1:
        raise OSError("Cannot uniquely find GPIO bank {} in {}".format(bank, GPIO_ROOT))
    chip = matches[0]
    if not 0 <= offset < int((chip / "ngpio").read_text()):
        raise ValueError("GPIO offset outside bank")
    return int((chip / "base").read_text()) + offset


class GPIO:
    """@brief Own one sysfs GPIO; initial=None selects input, otherwise output."""

    def __init__(self, bank, offset, initial=None):
        self._number = gpio_number(bank, offset)
        self._fd = None
        self._output = initial is not None
        self._owned = False
        path = GPIO_ROOT / "gpio{}".format(self._number)
        if path.exists():
            raise OSError(errno.EBUSY, "GPIO already exported; check its owner", str(path))
        (GPIO_ROOT / "export").write_text(str(self._number))
        self._owned = True
        try:
            direction = "in" if initial is None else ("high" if initial else "low")
            (path / "direction").write_text(direction)
            self._fd = os.open(str(path / "value"), os.O_RDWR)
        except Exception:
            self.close()
            raise

    @property
    def value(self):
        """@brief Read the physical GPIO level."""
        if self._fd is None:
            raise ValueError("GPIO is closed")
        os.lseek(self._fd, 0, os.SEEK_SET)
        return os.read(self._fd, 1) == b"1"

    @value.setter
    def value(self, level):
        """@brief Set the physical level of an output GPIO."""
        if self._fd is None or not self._output:
            raise ValueError("GPIO is closed or configured as input")
        os.lseek(self._fd, 0, os.SEEK_SET)
        os.write(self._fd, b"1" if level else b"0")

    def close(self):
        """@brief Release only the GPIO exported by this instance."""
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        if self._owned:
            (GPIO_ROOT / "unexport").write_text(str(self._number))
            self._owned = False
