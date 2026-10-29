import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

from lightswitch import solar

BEIJING = (39.89455, 116.35983)
TROMSO = (69.6492, 18.9553)
SYDNEY = (-33.8688, 151.2093)
SHANGHAI = ZoneInfo("Asia/Shanghai")


class SunTimesTest(unittest.TestCase):
    def test_matches_open_meteo_for_beijing(self):
        times = solar.sun_times(date(2026, 10, 29), *BEIJING, SHANGHAI)
        self.assertEqual(times.kind, "normal")
        self.assertEqual(times.sunrise.strftime("%H:%M"), "06:39")
        self.assertEqual(times.sunset.strftime("%H:%M"), "17:16")

    def test_southern_hemisphere_day_is_ordered(self):
        times = solar.sun_times(date(2026, 10, 29), *SYDNEY, ZoneInfo("Australia/Sydney"))
        self.assertLess(times.sunrise, times.sunset)
        self.assertTrue(5 <= times.sunrise.hour <= 7, times.sunrise)
        self.assertTrue(18 <= times.sunset.hour <= 21, times.sunset)

    def test_polar_day_and_night(self):
        day = solar.sun_times(date(2026, 6, 21), *TROMSO, ZoneInfo("Europe/Oslo"))
        night = solar.sun_times(date(2026, 12, 21), *TROMSO, ZoneInfo("Europe/Oslo"))
        self.assertEqual(day.kind, "polar_day")
        self.assertEqual(night.kind, "polar_night")
        self.assertIsNone(day.sunrise)

    def test_dst_day_stays_local(self):
        tz = ZoneInfo("America/New_York")
        times = solar.sun_times(date(2026, 11, 1), 40.7128, -74.0060, tz)
        self.assertEqual(times.sunrise.utcoffset().total_seconds(), -5 * 3600)
        self.assertTrue(6 <= times.sunrise.hour <= 7, times.sunrise)


class DecideTest(unittest.TestCase):
    def setUp(self):
        self.times = solar.SunTimes(
            datetime(2026, 10, 29, 6, 39, tzinfo=SHANGHAI),
            datetime(2026, 10, 29, 17, 16, tzinfo=SHANGHAI),
            "normal",
        )

    def test_boundaries_are_inclusive_at_sunrise(self):
        at = lambda h, m: datetime(2026, 10, 29, h, m, tzinfo=SHANGHAI)
        self.assertEqual(solar.decide(at(6, 38), self.times), "dark")
        self.assertEqual(solar.decide(at(6, 39), self.times), "light")
        self.assertEqual(solar.decide(at(17, 15), self.times), "light")
        self.assertEqual(solar.decide(at(17, 16), self.times), "dark")

    def test_buffer_delays_light_and_advances_dark(self):
        at = lambda h, m: datetime(2026, 10, 29, h, m, tzinfo=SHANGHAI)
        self.assertEqual(solar.decide(at(7, 8), self.times, 30), "dark")
        self.assertEqual(solar.decide(at(7, 9), self.times, 30), "light")
        self.assertEqual(solar.decide(at(16, 45), self.times, 30), "light")
        self.assertEqual(solar.decide(at(16, 46), self.times, 30), "dark")

    def test_polar_kinds_force_variant(self):
        polar_day = solar.SunTimes(None, None, "polar_day")
        polar_night = solar.SunTimes(None, None, "polar_night")
        now = datetime(2026, 6, 21, 12, tzinfo=ZoneInfo("Europe/Oslo"))
        self.assertEqual(solar.decide(now, polar_day), "light")
        self.assertEqual(solar.decide(now, polar_night), "dark")

    def test_next_change_reports_todays_sunset(self):
        now = datetime(2026, 10, 29, 12, 0, tzinfo=SHANGHAI)
        moment, variant = solar.next_change(now, self.times)
        self.assertEqual(variant, "dark")
        self.assertEqual(moment.hour, 17)
        self.assertEqual(moment.minute, 16)

    def test_next_change_skips_events_that_keep_current_variant(self):
        now = datetime(2026, 10, 29, 12, 0, tzinfo=SHANGHAI)
        self.assertEqual(solar.next_change(now, self.times, current="light")[1], "dark")
        self.assertIsNone(solar.next_change(now, self.times, current="dark"))


if __name__ == "__main__":
    unittest.main()
