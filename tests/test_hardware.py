"""@brief Hardware-independent checks for protocol, pin mapping and UI integration."""

from contextlib import ExitStack
import asyncio
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import aht30
import linux_gpio
import st7789


class SensorTests(unittest.TestCase):
    def setUp(self):
        self.resources = ExitStack()
        self.addCleanup(self.resources.close)
        self.resources.enter_context(patch.object(aht30.os, "open", return_value=41))
        self.close = self.resources.enter_context(patch.object(aht30.os, "close"))
        self.write = self.resources.enter_context(patch.object(aht30.os, "write", return_value=3))
        self.read = self.resources.enter_context(patch.object(aht30.os, "read"))
        self.ioctl = self.resources.enter_context(patch.object(aht30.fcntl, "ioctl"))
        self.resources.enter_context(patch.object(aht30.time, "sleep"))
        self.clock = self.resources.enter_context(patch.object(aht30.time, "monotonic", return_value=1.0))

    def test_crc_reference_and_paired_cached_measurement(self):
        self.assertEqual(aht30.crc8(bytes.fromhex("be ef")), 0x92)
        self.read.return_value = bytes.fromhex("18 80 00 06 00 00 23")
        sensor = aht30.AHT30()
        self.addCleanup(sensor.close)
        self.assertEqual(sensor.read(), (25.0, 50.0))
        self.assertEqual(sensor.read(), (25.0, 50.0))
        self.write.assert_called_once_with(41, b"\xac\x33\x00")
        self.ioctl.assert_called_once_with(41, 0x0703, 0x38)

    def test_crc_error_and_short_response(self):
        sensor = aht30.AHT30()
        self.addCleanup(sensor.close)
        self.read.return_value = bytes.fromhex("18 80 00 06 00 00 22")
        with self.assertRaisesRegex(OSError, "CRC"):
            sensor.read()
        self.read.return_value = b"\x18"
        with self.assertRaisesRegex(OSError, "Short"):
            sensor.read()

    def test_busy_timeout(self):
        sensor = aht30.AHT30()
        self.addCleanup(sensor.close)
        self.read.return_value = bytes.fromhex("98 80 00 06 00 00 00")
        self.clock.side_effect = [0.0, 0.3]
        with self.assertRaises(TimeoutError):
            sensor.read()

    def test_uncalibrated_sample_is_not_reported(self):
        data = bytes.fromhex("10 80 00 06 00 00")
        self.read.return_value = data + bytes([aht30.crc8(data)])
        sensor = aht30.AHT30()
        self.addCleanup(sensor.close)
        with self.assertRaisesRegex(OSError, "calibration"):
            sensor.read()

    def test_failed_address_claim_closes_descriptor(self):
        self.ioctl.side_effect = OSError("address busy")
        with self.assertRaises(OSError):
            aht30.AHT30()
        self.close.assert_called_once_with(41)


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

    def test_spi_bus_is_discovered_from_controller(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            devices = root / "devices"
            devices.mkdir()
            driver = root / "drivers" / "spidev"
            driver.mkdir(parents=True)
            for name, controller in (("spi7.0", "spi@fe640000"), ("spi3.0", "spi@fe620000")):
                node = root / controller / "spidev@0"
                node.mkdir(parents=True)
                device = devices / name
                device.mkdir()
                (device / "of_node").symlink_to(node)
                (device / "driver").symlink_to(driver)
            with patch.object(st7789, "SPI_DEVICES", devices):
                self.assertEqual(st7789.spi3_device(), "/dev/spidev7.0")


class ScreenTests(unittest.TestCase):
    def setUp(self):
        self.resources = ExitStack()
        self.addCleanup(self.resources.close)
        self.resources.enter_context(patch.dict(os.environ, {"AI_BOX_SPI_DEVICE": "/dev/spidev7.0"}, clear=True))
        self.spi = Mock()
        self.resources.enter_context(patch.dict(sys.modules, {"spidev": Mock(SpiDev=Mock(return_value=self.spi))}))
        self.resources.enter_context(patch.object(st7789.time, "sleep"))
        self.resources.enter_context(patch.object(st7789, "SPI_BUFFER_SIZE", Mock(read_text=Mock(return_value="4096"))))
        self.gpios = []

        def create_gpio(bank, offset, initial=None):
            gpio = Mock(value=initial)
            self.gpios.append(gpio)
            return gpio

        self.gpio = self.resources.enter_context(patch.object(st7789, "GPIO", side_effect=create_gpio))

    def test_rgb565_channel_order_and_endianness(self):
        colors = bytes.fromhex("ff0000 00ff00 0000ff ffffff")
        self.assertEqual(st7789.rgb565(colors), bytes.fromhex("f800 07e0 001f ffff"))
        with self.assertRaises(ValueError):
            st7789.rgb565(b"\x00")

    def test_hardware_cs_frame_size_chunks_and_release(self):
        screen = st7789.ST7789()
        self.addCleanup(screen.close)
        self.spi.open.assert_called_once_with(7, 0)
        self.assertFalse(self.spi.no_cs)
        self.assertEqual([call.args[:2] for call in self.gpio.call_args_list], [(4, 21), (1, 4), (3, 20)])
        self.spi.writebytes.reset_mock()
        screen.fill((255, 0, 0))
        writes = [call.args[0] for call in self.spi.writebytes.call_args_list]
        self.assertEqual(writes[:5], [[0x2A], [0, 0, 0, 239], [0x2B], [0, 0, 1, 63], [0x2C]])
        pixels = bytes(value for chunk in writes[5:] for value in chunk)
        self.assertEqual(pixels, b"\xf8\x00" * (240 * 320))
        self.assertTrue(all(len(chunk) <= 4096 for chunk in writes))
        screen.close()
        screen.close()
        self.assertFalse(self.gpios[2].value)
        self.spi.close.assert_called_once()
        for gpio in self.gpios:
            gpio.close.assert_called_once()

    def test_gpio_failure_releases_earlier_resources(self):
        dc, reset = Mock(), Mock()
        self.gpio.side_effect = [dc, reset, OSError("backlight busy")]
        with self.assertRaisesRegex(OSError, "backlight busy"):
            st7789.ST7789()
        dc.close.assert_called_once()
        reset.close.assert_called_once()
        self.spi.close.assert_called_once()

    def test_rotation_and_calibration_flags(self):
        with patch.dict(os.environ, {"AI_BOX_ROTATION": "90", "AI_BOX_BGR": "1", "AI_BOX_BL_ACTIVE_LOW": "1"}):
            screen = st7789.ST7789()
        self.addCleanup(screen.close)
        self.assertEqual((screen.width, screen.height), (320, 240))
        writes = [call.args[0] for call in self.spi.writebytes.call_args_list]
        madctl = writes.index([0x36])
        self.assertEqual(writes[madctl + 1], [0xA8])
        self.assertFalse(self.gpios[2].value)
        screen.close()
        self.assertTrue(self.gpios[2].value)


class ApplicationTests(unittest.TestCase):
    def test_streaming_response_accumulates_text_for_dict_like_objects(self):
        class Chunk:
            def __init__(self, text):
                self.text = text

            def __getitem__(self, key):
                if key != "message":
                    raise KeyError(key)
                return {"content": self.text}

        for filename in ("ALL_V2.py", "ai.py"):
            with self.subTest(filename=filename), ExitStack() as resources:
                resources.enter_context(patch.dict(sys.modules, {name: Mock() for name in ("vosk", "ollama", "pyaudio")}))
                spec = importlib.util.spec_from_file_location("ai_box_stream_test", Path(__file__).resolve().parents[1] / filename)
                application = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(application)
                application.ollama.chat.return_value = [Chunk("测"), Chunk("试")]
                show = resources.enter_context(patch.object(application, "show_on_display"))
                resources.enter_context(patch.object(application, "draw_face"))
                resources.enter_context(patch.object(application.time, "sleep"))
                resources.enter_context(patch.object(application.subprocess, "run"))
                resources.enter_context(patch("builtins.print"))
                asyncio.run(application.generate_and_play_text("测试"))
                self.assertEqual([call.args[0] for call in show.call_args_list], ["测", "测试"])

    def test_rendering_uses_native_rgb_frames(self):
        from PIL import ImageFont
        from display_ui import face_frame, menu_frame, text_frame

        font = ImageFont.truetype(os.environ.get("AI_BOX_TEST_FONT", "DejaVuSans.ttf"), 24)
        frames = [text_frame(240, 320, "Temperature\nHumidity", font),
                  menu_frame(240, 320, ["Light", "AI", "Weather"], 1, font)]
        frames.extend(face_frame(240, 320, state) for state in range(3))
        for frame in frames:
            self.assertEqual(frame.mode, "RGB")
            self.assertEqual(frame.size, (240, 320))
            self.assertIsNotNone(frame.getbbox())

    def test_weather_button_does_not_block_on_sensor(self):
        with patch.dict(sys.modules, {name: Mock() for name in ("vosk", "ollama", "pyaudio")}):
            spec = importlib.util.spec_from_file_location("ai_box_main", Path(__file__).resolve().parents[1] / "ALL_V2.py")
            application = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(application)
        application.sensor = Mock()
        application.shared_data["main_index"] = 2
        application.on_center_press()
        self.assertTrue(application.shared_data["temp_running"])
        application.sensor.read.assert_not_called()
        application.on_center_press()
        self.assertFalse(application.shared_data["temp_running"])


if __name__ == "__main__":
    unittest.main()
