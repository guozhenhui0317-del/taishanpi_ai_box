"""! @brief Obtain and briefly cache the Chengdu weather forecast."""

from datetime import datetime, timedelta, timezone
import json
import threading
import time
from urllib.request import urlopen


URL = ("https://api.open-meteo.com/v1/forecast?latitude=30.67&longitude=104.06"
       "&current=temperature_2m,relative_humidity_2m,weather_code"
       "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
       "&timezone=Asia%2FShanghai&forecast_days=2")
FALLBACK_URL = "https://wttr.in/30.67,104.06?format=j1"
FALLBACK_CONDITIONS = {
    113: "晴", 116: "晴间多云", 119: "多云", 122: "阴", 143: "薄雾", 149: "烟霾",
    176: "局部阵雨", 179: "局部阵雪", 182: "局部雨夹雪", 185: "局部冻雨",
    200: "局部雷暴", 227: "风雪", 230: "暴风雪", 248: "雾", 260: "冻雾",
    263: "小毛毛雨", 266: "毛毛雨", 281: "冻毛毛雨", 284: "冻毛毛雨",
    293: "局部小雨", 296: "小雨", 299: "局部中雨", 302: "中雨",
    305: "局部大雨", 308: "大雨", 311: "小冻雨", 314: "冻雨",
    317: "雨夹雪", 320: "雨夹雪", 323: "局部小雪", 326: "小雪",
    329: "局部中雪", 332: "中雪", 335: "局部大雪", 338: "大雪",
    350: "冰粒", 353: "小阵雨", 356: "中到大阵雨", 359: "暴雨",
    362: "小阵雨夹雪", 365: "阵雨夹雪", 368: "小阵雪", 371: "大阵雪",
    374: "小冰雹", 377: "冰雹", 386: "局部雷雨", 389: "雷雨",
    392: "局部雷阵雪", 395: "雷阵雪",
}
CONDITIONS = {
    0: "晴", 1: "晴间多云", 2: "多云", 3: "阴", 45: "雾", 48: "雾凇",
    51: "小毛毛雨", 53: "毛毛雨", 55: "大毛毛雨", 56: "小冻毛毛雨", 57: "冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨", 66: "小冻雨", 67: "冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒",
    80: "小阵雨", 81: "阵雨", 82: "强阵雨", 85: "小阵雪", 86: "大阵雪",
    95: "雷暴", 96: "雷暴伴小冰雹", 97: "强雷暴", 99: "雷暴伴大冰雹",
}


def _fallback_forecast(data):
    """! @brief Convert wttr.in's Chengdu forecast to the shared weather format.
    @param data JSON response, possibly wrapped in a data object.
    @return Current conditions and two days of normalized forecasts.
    """
    data = data.get("data", data)
    current = data["current_condition"][0]
    days = data["weather"][:2]
    if len(days) != 2:
        raise ValueError("备用天气数据不足两天")
    daily = {"time": [], "weather_code": [], "condition_text": [],
             "temperature_2m_min": [], "temperature_2m_max": [],
             "precipitation_probability_max": []}
    for day in days:
        hourly = day["hourly"]
        noon = min(hourly, key=lambda item: abs(int(item["time"]) - 1200))
        daily["time"].append(day["date"])
        daily["weather_code"].append(int(noon["weatherCode"]))
        daily["condition_text"].append(FALLBACK_CONDITIONS.get(int(noon["weatherCode"]), "天气未知"))
        daily["temperature_2m_min"].append(float(day["mintempC"]))
        daily["temperature_2m_max"].append(float(day["maxtempC"]))
        daily["precipitation_probability_max"].append(max(int(item["chanceofrain"]) for item in hourly))
    code = int(current["weatherCode"])
    return {"current": {"temperature_2m": float(current["temp_C"]),
                        "relative_humidity_2m": int(current["humidity"]),
                        "weather_code": code,
                        "condition_text": FALLBACK_CONDITIONS.get(code, "天气未知")},
            "daily": daily, "_daily_label": "中午", "_chance_label": "分时最高降雨概率"}


def _validate_forecast(data, today):
    """! @brief Validate all fields needed by the screen and voice.
    @param data Forecast data in the shared format.
    @param today Current Chengdu date.
    """
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


class Forecast:
    """! @brief Fetch Chengdu forecasts with fallback and clearly marked cached data."""

    def __init__(self):
        """! @brief Initialize the shared forecast cache."""
        self._lock = threading.Lock()
        self._data = None
        self._expires = 0
        self._updated = 0
        self._preferred = URL

    def get(self, force=False):
        """! @brief Fetch the forecast or return clearly marked recent cached data.
        @param force Bypass the cache when the weather page is opened.
        @return Parsed forecast data, or None if no recent data is available.
        """
        with self._lock:
            now = time.monotonic()
            today = datetime.now(timezone(timedelta(hours=8))).date()
            if not force and now < self._expires and (
                    self._data is None or self._data["daily"]["time"][0] == today.isoformat()):
                return self._data
            sources = [(URL, "Open-Meteo", 4), (FALLBACK_URL, "wttr.in", 8)]
            sources.sort(key=lambda source: source[0] != self._preferred)
            for url, source, timeout in sources:
                try:
                    with urlopen(url, timeout=timeout) as response:
                        data = json.load(response)
                    if url == FALLBACK_URL:
                        data = _fallback_forecast(data)
                    _validate_forecast(data, today)
                    data["_source"] = source
                    data["_queried"] = datetime.now(timezone(timedelta(hours=8))).strftime("%m-%d %H:%M")
                    self._data = data
                    self._updated = time.monotonic()
                    self._expires = self._updated + 600
                    self._preferred = url
                    print("成都天气查询成功：{}".format(source), flush=True)
                    return self._data
                except (OSError, ValueError, TypeError, KeyError, IndexError) as error:
                    print("成都天气源 {} 查询失败: {}".format(source, error), flush=True)
            self._expires = time.monotonic() + 15
            if (self._data is not None and time.monotonic() - self._updated <= 6 * 3600 and
                    self._data["daily"]["time"][:2] ==
                    [today.isoformat(), (today + timedelta(days=1)).isoformat()]):
                self._data = dict(self._data, _stale=True)
                return self._data
            self._data = None
            return None


def forecast_text(data, tomorrow=False, show_details=False):
    """! @brief Format a Chengdu forecast, marking cached data and its source.
    @param data Parsed forecast, or None if the request failed.
    @param tomorrow True to show tomorrow's forecast instead of current conditions.
    @param show_details Include source and query time on the weather page.
    @return Human-readable weather information.
    """
    if data is None:
        return "成都天气暂不可用\n天气服务无响应，请稍后重试"
    daily = data["daily"]
    index = 1 if tomorrow else 0
    label = ("明天" if tomorrow else "今天") + data.get("_daily_label", "")
    conditions = daily.get("condition_text")
    condition = conditions[index] if conditions else CONDITIONS.get(daily["weather_code"][index], "天气未知")
    chance_label = data.get("_chance_label", "降水概率")
    result = "成都{}{}\n气温 {:.0f}到{:.0f}摄氏度\n{} {}%".format(
        label, condition, daily["temperature_2m_min"][index],
        daily["temperature_2m_max"][index], chance_label, daily["precipitation_probability_max"][index])
    if not tomorrow:
        current = data["current"]
        current_condition = current.get("condition_text", CONDITIONS.get(current["weather_code"], "天气未知"))
        result = "成都现在{} {:.0f}摄氏度\n湿度 {}%\n".format(
            current_condition, current["temperature_2m"], current["relative_humidity_2m"]) + result
    if data.get("_stale"):
        result = "更新失败，以下为缓存\n" + result
    if (show_details or data.get("_stale")) and data.get("_queried"):
        result += "\n上次查询 {}".format(data["_queried"])
    if show_details and data.get("_source"):
        result += "\n来源 {}".format(data["_source"])
    return result
