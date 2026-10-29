import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

from lightswitch import solar

PARIS = (48.8566, 2.3522)
PARIS_TZ = ZoneInfo("Europe/Paris")
TROMSO = (69.6492, 18.9553)
SYDNEY = (-33.8688, 151.2093)


class SunTimesTest(unittest.TestCase):
    def test_matches_reference_dataset(self):
        times = solar.sun_times(date(2026, 10, 29), *PARIS, PARIS_TZ)
        self.assertEqual(times.kind, "normal")
        self.assertEqual(times.sunrise.strftime("%H:%M"), "07:32")
        self.assertEqual(times.sunset.strftime("%H:%M"), "17:35")

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

    def test_site_far_from_machine_timezone_stays_ordered(self):
        times = solar.sun_times(date(2026, 10, 29), 34.0504, -118.2430, PARIS_TZ)
        self.assertLess(times.sunrise, times.sunset)
        noon = solar.solar_noon(date(2026, 10, 29), -118.2430, PARIS_TZ)
        self.assertGreater(solar.noon_offset_hours(noon), 4)

    def test_sydney_sunrise_lands_on_requested_local_day(self):
        times = solar.sun_times(date(2026, 10, 29), *SYDNEY, ZoneInfo("Australia/Sydney"))
        self.assertEqual(times.sunrise.date(), date(2026, 10, 29))
        self.assertEqual(times.sunset.date(), date(2026, 10, 29))
        self.assertTrue(5 <= times.sunrise.hour <= 6, times.sunrise)

    def test_solar_noon_sits_near_local_noon_for_matching_timezone(self):
        noon = solar.solar_noon(date(2026, 10, 29), PARIS[1], PARIS_TZ)
        self.assertLess(solar.noon_offset_hours(noon), 1.5)
        self.assertTrue(11 <= noon.hour <= 13, noon)

    def test_dst_transition_day_keeps_local_offset(self):
        times = solar.sun_times(date(2026, 11, 1), 40.7128, -74.0060, ZoneInfo("America/New_York"))
        self.assertEqual(times.sunrise.utcoffset().total_seconds(), -5 * 3600)
        self.assertTrue(6 <= times.sunrise.hour <= 7, times.sunrise)


class DecideTest(unittest.TestCase):
    def setUp(self):
        self.times = solar.SunTimes(
            datetime(2026, 10, 29, 7, 32, tzinfo=PARIS_TZ),
            datetime(2026, 10, 29, 17, 35, tzinfo=PARIS_TZ),
            "normal",
        )

    def test_boundaries_are_inclusive_at_sunrise(self):
        at = lambda h, m: datetime(2026, 10, 29, h, m, tzinfo=PARIS_TZ)
        self.assertEqual(solar.decide(at(7, 31), self.times), "dark")
        self.assertEqual(solar.decide(at(7, 32), self.times), "light")
        self.assertEqual(solar.decide(at(17, 34), self.times), "light")
        self.assertEqual(solar.decide(at(17, 35), self.times), "dark")

    def test_buffer_delays_light_and_advances_dark(self):
        at = lambda h, m: datetime(2026, 10, 29, h, m, tzinfo=PARIS_TZ)
        self.assertEqual(solar.decide(at(8, 1), self.times, 30), "dark")
        self.assertEqual(solar.decide(at(8, 2), self.times, 30), "light")
        self.assertEqual(solar.decide(at(17, 4), self.times, 30), "light")
        self.assertEqual(solar.decide(at(17, 5), self.times, 30), "dark")

    def test_polar_kinds_force_variant(self):
        polar_day = solar.SunTimes(None, None, "polar_day")
        polar_night = solar.SunTimes(None, None, "polar_night")
        now = datetime(2026, 6, 21, 12, tzinfo=ZoneInfo("Europe/Oslo"))
        self.assertEqual(solar.decide(now, polar_day), "light")
        self.assertEqual(solar.decide(now, polar_night), "dark")

    def test_next_change_reports_todays_sunset(self):
        now = datetime(2026, 10, 29, 12, 0, tzinfo=PARIS_TZ)
        moment, variant = solar.next_change(now, self.times)
        self.assertEqual(variant, "dark")
        self.assertEqual((moment.hour, moment.minute), (17, 35))

    def test_next_change_skips_events_that_keep_current_variant(self):
        now = datetime(2026, 10, 29, 12, 0, tzinfo=PARIS_TZ)
        self.assertEqual(solar.next_change(now, self.times, current="light")[1], "dark")
        self.assertIsNone(solar.next_change(now, self.times, current="dark"))


if __name__ == "__main__":
    unittest.main()
