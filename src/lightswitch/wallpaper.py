"""WinDynamicDesktop 主题（.ddw）解析、按太阳高度排布壁纸与套用。

.ddw 就是一个 zip：theme.json 加一组图片。图片命名规则是 imageFilename 里的 "*" 替换成序号，
分组由 sunriseImageList / dayImageList / sunsetImageList / nightImageList 给出。
四个分段时间边界沿用 WinDynamicDesktop 的定义：民用黎明(-6°) → 金色时段结束(+6°)
→ 金色时段开始(+6°) → 民用黄昏(-6°) → 次日黎明。
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, tzinfo
from pathlib import Path

from . import solar
from .themes import Gsetting

BACKGROUND_SCHEMA = "org.gnome.desktop.background"


@dataclass(frozen=True)
class Theme:
    theme_id: str
    pattern: str
    day: list[int]
    night: list[int]
    sunrise: list[int] = field(default_factory=list)
    sunset: list[int] = field(default_factory=list)
    credits: str = ""

    def filename(self, index: int) -> str:
        return self.pattern.replace("*", str(index))

    def all_indices(self) -> list[int]:
        seen: list[int] = []
        for group in (self.sunrise, self.day, self.sunset, self.night):
            for index in group:
                if index not in seen:
                    seen.append(index)
        return seen


def read_theme(ddw: Path) -> Theme:
    try:
        with zipfile.ZipFile(ddw) as archive:
            names = archive.namelist()
            candidates = [n for n in names if n.lower().endswith("theme.json")]
            if not candidates:
                raise ValueError("压缩包里没有 theme.json")
            raw = json.loads(archive.read(candidates[0]).decode("utf-8-sig"))
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError(f"读不了 {ddw.name}：{exc}") from exc
    pattern = raw.get("imageFilename")
    day = raw.get("dayImageList")
    night = raw.get("nightImageList")
    if not pattern or not day or not night:
        raise ValueError("theme.json 缺少 imageFilename、dayImageList 或 nightImageList")
    return Theme(
        theme_id=ddw.stem,
        pattern=str(pattern),
        day=[int(i) for i in day],
        night=[int(i) for i in night],
        sunrise=[int(i) for i in (raw.get("sunriseImageList") or [])],
        sunset=[int(i) for i in (raw.get("sunsetImageList") or [])],
        credits=str(raw.get("imageCredits") or ""),
    )


def cache_dir(ddw: Path, root: Path) -> Path:
    digest = hashlib.sha256()
    with ddw.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return root / digest.hexdigest()[:12]


def extract(ddw: Path, root: Path, theme: Theme) -> dict[int, Path]:
    """把主题用到的图片解到缓存目录；已经解过就复用，返回 序号 → 文件路径。"""
    target = cache_dir(ddw, root)
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ddw) as archive:
        names = set(archive.namelist())
        for index in theme.all_indices():
            name = theme.filename(index)
            if name in names and not (target / Path(name).name).exists():
                archive.extract(name, target)
    paths: dict[int, Path] = {}
    for index in theme.all_indices():
        path = target / Path(theme.filename(index)).name
        if not path.exists():
            raise ValueError(f"主题缺少第 {index} 张图片（{theme.filename(index)}）")
        paths[index] = path
    return paths


def schedule(
    day: date, latitude: float, longitude: float, tz: tzinfo, theme: Theme, images: dict[int, Path]
) -> list[tuple[datetime, int]]:
    """当日每张图片开始生效的时刻，按时间升序；跨夜的夜间段延到次日黎明。"""
    now_segments = solar.day_segments(day, latitude, longitude, tz)
    next_segments = solar.day_segments(day + timedelta(days=1), latitude, longitude, tz)
    has_sunrise = bool(theme.sunrise)
    has_sunset = bool(theme.sunset)

    def spread(group: list[int], start: datetime | None, end: datetime | None) -> list[tuple[datetime, int]]:
        if not group or start is None or end is None or end <= start:
            return []
        span = (end - start) / len(group)
        return [(start + span * position, index) for position, index in enumerate(group)]

    entries: list[tuple[datetime, int]] = []
    if has_sunrise:
        entries += spread(theme.sunrise, now_segments["dawn"], now_segments["golden_am"])
    day_start = now_segments["golden_am"] if has_sunrise else now_segments["sunrise"]
    day_end = now_segments["golden_pm"] if has_sunset else now_segments["sunset"]
    if not (has_sunrise and theme.day == theme.sunrise):
        entries += spread(theme.day, day_start, day_end)
    if has_sunset and theme.sunset != theme.day:
        entries += spread(theme.sunset, now_segments["golden_pm"], now_segments["dusk"])
    night_start = now_segments["dusk"] if has_sunset else now_segments["sunset"]
    night_end = next_segments["dawn"] if has_sunrise else next_segments["sunrise"]
    entries += spread(theme.night, night_start, night_end)

    entries.sort(key=lambda item: item[0])
    return [(moment, index) for moment, index in entries if index in images]


def current(
    now: datetime, latitude: float, longitude: float, tz: tzinfo, theme: Theme, images: dict[int, Path]
) -> tuple[datetime, int] | None:
    """当前该用哪张图：把昨、今、明三天的排布接起来，取最后一个已生效的条目。"""
    merged: list[tuple[datetime, int]] = []
    for offset in (-1, 0, 1):
        merged += schedule(now.date() + timedelta(days=offset), latitude, longitude, tz, theme, images)
    merged.sort(key=lambda item: item[0])
    chosen = None
    for moment, index in merged:
        if moment <= now:
            chosen = (moment, index)
        else:
            break
    return chosen


def next_entry(
    now: datetime, latitude: float, longitude: float, tz: tzinfo, theme: Theme, images: dict[int, Path]
) -> tuple[datetime, int] | None:
    merged: list[tuple[datetime, int]] = []
    for offset in (0, 1):
        merged += schedule(now.date() + timedelta(days=offset), latitude, longitude, tz, theme, images)
    merged.sort(key=lambda item: item[0])
    return next(((moment, index) for moment, index in merged if moment > now), None)


def apply_actions(image: Path) -> list[Gsetting]:
    uri = image.resolve().as_uri()
    return [
        Gsetting(BACKGROUND_SCHEMA, "picture-uri", uri),
        Gsetting(BACKGROUND_SCHEMA, "picture-uri-dark", uri),
        Gsetting(BACKGROUND_SCHEMA, "picture-options", "zoom"),
    ]
