"""! @brief Hardware-independent checks for protocol, pin mapping and UI integration."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from ai_box.hardware import gpio as linux_gpio


class DiscoveryTests(unittest.TestCase):
    def test_gpio_mapping_uses_label_and_reported_base(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, label, base in (("gpiochip900", "gpio4", 320), ("gpiochip7", "gpio1", 64)):
                chip = root / name
                chip.mkdir()
                (chip / "label").write_text(label)
                (chip / "base").write_text(str(base))
                (chip / "ngpio").write_text("32")
            with patch.object(linux_gpio, "GPIO_ROOT", root):
                self.assertEqual(linux_gpio.gpio_number(4, 21), 341)
                self.assertEqual(linux_gpio.gpio_number(1, 4), 68)
                with self.assertRaises(OSError):
                    linux_gpio.gpio_number(3, 20)
                with self.assertRaises(ValueError):
                    linux_gpio.gpio_number(4, 32)



if __name__ == "__main__":
    unittest.main()
