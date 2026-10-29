"""systemd 用户级定时器：安装、启停与状态查询。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

SERVICE_NAME = "lightswitch.service"
TIMER_NAME = "lightswitch.timer"

SERVICE_UNIT = """[Unit]
Description=lightswitch 日出日落主题切换

[Service]
Type=oneshot
ExecStart={exec_path} tick
"""

TIMER_UNIT = """[Unit]
Description=每 5 分钟检查日出日落并切换主题

[Timer]
OnCalendar=*:0/5
Persistent=true
AccuracySec=30s
Unit={service}

[Install]
WantedBy=timers.target
"""


def unit_dir(home: Path | None = None) -> Path:
    return (home or Path.home()) / ".config" / "systemd" / "user"


def install_units(exec_path: Path, home: Path | None = None) -> list[Path]:
    target = unit_dir(home)
    target.mkdir(parents=True, exist_ok=True)
    service = target / SERVICE_NAME
    timer = target / TIMER_NAME
    service.write_text(SERVICE_UNIT.format(exec_path=exec_path), encoding="utf-8")
    timer.write_text(TIMER_UNIT.format(service=SERVICE_NAME), encoding="utf-8")
    _systemctl(["daemon-reload"])
    return [service, timer]


def remove_units(home: Path | None = None) -> None:
    disable(home)
    for name in (SERVICE_NAME, TIMER_NAME):
        path = unit_dir(home) / name
        if path.exists():
            path.unlink()
    _systemctl(["daemon-reload"])


def _systemctl(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["systemctl", "--user", *args], capture_output=True, text=True, env=os.environ.copy()
    )


def enable() -> tuple[bool, str]:
    proc = _systemctl(["enable", "--now", TIMER_NAME])
    return proc.returncode == 0, (proc.stderr or proc.stdout).strip()


def disable() -> tuple[bool, str]:
    proc = _systemctl(["disable", "--now", TIMER_NAME])
    return proc.returncode == 0, (proc.stderr or proc.stdout).strip()


def is_enabled() -> str:
    proc = _systemctl(["is-enabled", TIMER_NAME])
    return proc.stdout.strip() or "not-installed"


def is_active() -> bool:
    return _systemctl(["is-active", TIMER_NAME]).stdout.strip() == "active"


def next_elapse() -> str | None:
    proc = _systemctl(["show", TIMER_NAME, "-p", "NextElapseUSecRealtime", "--value"])
    value = proc.stdout.strip()
    return value if value and value != "n/a" else None
