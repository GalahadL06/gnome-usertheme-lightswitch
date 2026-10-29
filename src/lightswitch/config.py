"""配置与运行时状态：默认值、读写、原子落盘。"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

VARIANTS = ("light", "dark")

DEFAULT_SPECS: dict[str, dict[str, str]] = {
    "light": {
        "gtk": "MacTahoe-Light",
        "icons": "MacTahoe-light",
        "shell": "MacTahoe-Light",
        "gtk4_css": "gtk-Light.css",
    },
    "dark": {
        "gtk": "MacTahoe-Dark",
        "icons": "MacTahoe-dark",
        "shell": "MacTahoe-Dark",
        "gtk4_css": "gtk-Dark.css",
    },
}


@dataclass(frozen=True)
class ThemeSpec:
    gtk: str
    icons: str
    shell: str
    gtk4_css: str


@dataclass
class Config:
    latitude: float | None = None
    longitude: float | None = None
    buffer_minutes: int = 0
    apply_shell: bool = True
    wallpaper_ddw: str | None = None
    wallpaper_enabled: bool = False
    light: ThemeSpec = field(default_factory=lambda: ThemeSpec(**DEFAULT_SPECS["light"]))
    dark: ThemeSpec = field(default_factory=lambda: ThemeSpec(**DEFAULT_SPECS["dark"]))

    def spec(self, variant: str) -> ThemeSpec:
        if variant not in VARIANTS:
            raise ValueError(f"未知主题变体: {variant}")
        return self.light if variant == "light" else self.dark


@dataclass
class State:
    variant: str | None = None
    applied_at: str | None = None
    last_tick: str | None = None


def config_path(home: Path | None = None) -> Path:
    return (home or Path.home()) / ".config" / "lightswitch" / "config.json"


def state_path(home: Path | None = None) -> Path:
    return (home or Path.home()) / ".local" / "state" / "lightswitch" / "state.json"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _spec_from(raw: dict | None, variant: str) -> ThemeSpec:
    merged = dict(DEFAULT_SPECS[variant])
    if isinstance(raw, dict):
        merged.update({k: str(v) for k, v in raw.items() if k in merged})
    return ThemeSpec(**merged)


def load_config(home: Path | None = None) -> Config:
    path = config_path(home)
    if not path.exists():
        return Config()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"配置无法解析：{path}（{exc}）")
    return Config(
        latitude=raw.get("latitude"),
        longitude=raw.get("longitude"),
        buffer_minutes=int(raw.get("buffer_minutes", 0)),
        apply_shell=bool(raw.get("apply_shell", True)),
        wallpaper_ddw=raw.get("wallpaper_ddw"),
        wallpaper_enabled=bool(raw.get("wallpaper_enabled", False)),
        light=_spec_from(raw.get("light"), "light"),
        dark=_spec_from(raw.get("dark"), "dark"),
    )


def save_config(cfg: Config, home: Path | None = None) -> Path:
    path = config_path(home)
    data = asdict(cfg)
    _atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return path


def load_state(home: Path | None = None) -> State:
    path = state_path(home)
    if not path.exists():
        return State()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return State()
    return State(
        variant=raw.get("variant"),
        applied_at=raw.get("applied_at"),
        last_tick=raw.get("last_tick"),
    )


def save_state(state: State, home: Path | None = None) -> Path:
    path = state_path(home)
    _atomic_write(path, json.dumps(asdict(state), ensure_ascii=False, indent=2) + "\n")
    return path


def with_spec(cfg: Config, variant: str, **changes: str) -> Config:
    return replace(cfg, **{variant: replace(cfg.spec(variant), **changes)})
