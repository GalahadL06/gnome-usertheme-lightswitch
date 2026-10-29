"""地理位置来源：GeoClue2（系统授权弹窗）、IP 兜底、手动坐标。"""

from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.parse
import urllib.request

BEACONDB_ENDPOINT = "https://api.beacondb.net/v1/geolocate"
GEOCODE_ENDPOINT = "https://geocoding-api.open-meteo.com/v1/search"


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


def from_city(name: str, timeout: int = 10) -> tuple[float, float, str]:
    """按地名解析坐标：请求里只有城市名，与出口 IP 无关；返回坐标与匹配到的完整地名。"""
    query = urllib.parse.urlencode({"name": name, "count": 1, "language": "zh", "format": "json"})
    req = urllib.request.Request(f"{GEOCODE_ENDPOINT}?{query}", headers={"User-Agent": "lightswitch"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    results = payload.get("results") or []
    if not results:
        raise RuntimeError(f"地名解析不到 {name}，换个写法或用 --set 直接给坐标")
    hit = results[0]
    label = " ".join(str(part) for part in (hit.get("name"), hit.get("admin1"), hit.get("country")) if part)
    return float(hit["latitude"]), float(hit["longitude"]), label


def nearby_access_points(limit: int = 8) -> list[dict[str, object]]:
    """用 NetworkManager 扫一遍周边 AP，只取 BSSID 与信号强度，不含任何 IP 信息。"""
    proc = subprocess.run(
        ["nmcli", "-t", "-f", "BSSID,SIGNAL", "dev", "wifi", "list", "--rescan", "yes"],
        capture_output=True, text=True, timeout=40,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"扫描 WiFi 失败：{(proc.stderr or proc.stdout).strip()}")
    points: list[dict[str, object]] = []
    for line in proc.stdout.splitlines():
        bssid, _, signal = line.rpartition(":")
        bssid = bssid.replace("\\:", ":").strip().upper()
        if bssid.count(":") != 5 or not signal.strip().isdigit():
            continue
        points.append({"macAddress": bssid, "signalStrength": -int(signal.strip())})
    if not points:
        raise RuntimeError("没有扫到周边 AP（无线网卡未启用？）")
    points.sort(key=lambda point: point["signalStrength"])
    return points[:limit]


def from_wifi(limit: int = 8, timeout: int = 15) -> tuple[float, float]:
    """按 AP 指纹查询 BeaconDB；GeoClue 2.7 用的也是这个库，所以它给不出的坐标这里同样给不出。"""
    points = nearby_access_points(limit)
    body = json.dumps({"considerIp": False, "wifiAccessPoints": points}).encode("utf-8")
    req = urllib.request.Request(
        BEACONDB_ENDPOINT, data=body, headers={"Content-Type": "application/json", "User-Agent": "lightswitch"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise RuntimeError(
                f"BeaconDB 里没有这 {len(points)} 个 AP 的记录，AP 指纹定位在这里给不出结果；"
                "改用 lightswitch location --city 城市名"
            ) from exc
        raise RuntimeError(f"BeaconDB 查询失败：HTTP {exc.code}") from exc
    if "location" not in payload:
        raise RuntimeError(f"BeaconDB 未返回坐标：{payload}")
    return float(payload["location"]["lat"]), float(payload["location"]["lng"])
