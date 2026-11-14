"""! @brief Obtain and briefly cache the Chengdu weather forecast."""

from datetime import datetime, timedelta, timezone
import json
import threading
import time
from urllib.error import HTTPError
from urllib.request import urlopen


URL = ("https://api.open-meteo.com/v1/forecast?latitude=30.67&longitude=104.06"
       "&current=temperature_2m,relative_humidity_2m,weather_code"
       "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
       "&timezone=Asia%2FShanghai&forecast_days=2")
CONDITIONS = {
    0: "晴", 1: "晴间多云", 2: "多云", 3: "阴", 45: "雾", 48: "雾凇",
    51: "小毛毛雨", 53: "毛毛雨", 55: "大毛毛雨", 56: "小冻毛毛雨", 57: "冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨", 66: "小冻雨", 67: "冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒",
    80: "小阵雨", 81: "阵雨", 82: "强阵雨", 85: "小阵雪", 86: "大阵雪",
    95: "雷暴", 96: "雷暴伴小冰雹", 97: "强雷暴", 99: "雷暴伴大冰雹",
}


class Forecast:
    """! @brief Fetch Chengdu forecasts, sharing cached results between callers."""

    def __init__(self):
        """! @brief Initialize the shared forecast cache."""
        self._lock = threading.Lock()
        self._data = None
        self._expires = 0

    def get(self):
        """! @brief Return current conditions and two days of forecasts.
        @return Parsed forecast data, or None when the service is unavailable.
        """
        with self._lock:
            today = datetime.now(timezone(timedelta(hours=8))).date()
            if time.monotonic() < self._expires and (
                    self._data is None or self._data["daily"]["time"][0] == today.isoformat()):
                return self._data
            try:
                for attempt in range(2):
                    try:
                        with urlopen(URL, timeout=8) as response:
                            data = json.load(response)
                        break
                    except HTTPError:
                        raise
                    except OSError:
                        if attempt:
                            raise
                current, daily = data["current"], data["daily"]
                float(current["temperature_2m"])
                float(current["relative_humidity_2m"])
                int(current["weather_code"])
                for index in (0, 1):
                    int(daily["weather_code"][index])
                    float(daily["temperature_2m_max"][index])
                    float(daily["temperature_2m_min"][index])
                    int(daily["precipitation_probability_max"][index])
                if daily["time"][:2] != [today.isoformat(), (today + timedelta(days=1)).isoformat()]:
                    raise ValueError("forecast dates do not match today and tomorrow")
                self._data = data
                self._expires = time.monotonic() + 600
                print("成都天气查询成功", flush=True)
            except (OSError, ValueError, TypeError, KeyError, IndexError) as error:
                print("成都天气查询失败: {}".format(error), flush=True)
                self._data = None
                self._expires = time.monotonic() + (60 if isinstance(error, HTTPError) else 15)
            return self._data


def forecast_text(data, tomorrow=False):
    """! @brief Format a Chengdu forecast for the screen and speech.
    @param data Parsed forecast, or None if the request failed.
    @param tomorrow True to show tomorrow's forecast instead of current conditions.
    @return Human-readable weather information.
    """
    if data is None:
        return "成都天气暂不可用\n请检查网络或稍后再试"
    daily = data["daily"]
    index = 1 if tomorrow else 0
    label = "明天" if tomorrow else "今天"
    condition = CONDITIONS.get(daily["weather_code"][index], "天气未知")
    result = "成都{}{}\n气温 {:.0f}到{:.0f}摄氏度\n降水概率 {}%".format(
        label, condition, daily["temperature_2m_min"][index],
        daily["temperature_2m_max"][index], daily["precipitation_probability_max"][index])
    if tomorrow:
        return result
    current = data["current"]
    return "成都现在{} {:.0f}摄氏度\n湿度 {}%\n".format(
        CONDITIONS.get(current["weather_code"], "天气未知"),
        current["temperature_2m"], current["relative_humidity_2m"]) + result
