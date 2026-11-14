"""! @brief Check online weather, caching and integration with the menu and voice."""

from datetime import datetime, timedelta, timezone
import io
import json
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.error import URLError

from ai_box.app import Application
from ai_box.weather import Forecast, forecast_text


def sample_forecast():
    """! @brief Return representative Chengdu conditions for today and tomorrow."""
    today = datetime.now(timezone(timedelta(hours=8))).date()
    return {
        "current": {"temperature_2m": 21, "relative_humidity_2m": 70, "weather_code": 2},
        "daily": {"time": [today.isoformat(), (today + timedelta(days=1)).isoformat()],
                  "weather_code": [2, 63], "temperature_2m_min": [18, 17],
                  "temperature_2m_max": [25, 23], "precipitation_probability_max": [20, 80]},
    }


class ForecastTests(unittest.TestCase):
    def test_fetch_cache_and_tomorrow_format(self):
        data = sample_forecast()
        with patch("ai_box.weather.urlopen", return_value=io.BytesIO(json.dumps(data).encode())) as request:
            forecast = Forecast()
            self.assertEqual(forecast.get(), data)
            self.assertEqual(forecast.get(), data)
        request.assert_called_once()
        self.assertIn("成都现在多云", forecast_text(data))
        self.assertIn("成都明天中雨", forecast_text(data, tomorrow=True))
        self.assertIn("降水概率 80%", forecast_text(data, tomorrow=True))

    def test_offline_and_incomplete_forecast_report_unavailable(self):
        for response in (URLError("offline"), io.BytesIO(b'{"current": {}}')):
            with self.subTest(response=response), patch("ai_box.weather.urlopen") as request:
                if isinstance(response, Exception):
                    request.side_effect = response
                else:
                    request.return_value = response
                forecast = Forecast()
                self.assertIsNone(forecast.get())
                self.assertIsNone(forecast.get())
                self.assertEqual(request.call_count, 2 if isinstance(response, Exception) else 1)
        self.assertIn("不可用", forecast_text(None))

    def test_temporary_network_failure_is_retried(self):
        data = sample_forecast()
        with patch("ai_box.weather.urlopen", side_effect=[URLError("timeout"),
                   io.BytesIO(json.dumps(data).encode())]) as request:
            self.assertEqual(Forecast().get(), data)
        self.assertEqual(request.call_count, 2)

    def test_failed_page_refresh_retries_after_fifteen_seconds(self):
        application = Application(Mock(), [])
        application._forecast.get = Mock(return_value=None)
        with patch("ai_box.app.time.monotonic", return_value=100):
            application._update_forecast()
        self.assertEqual(application._forecast_next, 115)

    def test_voice_weather_uses_online_data(self):
        screen = Mock()
        application = Application(screen, [])
        application._forecast.get = Mock(return_value=sample_forecast())
        application._voice = Mock()
        self.assertTrue(application.handle_voice_command("明 天 天 气 怎么样"))
        self.assertIn("成都明天中雨", application._voice.speak.call_args.args[0])
        self.assertFalse(application.handle_voice_command("室内温度"))

    def test_weather_fetch_does_not_block_navigation(self):
        screen = Mock()
        application = Application(screen, [])
        started, release = threading.Event(), threading.Event()

        def get_forecast():
            started.set()
            release.wait(3)
            return sample_forecast()

        application._forecast.get = get_forecast
        application.move(1)
        application.select()
        try:
            application.render()
            self.assertTrue(started.wait(1))
            application.move(-1)
            application.render()
            screen.menu.assert_called_with(application.main_menu, 0)
        finally:
            release.set()
            application._forecast_thread.join(3)
        self.assertFalse(application.weather)


if __name__ == "__main__":
    unittest.main()
