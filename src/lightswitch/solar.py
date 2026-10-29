"""日出/日落计算与切换判定（NOAA 太阳位置近似，无网络依赖）。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone, tzinfo

ZENITH = 90.833


@dataclass(frozen=True)
class SunTimes:
    sunrise: datetime | None
    sunset: datetime | None
    kind: str


def _event(day_of_year: int, latitude: float, longitude: float, rising: bool) -> tuple[float, float]:
    """返回该事件的 UTC 小时数与太阳时角余弦；余弦超出 [-1,1] 说明当日不升或不落。"""
    lng_hour = longitude / 15.0
    t = day_of_year + ((6.0 if rising else 18.0) - lng_hour) / 24.0
    m = 0.9856 * t - 3.289
    l = (m + 1.916 * math.sin(math.radians(m)) + 0.020 * math.sin(math.radians(2 * m)) + 282.634) % 360.0
    sin_dec = 0.39782 * math.sin(math.radians(l))
    cos_dec = math.cos(math.asin(sin_dec))
    cos_h = (math.cos(math.radians(ZENITH)) - sin_dec * math.sin(math.radians(latitude))) / (
        cos_dec * math.cos(math.radians(latitude))
    )
    if not -1.0 <= cos_h <= 1.0:
        return (0.0, cos_h)
    ra = math.degrees(math.atan(0.91764 * math.tan(math.radians(l)))) % 360.0
    ra += (math.floor(l / 90.0) * 90.0) - (math.floor(ra / 90.0) * 90.0)
    ra /= 15.0
    h = (360.0 - math.degrees(math.acos(cos_h))) if rising else math.degrees(math.acos(cos_h))
    ut = (((h / 15.0) + ra - 0.06571 * t - 6.622) - lng_hour) % 24.0
    return (ut, cos_h)


def _place(day: date, ut_hours: float, longitude: float, tz: tzinfo) -> datetime:
    """把 UTC 小时还原成绝对时刻：在 ±1 天的三个候选中，取最靠近该地当日太阳正午的那个。

    NOAA 的 UT 结果落在 [0,24) 内，东经站点的事件会被折到次日、西经站点会被折回前日；
    用太阳正午做锚点比按显示时区的日期硬夹正确，显示时区与站点时区不同时也不会把日出日落颠倒。
    """
    noon_ut = 12.0 - longitude / 15.0
    chosen = min((ut_hours + 24 * k for k in (-1, 0, 1)), key=lambda hour: abs(hour - noon_ut))
    base = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    return (base + timedelta(hours=chosen)).astimezone(tz)


def sun_times(day: date, latitude: float, longitude: float, tz: tzinfo) -> SunTimes:
    """返回该日当地时区的日出、日落；极昼极夜时两者为 None 并由 kind 标记。"""
    day_of_year = day.timetuple().tm_yday
    rise_ut, cos_h = _event(day_of_year, latitude, longitude, True)
    if cos_h > 1.0:
        return SunTimes(None, None, "polar_night")
    if cos_h < -1.0:
        return SunTimes(None, None, "polar_day")
    drop_ut, _ = _event(day_of_year, latitude, longitude, False)
    return SunTimes(_place(day, rise_ut, longitude, tz), _place(day, drop_ut, longitude, tz), "normal")


def solar_noon(day: date, longitude: float, tz: tzinfo) -> datetime:
    """该地在给定日期、把太阳正午换算到 tz 后的钟点；用于核对坐标与机器时区是否自洽。"""
    return _place(day, 12.0 - longitude / 15.0, longitude, tz)


def noon_offset_hours(noon: datetime) -> float:
    """太阳正午偏离 12:00 的小时数，按 12 小时环绕取值。"""
    delta = abs((noon.hour + noon.minute / 60 + noon.second / 3600) - 12.0)
    return min(delta, 24.0 - delta)



def decide(now: datetime, times: SunTimes, buffer_minutes: int = 0) -> str:
    """浅色区间为 [日出+N, 日落-N)；缓冲分钟数对调两侧边界。"""
    if times.kind == "polar_day":
        return "light"
    if times.kind == "polar_night":
        return "dark"
    assert times.sunrise and times.sunset
    rise = times.sunrise + timedelta(minutes=buffer_minutes)
    drop = times.sunset - timedelta(minutes=buffer_minutes)
    return "light" if rise <= now < drop else "dark"


def next_change(
    now: datetime, times: SunTimes, buffer_minutes: int = 0, current: str | None = None
) -> tuple[datetime, str] | None:
    """下一次会改变主题的时刻与目标；current 与事件目标相同的事件会被跳过。"""
    if times.kind != "normal":
        return None
    assert times.sunrise and times.sunset
    rise = times.sunrise + timedelta(minutes=buffer_minutes)
    drop = times.sunset - timedelta(minutes=buffer_minutes)
    for moment, variant in ((rise, "light"), (drop, "dark")):
        if moment > now and variant != current:
            return moment, variant
    return None
