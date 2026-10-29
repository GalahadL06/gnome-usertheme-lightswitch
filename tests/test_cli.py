import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LAUNCHER = REPO / "bin" / "lightswitch"

GSETTINGS_SHIM = """#!/bin/sh
echo "$@" >> "$HOME/gsettings.log"
if [ "$1" = "get" ]; then
  if [ -f "$HOME/.gsettings.$3" ]; then cat "$HOME/.gsettings.$3"; else echo "''"; fi
  exit 0
fi
if [ "$1" = "set" ]; then printf '%s' "$4" > "$HOME/.gsettings.$3"; fi
exit 0
"""


class CliTest(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        gtk4 = self.home / ".config" / "gtk-4.0"
        gtk4.mkdir(parents=True)
        (gtk4 / "gtk-Light.css").write_text("/* light */\n")
        (gtk4 / "gtk-Dark.css").write_text("/* dark */\n")
        (self.home / ".config" / "lightswitch").mkdir(parents=True)
        (self.home / ".config" / "lightswitch" / "config.json").write_text(
            json.dumps({"latitude": 39.89455, "longitude": 116.35983, "buffer_minutes": 0})
        )
        shim_dir = self.home / "bin"
        shim_dir.mkdir()
        shim = shim_dir / "gsettings"
        shim.write_text(GSETTINGS_SHIM)
        shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
        self.env = os.environ.copy()
        self.env["HOME"] = str(self.home)
        self.env["PATH"] = f"{shim_dir}:{self.env['PATH']}"

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, str(LAUNCHER), *args],
            capture_output=True, text=True, env=self.env, timeout=60,
        )

    def state(self):
        path = self.home / ".local" / "state" / "lightswitch" / "state.json"
        return json.loads(path.read_text()) if path.exists() else {}

    def test_tick_switches_to_light_before_sunset(self):
        result = self.run_cli("tick", "--at", "2026-10-29T12:00")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("浅色", result.stdout)
        self.assertEqual(self.state()["variant"], "light")
        calls = (self.home / "gsettings.log").read_text()
        self.assertIn("'MacTahoe-Light'", calls)

    def test_tick_switches_to_dark_after_sunset(self):
        self.run_cli("tick", "--at", "2026-10-29T12:00")
        result = self.run_cli("tick", "--at", "2026-10-29T18:00")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.state()["variant"], "dark")
        self.assertIn("'MacTahoe-Dark'", (self.home / "gsettings.log").read_text())

    def test_tick_is_a_noop_when_already_correct(self):
        self.run_cli("tick", "--at", "2026-10-29T18:00")
        log = lambda: [l for l in (self.home / "gsettings.log").read_text().splitlines() if l.startswith("set ")]
        before = len(log())
        result = self.run_cli("tick", "--at", "2026-10-29T19:30")
        self.assertIn("无需动作", result.stdout)
        self.assertEqual(len(log()), before)

    def test_tick_without_location_explains_the_next_step(self):
        (self.home / ".config" / "lightswitch" / "config.json").write_text("{}")
        result = self.run_cli("tick")
        self.assertEqual(result.returncode, 2)
        self.assertIn("location", result.stderr)

    def test_status_json_reports_state_and_sun_times(self):
        self.run_cli("tick", "--at", "2026-10-29T12:00")
        result = self.run_cli("status", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["variant"], "light")
        self.assertEqual(payload["sun"]["sunrise"][11:16], "06:39")
        self.assertEqual(payload["gtk4_css"], "gtk-Light.css")

    def test_config_set_persists_custom_theme_names(self):
        result = self.run_cli("config", "set", "--light-theme", "MacTahoe-Light-solid",
                              "--light-icons", "MacTahoe", "--buffer", "20")
        self.assertEqual(result.returncode, 0, result.stderr)
        saved = json.loads((self.home / ".config" / "lightswitch" / "config.json").read_text())
        self.assertEqual(saved["light"]["gtk"], "MacTahoe-Light-solid")
        self.assertEqual(saved["light"]["icons"], "MacTahoe")
        self.assertEqual(saved["buffer_minutes"], 20)
        self.assertIn("已保存", result.stdout)

    def test_location_set_resolves_sun_times(self):
        result = self.run_cli("location", "--set", "39.89455,116.35983")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("06:39", result.stdout)
        self.assertIn("17:16", result.stdout)

    def test_location_rejects_coordinates_from_another_timezone(self):
        before = json.loads((self.home / ".config" / "lightswitch" / "config.json").read_text())
        result = self.run_cli("location", "--set", "34.0504,-118.2430")
        self.assertEqual(result.returncode, 3)
        self.assertIn("对不上", result.stderr)
        self.assertIn("这份坐标没有保存", result.stderr)
        after = json.loads((self.home / ".config" / "lightswitch" / "config.json").read_text())
        self.assertEqual(after["latitude"], before["latitude"])

    def test_location_force_saves_mismatched_coordinates(self):
        result = self.run_cli("location", "--set", "34.0504,-118.2430", "--force")
        self.assertEqual(result.returncode, 0, result.stderr)
        saved = json.loads((self.home / ".config" / "lightswitch" / "config.json").read_text())
        self.assertAlmostEqual(saved["latitude"], 34.0504, places=3)

    def test_tick_refuses_to_switch_with_mismatched_coordinates(self):
        (self.home / ".config" / "lightswitch" / "config.json").write_text(
            json.dumps({"latitude": 34.0504, "longitude": -118.2430})
        )
        result = self.run_cli("tick", "--at", "2026-10-29T12:00")
        self.assertEqual(result.returncode, 2)
        self.assertIn("拒绝切换", result.stderr)

    def test_location_clear_removes_coordinates(self):
        result = self.run_cli("location", "--clear")
        self.assertEqual(result.returncode, 0, result.stderr)
        saved = json.loads((self.home / ".config" / "lightswitch" / "config.json").read_text())
        self.assertIsNone(saved["latitude"])
        self.assertIsNone(saved["longitude"])

    def test_location_rejects_bad_coordinates_without_traceback(self):
        result = self.run_cli("location", "--set", "999,999")
        self.assertEqual(result.returncode, 2)
        self.assertIn("取位置失败", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
