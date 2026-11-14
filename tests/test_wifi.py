"""! @brief Check network parsing, secret handling, recovery and touchscreen input."""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import ImageFont

from ai_box import wifi
from ai_box.app import Application


class WifiTests(unittest.TestCase):
    def test_scan_unescapes_names_deduplicates_and_finds_saved_profile(self):
        def output(*args, **kwargs):
            if "wifi" in args:
                return SimpleNamespace(returncode=0, stdout=(
                    r":Cafe\:A:30:WPA2" + "\n" + r"*:Cafe\:A:60:WPA2" + "\n"))
            if "UUID,TYPE" in args:
                return SimpleNamespace(returncode=0, stdout="123:802-11-wireless\n")
            return SimpleNamespace(returncode=0, stdout=r"Cafe\:A" + "\n")

        with patch.object(wifi, "_nmcli", side_effect=output):
            self.assertEqual(wifi.scan_networks(), [{"ssid": "Cafe:A", "signal": 60,
                             "security": "WPA2", "active": True, "uuid": "123"}])

    def test_password_is_sent_on_stdin_and_failed_connection_restores_previous(self):
        results = [SimpleNamespace(returncode=0, stdout="old-uuid\n"),
                   SimpleNamespace(returncode=1), SimpleNamespace(returncode=0)]
        network = {"ssid": "new-network", "uuid": None}
        with patch.object(wifi, "_nmcli", side_effect=results) as command:
            self.assertFalse(wifi.connect_network(network, "secret123"))
        self.assertNotIn("secret123", command.call_args_list[1].args)
        self.assertEqual(command.call_args_list[1].kwargs["input_text"], "secret123\n")
        self.assertIn("old-uuid", command.call_args_list[2].args)

    def test_password_keyboard_and_menu_are_touch_operated(self):
        display = Mock(width=800, height=480)
        screen = SimpleNamespace(display=display, font=ImageFont.truetype("DejaVuSans.ttf", 32))
        panel = wifi.WifiPanel(screen)
        panel.active = True
        panel.networks = [{"ssid": "Example", "signal": 80, "security": "WPA2",
                           "active": False, "uuid": None}]
        panel.touch(100, 90)
        self.assertEqual(panel.mode, "password")
        panel.touch(20, 130)
        self.assertEqual(panel.password, "1")
        panel.touch(10, 450)
        panel.touch(20, 210)
        self.assertEqual(panel.password, "1Q")
        panel.touch(145, 450)
        panel.touch(20, 130)
        self.assertEqual(panel.password, "1Q!")
        panel.password = "validpass"
        with patch.object(panel, "_start_connect_locked") as connect:
            panel.touch(600, 450)
            connect.assert_called_once_with(panel.selected, "validpass")
        panel.touch(780, 450)
        self.assertEqual(panel.mode, "list")
        self.assertEqual(panel.password, "")

    def test_network_panel_is_available_from_the_menu(self):
        panel = Mock()
        panel.active = False
        app = Application(Mock(), [], rotate=Mock(), network=panel)
        app.move(3)
        app.select()
        panel.open.assert_called_once()


if __name__ == "__main__":
    unittest.main()
