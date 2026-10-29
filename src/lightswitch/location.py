"""地理位置来源：GeoClue2（系统授权弹窗）、IP 兜底、手动坐标。"""

from __future__ import annotations

import json
import urllib.request


def from_geoclue(timeout: int = 45) -> tuple[float, float]:
    """经 GeoClue2 取坐标；GNOME 会话会弹出授权提示，拒绝或超时抛 RuntimeError。"""
    try:
        import gi

        gi.require_version("Geoclue", "2.0")
        from gi.repository import Geoclue, GLib
    except (ImportError, ValueError) as exc:
        raise RuntimeError(f"缺少 python3-gi 或 Geoclue 绑定：{exc}") from exc

    loop = GLib.MainLoop()
    result: dict[str, object] = {}

    def on_ready(source, res, _data=None):
        try:
            simple = Geoclue.Simple.new_finish(res)
            loc = simple.get_location()
            result["coords"] = (loc.get_property("latitude"), loc.get_property("longitude"))
        except GLib.Error as exc:
            result["error"] = exc.message
        loop.quit()

    Geoclue.Simple.new("lightswitch", Geoclue.AccuracyLevel.CITY, None, on_ready)
    GLib.timeout_add_seconds(timeout, lambda: (result.setdefault("error", "授权超时"), loop.quit(), False)[2])
    loop.run()
    if "coords" in result:
        lat, lon = result["coords"]  # type: ignore[misc]
        return float(lat), float(lon)
    raise RuntimeError(f"GeoClue 未返回坐标：{result.get('error')}")


def from_ip(timeout: int = 10) -> tuple[float, float]:
    """按出口 IP 猜坐标，仅作兜底；走代理或 VPN 时结果会偏离实际位置。"""
    req = urllib.request.Request("https://ipinfo.io/json", headers={"User-Agent": "lightswitch"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    loc = payload.get("loc") or ""
    lat, _, lon = loc.partition(",")
    if not lat or not lon:
        raise RuntimeError(f"IP 定位失败：{payload}")
    return float(lat), float(lon)


def parse_coords(text: str) -> tuple[float, float]:
    parts = [p.strip() for p in text.replace("，", ",").split(",")]
    if len(parts) != 2:
        raise ValueError("坐标格式应为 纬度,经度，例如 39.9042,116.4074")
    lat, lon = float(parts[0]), float(parts[1])
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError("坐标超出范围")
    return lat, lon
