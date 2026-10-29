"""把主题变体翻译成动作列表，并执行这些动作。plan 无副作用，execute 才落地。"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import VARIANTS, Config

INTERFACE_SCHEMA = "org.gnome.desktop.interface"
SHELL_SCHEMA = "org.gnome.shell.extensions.user-theme"


@dataclass(frozen=True)
class Gsetting:
    schema: str
    key: str
    value: str


@dataclass(frozen=True)
class Symlink:
    path: Path
    target: Path


@dataclass(frozen=True)
class IniEntry:
    path: Path
    key: str
    value: str


def gtk4_dir(home: Path | None = None) -> Path:
    return (home or Path.home()) / ".config" / "gtk-4.0"


def gtk3_dir(home: Path | None = None) -> Path:
    return (home or Path.home()) / ".config" / "gtk-3.0"


def plan(cfg: Config, variant: str, home: Path | None = None) -> list[Gsetting | Symlink | IniEntry]:
    if variant not in VARIANTS:
        raise ValueError(f"未知主题变体: {variant}")
    spec = cfg.spec(variant)
    css = gtk4_dir(home) / spec.gtk4_css
    actions: list[Gsetting | Symlink | IniEntry] = [
        Gsetting(INTERFACE_SCHEMA, "gtk-theme", spec.gtk),
        Gsetting(INTERFACE_SCHEMA, "icon-theme", spec.icons),
        Gsetting(INTERFACE_SCHEMA, "color-scheme", f"prefer-{variant}"),
    ]
    if cfg.apply_shell and spec.shell:
        actions.append(Gsetting(SHELL_SCHEMA, "name", spec.shell))
    actions.append(Symlink(gtk4_dir(home) / "gtk.css", css))
    actions.append(Symlink(gtk4_dir(home) / "gtk-dark.css", css))
    prefer_dark = "1" if variant == "dark" else "0"
    actions.append(IniEntry(gtk4_dir(home) / "settings.ini", "gtk-application-prefer-dark-theme", prefer_dark))
    actions.append(IniEntry(gtk3_dir(home) / "settings.ini", "gtk-application-prefer-dark-theme", prefer_dark))
    return actions


def describe(action: Gsetting | Symlink | IniEntry) -> str:
    if isinstance(action, Gsetting):
        return f"gsettings set {action.schema} {action.key} {action.value}"
    if isinstance(action, Symlink):
        return f"link {action.path} -> {action.target.name}"
    return f"ini {action.path} {action.key}={action.value}"


def _replace_symlink(path: Path, target: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.lightswitch")
    if tmp.is_symlink() or tmp.exists():
        tmp.unlink()
    os.symlink(target, tmp)
    os.replace(tmp, path)


def _write_ini(path: Path, key: str, value: str) -> None:
    lines: list[str] = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    in_settings = False
    seen_section = False
    replaced = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_settings = stripped.lower() == "[settings]"
            seen_section = seen_section or in_settings
            out.append(line)
            continue
        if in_settings and "=" in stripped and stripped.split("=", 1)[0].strip() == key:
            out.append(f"{key}={value}")
            replaced = True
            continue
        out.append(line)
    if not replaced:
        if not seen_section:
            if out and out[-1] != "":
                out.append("")
            out.append("[Settings]")
        out.append(f"{key}={value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out).rstrip("\n") + "\n", encoding="utf-8")


def execute(
    actions: list[Gsetting | Symlink | IniEntry],
    runner=None,
    dry_run: bool = False,
) -> list[str]:
    run = runner or _run_gsettings
    log: list[str] = []
    for action in actions:
        log.append(describe(action))
        if dry_run:
            continue
        if isinstance(action, Gsetting):
            run(["gsettings", "set", action.schema, action.key, f"'{action.value}'"])
        elif isinstance(action, Symlink):
            if not action.target.exists():
                raise SystemExit(f"缺少主题 CSS：{action.target}（该主题的安装脚本没有生成它，或 config 里的 gtk4_css 名字不对）")
            _replace_symlink(action.path, action.target)
        else:
            _write_ini(action.path, action.key, action.value)
    return log


def _run_gsettings(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"命令失败：{' '.join(cmd)}\n{proc.stderr.strip()}")


def current_gtk_theme() -> str | None:
    proc = subprocess.run(
        ["gsettings", "get", INTERFACE_SCHEMA, "gtk-theme"], capture_output=True, text=True
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.strip().strip("'")
