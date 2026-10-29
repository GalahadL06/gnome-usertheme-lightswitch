import os
import stat
import tempfile
import unittest
from pathlib import Path

from lightswitch import themes
from lightswitch.config import Config

GSETTINGS_SHIM = """#!/bin/sh
echo "$@" >> "$HOME/gsettings.log"
if [ "$1" = "get" ]; then
  if [ -f "$HOME/.gsettings.$3" ]; then cat "$HOME/.gsettings.$3"; else echo "''"; fi
  exit 0
fi
if [ "$1" = "set" ]; then printf '%s' "$4" > "$HOME/.gsettings.$3"; fi
exit 0
"""


class PlanTest(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.cfg = Config(latitude=39.9, longitude=116.4)
        gtk4 = self.home / ".config" / "gtk-4.0"
        gtk4.mkdir(parents=True)
        (gtk4 / "gtk-Light.css").write_text("/* light */\n")
        (gtk4 / "gtk-Dark.css").write_text("/* dark */\n")
        shim_dir = self.home / "bin"
        shim_dir.mkdir()
        shim = shim_dir / "gsettings"
        shim.write_text(GSETTINGS_SHIM)
        shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
        self._env = {key: os.environ.get(key) for key in ("HOME", "PATH")}
        os.environ["HOME"] = str(self.home)
        os.environ["PATH"] = f"{shim_dir}:{self._env['PATH']}"

    def tearDown(self):
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_light_plan_targets_light_assets(self):
        actions = themes.plan(self.cfg, "light", self.home)
        gsettings = {(a.schema, a.key): a.value for a in actions if isinstance(a, themes.Gsetting)}
        self.assertEqual(gsettings[(themes.INTERFACE_SCHEMA, "gtk-theme")], "MacTahoe-Light")
        self.assertEqual(gsettings[(themes.INTERFACE_SCHEMA, "icon-theme")], "MacTahoe-light")
        self.assertEqual(gsettings[(themes.INTERFACE_SCHEMA, "color-scheme")], "prefer-light")
        self.assertEqual(gsettings[(themes.SHELL_SCHEMA, "name")], "MacTahoe-Light")
        links = {a.path.name: a.target.name for a in actions if isinstance(a, themes.Symlink)}
        self.assertEqual(links, {"gtk.css": "gtk-Light.css", "gtk-dark.css": "gtk-Light.css"})

    def test_shell_can_be_left_alone(self):
        cfg = Config(apply_shell=False)
        schemas = {a.schema for a in themes.plan(cfg, "dark", self.home) if isinstance(a, themes.Gsetting)}
        self.assertNotIn(themes.SHELL_SCHEMA, schemas)

    def test_execute_applies_settings_symlinks_and_ini(self):
        themes.execute(themes.plan(self.cfg, "light", self.home))

        calls = (self.home / "gsettings.log").read_text().splitlines()
        self.assertEqual(len(calls), 4)
        self.assertIn("set org.gnome.desktop.interface gtk-theme 'MacTahoe-Light'", calls)
        self.assertIn("set org.gnome.desktop.interface color-scheme 'prefer-light'", calls)

        gtk4 = self.home / ".config" / "gtk-4.0"
        self.assertEqual(os.readlink(gtk4 / "gtk.css"), str(gtk4 / "gtk-Light.css"))
        self.assertEqual(os.readlink(gtk4 / "gtk-dark.css"), str(gtk4 / "gtk-Light.css"))
        self.assertIn("gtk-application-prefer-dark-theme=0",
                      (gtk4 / "settings.ini").read_text())
        self.assertIn("gtk-application-prefer-dark-theme=0",
                      (self.home / ".config" / "gtk-3.0" / "settings.ini").read_text())

    def test_execute_is_idempotent(self):
        themes.execute(themes.plan(self.cfg, "dark", self.home))
        themes.execute(themes.plan(self.cfg, "dark", self.home))
        gtk4 = self.home / ".config" / "gtk-4.0"
        self.assertEqual(os.readlink(gtk4 / "gtk.css"), str(gtk4 / "gtk-Dark.css"))
        text = (gtk4 / "settings.ini").read_text()
        self.assertEqual(text.count("gtk-application-prefer-dark-theme"), 1)
        self.assertIn("gtk-application-prefer-dark-theme=1", text)

    def test_existing_ini_keys_survive(self):
        ini = self.home / ".config" / "gtk-3.0" / "settings.ini"
        ini.parent.mkdir(parents=True)
        ini.write_text("[Settings]\ngtk-theme=Something\n")
        themes.execute(themes.plan(self.cfg, "dark", self.home))
        text = ini.read_text()
        self.assertIn("gtk-theme=Something", text)
        self.assertIn("gtk-application-prefer-dark-theme=1", text)

    def test_missing_css_files_fail_loudly(self):
        (self.home / ".config" / "gtk-4.0" / "gtk-Light.css").unlink()
        with self.assertRaises(SystemExit):
            themes.execute(themes.plan(self.cfg, "light", self.home))


if __name__ == "__main__":
    unittest.main()
