import json
import os
import stat
import tempfile
import unittest
import zipfile
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from lightswitch import solar, wallpaper

PARIS = (48.8566, 2.3522)
TZ = ZoneInfo("Europe/Paris")
CACHE = Path(tempfile.gettempdir()) / "lightswitch-test-cache"

THEME_JSON = {
    "imageFilename": "shot_*.jpg",
    "imageCredits": "test",
    "sunriseImageList": [1, 2],
    "dayImageList": [3, 4, 5],
    "sunsetImageList": [6, 7],
    "nightImageList": [8],
}


def make_ddw(directory: Path, theme=THEME_JSON, name="demo.ddw") -> Path:
    path = directory / name
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("theme.json", json.dumps(theme))
        for index in range(1, 9):
            archive.writestr(f"shot_{index}.jpg", f"image-{index}".encode())
    return path


class ThemeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.ddw = make_ddw(self.tmp)

    def test_read_theme_maps_groups(self):
        theme = wallpaper.read_theme(self.ddw)
        self.assertEqual(theme.theme_id, "demo")
        self.assertEqual(theme.day, [3, 4, 5])
        self.assertEqual(theme.night, [8])
        self.assertEqual(theme.sunrise, [1, 2])
        self.assertEqual(theme.filename(4), "shot_4.jpg")
        self.assertEqual(theme.all_indices(), [1, 2, 3, 4, 5, 6, 7, 8])

    def test_extract_is_cached_and_complete(self):
        theme = wallpaper.read_theme(self.ddw)
        first = wallpaper.extract(self.ddw, self.tmp / "cache", theme)
        second = wallpaper.extract(self.ddw, self.tmp / "cache", theme)
        self.assertEqual(first.keys(), second.keys())
        self.assertEqual(first[1].read_bytes(), b"image-1")
        self.assertEqual(len({p.parent for p in first.values()}), 1)

    def test_missing_image_is_reported(self):
        broken = make_ddw(self.tmp, {**THEME_JSON, "nightImageList": [99]}, name="broken.ddw")
        theme = wallpaper.read_theme(broken)
        with self.assertRaises(ValueError) as ctx:
            wallpaper.extract(broken, self.tmp / "cache", theme)
        self.assertIn("99", str(ctx.exception))

    def test_theme_without_required_fields_is_rejected(self):
        bad = make_ddw(self.tmp, {"imageFilename": "shot_*.jpg"}, name="bad.ddw")
        with self.assertRaises(ValueError):
            wallpaper.read_theme(bad)


class ScheduleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.ddw = make_ddw(self.tmp)
        self.theme = wallpaper.read_theme(self.ddw)
        self.images = wallpaper.extract(self.ddw, self.tmp / "cache", self.theme)
        self.day = date(2026, 10, 29)

    def test_schedule_covers_four_segments_in_order(self):
        entries = wallpaper.schedule(self.day, *PARIS, TZ, self.theme, self.images)
        moments = [moment for moment, _ in entries]
        self.assertEqual(moments, sorted(moments))
        self.assertEqual(len(entries), 8)
        segments = solar.day_segments(self.day, *PARIS, TZ)
        self.assertEqual(moments[0], segments["dawn"])
        self.assertEqual(moments[-1], segments["dusk"])

    def test_sunrise_images_spread_between_dawn_and_golden_hour(self):
        entries = wallpaper.schedule(self.day, *PARIS, TZ, self.theme, self.images)
        segments = solar.day_segments(self.day, *PARIS, TZ)
        sunrise_entries = [e for e in entries if e[1] in self.theme.sunrise]
        self.assertEqual(len(sunrise_entries), 2)
        self.assertGreaterEqual(sunrise_entries[0][0], segments["dawn"])
        self.assertLess(sunrise_entries[0][0], segments["golden_am"])

    def test_current_picks_night_before_dawn(self):
        segments = solar.day_segments(self.day, *PARIS, TZ)
        early = segments["dawn"] - (segments["dawn"] - segments["dawn"].replace(hour=0, minute=0)) / 2
        moment, index = wallpaper.current(early, *PARIS, TZ, self.theme, self.images)
        self.assertIn(index, self.theme.night)

    def test_current_picks_day_image_at_noon(self):
        noon = datetime(2026, 10, 29, 12, 0, tzinfo=TZ)
        moment, index = wallpaper.current(noon, *PARIS, TZ, self.theme, self.images)
        self.assertIn(index, self.theme.day)

    def test_next_entry_is_after_now(self):
        noon = datetime(2026, 10, 29, 12, 0, tzinfo=TZ)
        moment, index = wallpaper.next_entry(noon, *PARIS, TZ, self.theme, self.images)
        self.assertGreater(moment, noon)
        self.assertIn(index, self.theme.day + self.theme.sunset + self.theme.night)

    def test_apply_actions_target_both_uris(self):
        path = self.images[3]
        actions = wallpaper.apply_actions(path)
        values = {a.key: a.value for a in actions}
        self.assertEqual(values["picture-uri"], path.resolve().as_uri())
        self.assertEqual(values["picture-uri-dark"], path.resolve().as_uri())
        self.assertEqual(values["picture-options"], "zoom")


class WallpaperCliTest(unittest.TestCase):
    SHIM = '''#!/bin/sh
echo "$@" >> "$HOME/gsettings.log"
if [ "$1" = "get" ]; then
  if [ -f "$HOME/.gsettings.$3" ]; then cat "$HOME/.gsettings.$3"; else echo "''"; fi
  exit 0
fi
if [ "$1" = "set" ]; then printf '%s' "$4" > "$HOME/.gsettings.$3"; fi
exit 0
'''

    def setUp(self):
        import subprocess
        import sys

        self.subprocess = subprocess
        self.sys = sys
        repo = Path(__file__).resolve().parents[1]
        self.launcher = repo / "bin" / "lightswitch"
        self.home = Path(tempfile.mkdtemp())
        (self.home / ".config" / "lightswitch").mkdir(parents=True)
        (self.home / ".config" / "lightswitch" / "config.json").write_text(
            json.dumps({"latitude": 48.8566, "longitude": 2.3522})
        )
        shim_dir = self.home / "bin"
        shim_dir.mkdir()
        shim = shim_dir / "gsettings"
        shim.write_text(self.SHIM)
        shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
        self.ddw = make_ddw(self.home, name="demo.ddw")
        self.env = os.environ.copy()
        self.env.update({"HOME": str(self.home), "PATH": f"{shim_dir}:{self.env['PATH']}", "TZ": "Europe/Paris"})

    def run_cli(self, *args):
        return self.subprocess.run(
            [self.sys.executable, str(self.launcher), *args],
            capture_output=True, text=True, env=self.env, timeout=60,
        )

    def test_use_then_apply_sets_wallpaper(self):
        result = self.run_cli("wallpaper", "use", str(self.ddw))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("已启用 demo", result.stdout)
        log = (self.home / "gsettings.log").read_text()
        self.assertIn("org.gnome.desktop.background picture-uri", log)
        saved = json.loads((self.home / ".config" / "lightswitch" / "config.json").read_text())
        self.assertTrue(saved["wallpaper_enabled"])

    def test_apply_at_changes_image_and_skips_repeat(self):
        self.run_cli("wallpaper", "use", str(self.ddw))
        night = self.run_cli("wallpaper", "apply", "--at", "2026-10-29T23:00")
        self.assertIn("shot_8.jpg", night.stdout)
        again = self.run_cli("wallpaper", "apply", "--at", "2026-10-29T23:10")
        self.assertIn("已生效", again.stdout)

    def test_off_disables_without_touching_wallpaper(self):
        self.run_cli("wallpaper", "use", str(self.ddw))
        result = self.run_cli("wallpaper", "off")
        self.assertIn("已停止", result.stdout)
        saved = json.loads((self.home / ".config" / "lightswitch" / "config.json").read_text())
        self.assertFalse(saved["wallpaper_enabled"])

    def test_status_reports_theme_and_next_change(self):
        self.run_cli("wallpaper", "use", str(self.ddw))
        result = self.run_cli("wallpaper", "status")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("demo", result.stdout)
        self.assertIn("下次", result.stdout)


if __name__ == "__main__":
    unittest.main()
