"""lightswitch 命令行入口。"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

from . import location, scheduler, solar, themes
from .config import (
    VARIANTS,
    Config,
    ThemeSpec,
    config_path,
    load_config,
    load_state,
    save_config,
    save_state,
    state_path,
    with_spec,
)

VERSION = "1.0.0"


def _local_tz():
    return datetime.now().astimezone().tzinfo


def _parse_moment(text: str | None) -> datetime:
    now = datetime.now().astimezone()
    if not text:
        return now
    if len(text) <= 5 and ":" in text:
        hour, minute = text.split(":")
        return now.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise SystemExit(f"无法解析时间：{text}（用 2026-10-29T18:30 或 18:30 格式）")
    return parsed.replace(tzinfo=_local_tz()) if parsed.tzinfo is None else parsed


def _gsettings_get(schema: str, key: str) -> str:
    proc = subprocess.run(["gsettings", "get", schema, key], capture_output=True, text=True)
    return proc.stdout.strip().strip("'") if proc.returncode == 0 else ""


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _sanity(latitude: float, longitude: float, tz) -> tuple[bool, float]:
    """坐标与机器时区是否自洽：太阳正午应落在当地时间正午附近（容差 4 小时）。"""
    offset = solar.noon_offset_hours(solar.solar_noon(datetime.now().astimezone().date(), longitude, tz))
    return offset <= 4.0, offset


def _apply(cfg: Config, variant: str, dry_run: bool = False) -> str:
    spec = cfg.spec(variant)
    themes.execute(themes.plan(cfg, variant), dry_run=dry_run)
    if not dry_run:
        state = load_state()
        state.variant = variant
        state.applied_at = _now_iso()
        save_state(state)
    label = "浅色" if variant == "light" else "深色"
    return f"{label}：{spec.gtk} / {spec.icons} / {spec.gtk4_css}" + ("（演练，未写入）" if dry_run else "")


def cmd_light(args: argparse.Namespace) -> int:
    print(_apply(load_config(), "light", args.dry_run))
    return 0


def cmd_dark(args: argparse.Namespace) -> int:
    print(_apply(load_config(), "dark", args.dry_run))
    return 0


def cmd_toggle(args: argparse.Namespace) -> int:
    cfg = load_config()
    state = load_state()
    current = state.variant
    if current is None:
        current = "light" if _gsettings_get(themes.INTERFACE_SCHEMA, "gtk-theme") == cfg.light.gtk else "dark"
    print(_apply(cfg, "dark" if current == "light" else "light", args.dry_run))
    return 0


def cmd_tick(args: argparse.Namespace) -> int:
    cfg = load_config()
    if cfg.latitude is None or cfg.longitude is None:
        print("尚未设置位置：先运行 lightswitch location --geoclue，或用 --set 纬度,经度 手填", file=sys.stderr)
        return 2
    now = _parse_moment(args.at)
    tz = now.tzinfo or _local_tz()
    sane, offset = _sanity(cfg.latitude, cfg.longitude, tz)
    if not sane:
        print(f"坐标 {cfg.latitude:.4f},{cfg.longitude:.4f} 与机器时区相差 {offset:.1f} 小时，"
              "日照区间落不到当地的白天，拒绝切换；请用 lightswitch location --set 校正", file=sys.stderr)
        return 2
    times = solar.sun_times(now.date(), cfg.latitude, cfg.longitude, tz)
    wanted = solar.decide(now, times, cfg.buffer_minutes)
    spec = cfg.spec(wanted)
    state = load_state()
    if state.variant == wanted and themes.current_gtk_theme() == spec.gtk:
        if not args.dry_run:
            state.last_tick = _now_iso()
            save_state(state)
        print(f"{now:%Y-%m-%d %H:%M} 已是{'浅色' if wanted == 'light' else '深色'}（{spec.gtk}），无需动作")
        return 0
    print(_apply(cfg, wanted, args.dry_run))
    if not args.dry_run:
        state = load_state()
        state.last_tick = _now_iso()
        save_state(state)
    return 0


def cmd_auto(args: argparse.Namespace) -> int:
    if args.state == "on":
        ok, message = scheduler.enable()
        print("自动切换已启用：systemd 用户定时器每 5 分钟核对一次日出日落" if ok else f"启用失败：{message}")
        return 0 if ok else 1
    ok, message = scheduler.disable()
    print("自动切换已停止，主题保持当前状态" if ok else f"停止失败：{message}")
    return 0 if ok else 1


def cmd_refresh(args: argparse.Namespace) -> int:
    cfg = load_config()
    state = load_state()
    variant = state.variant
    if variant not in VARIANTS:
        variant = "light" if _gsettings_get(themes.INTERFACE_SCHEMA, "gtk-theme") == cfg.light.gtk else "dark"
    print(_apply(cfg, variant, args.dry_run))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    cfg = load_config()
    state = load_state()
    now = datetime.now().astimezone()
    gtk = _gsettings_get(themes.INTERFACE_SCHEMA, "gtk-theme")
    icons = _gsettings_get(themes.INTERFACE_SCHEMA, "icon-theme")
    scheme = _gsettings_get(themes.INTERFACE_SCHEMA, "color-scheme")
    shell = _gsettings_get(themes.SHELL_SCHEMA, "name")
    css_link = themes.gtk4_dir() / "gtk.css"
    css_target = css_link.resolve().name if css_link.is_symlink() and css_link.exists() else "（无）"

    sun = None
    planned = None
    if cfg.latitude is not None and cfg.longitude is not None:
        times = solar.sun_times(now.date(), cfg.latitude, cfg.longitude, now.tzinfo)
        sun = times
        upcoming = solar.next_change(now, times, cfg.buffer_minutes, state.variant)
        if upcoming is None:
            tomorrow = now + timedelta(days=1)
            next_times = solar.sun_times(tomorrow.date(), cfg.latitude, cfg.longitude, now.tzinfo)
            upcoming = solar.next_change(now, next_times, cfg.buffer_minutes, state.variant)
        if upcoming and _sanity(cfg.latitude, cfg.longitude, now.tzinfo)[0]:
            planned = {"at": upcoming[0].isoformat(timespec="minutes"), "variant": upcoming[1]}

    payload = {
        "variant": state.variant,
        "applied_at": state.applied_at,
        "last_tick": state.last_tick,
        "gsettings": {"gtk": gtk, "icons": icons, "color_scheme": scheme, "shell": shell},
        "gtk4_css": str(css_target),
        "location": {"latitude": cfg.latitude, "longitude": cfg.longitude},
        "sun": {"sunrise": sun.sunrise.isoformat(timespec="minutes") if sun and sun.sunrise else None,
                "sunset": sun.sunset.isoformat(timespec="minutes") if sun and sun.sunset else None,
                "kind": sun.kind if sun else None},
        "buffer_minutes": cfg.buffer_minutes,
        "next_change": planned,
        "timer": {"enabled": scheduler.is_enabled(), "active": scheduler.is_active(),
                  "next_elapse": scheduler.next_elapse()},
        "config_path": str(config_path()),
        "state_path": str(state_path()),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    label = {"light": "浅色", "dark": "深色"}.get(state.variant or "", "未知")
    print(f"当前主题：{label}"
          + (f"（{state.applied_at} 应用）" if state.applied_at else "（未由本工具应用过）"))
    print(f"gsettings：gtk={gtk or '?'}  icon={icons or '?'}  color-scheme={scheme or '?'}  shell={shell or '未启用'}")
    print(f"libadwaita：gtk.css → {css_target}")
    if sun and sun.sunrise and sun.sunset:
        print(f"位置 {cfg.latitude:.4f},{cfg.longitude:.4f}  日出 {sun.sunrise:%H:%M}  日落 {sun.sunset:%H:%M}"
              f"  缓冲 {cfg.buffer_minutes} 分钟")
    elif cfg.latitude is None:
        print("位置：未设置（lightswitch location --geoclue，或 --set 纬度,经度）")
    else:
        print(f"位置 {cfg.latitude:.4f},{cfg.longitude:.4f}  极昼" if sun and sun.kind == "polar_day"
              else f"位置 {cfg.latitude:.4f},{cfg.longitude:.4f}  极夜")
    if cfg.latitude is not None and cfg.longitude is not None:
        sane, offset = _sanity(cfg.latitude, cfg.longitude, now.tzinfo)
        if not sane:
            print(f"⚠ 坐标与机器时区相差 {offset:.1f} 小时，日照区间不在当地白天，疑似代理环境下的 IP 定位；"
                  "请用 lightswitch location --set 校正")
    if planned:
        target = "浅色" if planned["variant"] == "light" else "深色"
        print(f"下次切换：{planned['at']} → {target}")
    print(f"自动切换：定时器 {payload['timer']['enabled']}"
          + (f"，下次唤醒 {payload['timer']['next_elapse']}" if payload["timer"]["next_elapse"] else ""))
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    cfg = load_config()
    if args.action == "show":
        print(json.dumps(asdict(cfg), ensure_ascii=False, indent=2))
        print(f"\n配置文件：{config_path()}")
        return 0
    mapping = {
        "light_theme": ("light", "gtk"),
        "light_icons": ("light", "icons"),
        "light_shell": ("light", "shell"),
        "light_css": ("light", "gtk4_css"),
        "dark_theme": ("dark", "gtk"),
        "dark_icons": ("dark", "icons"),
        "dark_shell": ("dark", "shell"),
        "dark_css": ("dark", "gtk4_css"),
    }
    changed = False
    for field_name, (variant, attr) in mapping.items():
        value = getattr(args, field_name)
        if value:
            cfg = with_spec(cfg, variant, **{attr: value})
            changed = True
    if args.buffer is not None:
        cfg.buffer_minutes = args.buffer
        changed = True
    if args.shell is not None:
        cfg.apply_shell = args.shell == "on"
        changed = True
    if not changed:
        print("没有给出要修改的字段，用 lightswitch config show 查看当前配置", file=sys.stderr)
        return 2
    save_config(cfg)
    print(f"已保存：{config_path()}")
    for variant in VARIANTS:
        spec = cfg.spec(variant)
        print(f"  {variant}: {spec.gtk} / {spec.icons} / {spec.shell} / {spec.gtk4_css}")
    return 0


def cmd_location(args: argparse.Namespace) -> int:
    cfg = load_config()
    if getattr(args, "clear", False):
        cfg.latitude, cfg.longitude = None, None
        save_config(cfg)
        print("已清除坐标，自动切换在重新设置位置前不会生效")
        return 0
    label = ""
    try:
        if args.set_coords:
            lat, lon = location.parse_coords(args.set_coords)
            source = "手动坐标"
        elif args.city:
            lat, lon, label = location.from_city(args.city)
            source = "地名解析（请求只含城市名）"
        elif args.wifi:
            lat, lon = location.from_wifi()
            source = "AP 指纹（BeaconDB，不含 IP 信息）"
        elif args.ip:
            lat, lon = location.from_ip()
            source = "IP 定位（走代理或 VPN 时不可信）"
        elif args.geoclue:
            lat, lon = location.from_geoclue(args.timeout)
            source = "GeoClue2（可能与 AP 数据库无关）"
        else:
            if cfg.latitude is None:
                print("尚未设置位置。用 --city 城市名、--set 纬度,经度 或 --wifi 取坐标", file=sys.stderr)
                return 2
            lat, lon = cfg.latitude, cfg.longitude
            source = "已保存的坐标"
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"取位置失败：{exc}", file=sys.stderr)
        return 2
    now = datetime.now().astimezone()
    sane, offset = _sanity(lat, lon, now.tzinfo)
    explicit = args.set_coords or args.city or args.wifi or args.ip or args.geoclue
    if not sane and not getattr(args, "force", False):
        noon = solar.solar_noon(now.date(), lon, now.tzinfo)
        print(f"坐标 {lat:.4f},{lon:.4f} 与这台机器的时区对不上：当地太阳正午换算过来是 {noon:%H:%M}，"
              f"偏了 {offset:.1f} 小时", file=sys.stderr)
        print("  这份坐标没有保存。用 --city 城市名或 --set 纬度,经度 给真实位置；"
              "确实要按异地坐标调度再加 --force。", file=sys.stderr)
        return 3
    if explicit:
        cfg.latitude, cfg.longitude = lat, lon
        save_config(cfg)
    times = solar.sun_times(now.date(), lat, lon, now.tzinfo)
    print(f"位置：{lat:.4f},{lon:.4f}（{source}{'：' + label if label else ''}）")
    if times.sunrise and times.sunset:
        print(f"今日日出 {times.sunrise:%H:%M}，日落 {times.sunset:%H:%M}")
    else:
        print(f"今日{'极昼' if times.kind == 'polar_day' else '极夜'}")
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    repo = Path(__file__).resolve().parents[2]
    launcher = repo / "bin" / "lightswitch"
    launcher.chmod(0o755)
    target = Path.home() / ".local" / "bin" / "lightswitch"
    target.parent.mkdir(parents=True, exist_ok=True)
    themes._replace_symlink(target, launcher)
    scheduler.install_units(target)
    print(f"命令入口：{target} → {launcher}")
    print(f"定时器：{scheduler.unit_dir()}/lightswitch.timer")
    print("下一步：lightswitch location --geoclue（桌面会弹授权），然后 lightswitch auto on")
    return 0


def cmd_uninstall(args: argparse.Namespace) -> int:
    scheduler.remove_units()
    target = Path.home() / ".local" / "bin" / "lightswitch"
    if target.is_symlink():
        target.unlink()
        print(f"已删除 {target}")
    print("定时器与命令入口已移除，主题保持现状")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    cfg = load_config()
    home = Path.home()
    icon_dirs = [home / ".icons", home / ".local" / "share" / "icons"]
    checks: list[tuple[str, bool, str]] = []
    for name in ("gtk-Light.css", "gtk-Dark.css"):
        path = themes.gtk4_dir() / name
        checks.append((f"libadwaita CSS {name}", path.exists(), str(path)))
    for variant in VARIANTS:
        spec = cfg.spec(variant)
        checks.append((f"{variant} 主题目录", (home / ".themes" / spec.gtk).is_dir(), str(home / ".themes" / spec.gtk)))
        found = next((d / spec.icons for d in icon_dirs if (d / spec.icons).is_dir()), None)
        checks.append((f"{variant} 图标包", found is not None, str(found or spec.icons)))
        if cfg.apply_shell and spec.shell:
            shell_css = home / ".themes" / spec.shell / "gnome-shell" / "gnome-shell.css"
            checks.append((f"{variant} shell 主题", shell_css.exists(), str(shell_css)))
    schema_ok = subprocess.run(["gsettings", "list-keys", themes.SHELL_SCHEMA], capture_output=True).returncode == 0
    checks.append(("user-theme 扩展 schema", schema_ok, themes.SHELL_SCHEMA))
    checks.append(("位置已设置", cfg.latitude is not None, f"{cfg.latitude},{cfg.longitude}"))
    checks.append(("systemd 用户管理器", scheduler.is_enabled() != "unknown", scheduler.is_enabled()))
    failed = 0
    for name, ok, detail in checks:
        print(f"{'✓' if ok else '✗'} {name}  {detail}")
        failed += 0 if ok else 1
    print(f"\n{'全部通过' if failed == 0 else f'{failed} 项未通过'}")
    return 0 if failed == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lightswitch", description="按日出日落切换 GTK 主题、图标与 libadwaita 配色")
    parser.add_argument("--version", action="version", version=f"lightswitch {VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)

    for name, func, help_text in (
        ("light", cmd_light, "切到浅色"),
        ("dark", cmd_dark, "切到深色"),
        ("toggle", cmd_toggle, "在当前基础上反向切换"),
        ("refresh", cmd_refresh, "按当前变体重新应用一遍（修软链、补 gsettings）"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--dry-run", action="store_true", help="只打印将要执行的动作")
        p.set_defaults(func=func)

    p = sub.add_parser("auto", help="启用或停止自动切换")
    p.add_argument("state", choices=("on", "off"))
    p.set_defaults(func=cmd_auto)

    p = sub.add_parser("stop", help="停止自动切换（等价于 auto off）")
    p.set_defaults(func=lambda a: cmd_auto(argparse.Namespace(state="off")))

    p = sub.add_parser("tick", help="按当前时间核对并切换一次（定时器调用）")
    p.add_argument("--at", help="用指定时间判定，便于验证：2026-10-29T18:30 或 18:30")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_tick)

    p = sub.add_parser("status", help="查看当前主题、日出日落与定时器状态")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("config", help="查看或修改浅色/深色所用的主题与图标")
    p.add_argument("action", choices=("show", "set"), nargs="?", default="show")
    p.add_argument("--light-theme", dest="light_theme")
    p.add_argument("--light-icons", dest="light_icons")
    p.add_argument("--light-shell", dest="light_shell")
    p.add_argument("--light-css", dest="light_css")
    p.add_argument("--dark-theme", dest="dark_theme")
    p.add_argument("--dark-icons", dest="dark_icons")
    p.add_argument("--dark-shell", dest="dark_shell")
    p.add_argument("--dark-css", dest="dark_css")
    p.add_argument("--buffer", type=int, help="浅色延后、深色提前的分钟数")
    p.add_argument("--shell", choices=("on", "off"), help="是否一并切换 GNOME Shell 面板主题")
    p.set_defaults(func=cmd_config)

    p = sub.add_parser("location", help="获取或设置地理位置")
    source = p.add_mutually_exclusive_group()
    source.add_argument("--city", help="按城市名解析坐标（只发送地名，与出口 IP 无关）")
    source.add_argument("--wifi", action="store_true", help="按周边 AP 指纹查询 BeaconDB（不含 IP 信息）")
    source.add_argument("--set", dest="set_coords", help="手动坐标：纬度,经度")
    source.add_argument("--geoclue", action="store_true", help="用系统定位服务（不推荐：可能与 AP 数据库无关，也不保证有授权提示）")
    source.add_argument("--ip", action="store_true", help="按出口 IP 猜（走 Clash TUN 等代理时拿到的是出口所在地）")
    source.add_argument("--clear", action="store_true", help="清除已保存的坐标")
    p.add_argument("--force", action="store_true", help="坐标与机器时区不符时仍然保存")
    p.add_argument("--timeout", type=int, default=45)
    p.set_defaults(func=cmd_location)

    p = sub.add_parser("install", help="安装命令入口与 systemd 用户定时器")
    p.set_defaults(func=cmd_install)

    p = sub.add_parser("uninstall", help="移除定时器与命令入口")
    p.set_defaults(func=cmd_uninstall)

    p = sub.add_parser("doctor", help="自检主题、图标、CSS 与定时器依赖")
    p.set_defaults(func=cmd_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
