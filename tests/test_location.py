import json
import subprocess
import unittest
import urllib.error
from unittest import mock

from lightswitch import location

GEOCODE_PAYLOAD = {
    "results": [
        {
            "name": "巴黎",
            "latitude": 48.8566,
            "longitude": 2.3522,
            "country": "法国",
            "admin1": "法兰西岛",
        }
    ]
}

NMCLI_OUTPUT = """86\\:8E\\:3D\\:CE\\:33\\:5B:85
9C\\:09\\:71\\:9A\\:08\\:80:59
not-a-bssid:70
5C\\:7D\\:AE\\:CB\\:B7\\:3E:45
"""


def fake_urlopen(payload):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps(payload).encode()

    return mock.Mock(return_value=Response())


class CityTest(unittest.TestCase):
    def test_city_lookup_returns_coordinates_and_label(self):
        with mock.patch("urllib.request.urlopen", fake_urlopen(GEOCODE_PAYLOAD)):
            lat, lon, label = location.from_city("巴黎")
        self.assertAlmostEqual(lat, 48.8566)
        self.assertAlmostEqual(lon, 2.3522)
        self.assertEqual(label, "巴黎 法兰西岛 法国")

    def test_city_lookup_sends_only_the_name(self):
        opener = fake_urlopen(GEOCODE_PAYLOAD)
        with mock.patch("urllib.request.urlopen", opener):
            location.from_city("巴黎")
        url = opener.call_args[0][0].full_url
        self.assertIn("name=%E5%B7%B4%E9%BB%8E", url)
        self.assertNotIn("ip", url.lower())

    def test_unknown_city_explains_the_fallback(self):
        with mock.patch("urllib.request.urlopen", fake_urlopen({"results": []})):
            with self.assertRaises(RuntimeError) as ctx:
                location.from_city("没有这个地名")
        self.assertIn("--set", str(ctx.exception))


class WifiTest(unittest.TestCase):
    def test_nearby_access_points_parses_escaped_colons(self):
        proc = subprocess.CompletedProcess(args=[], returncode=0, stdout=NMCLI_OUTPUT, stderr="")
        with mock.patch("subprocess.run", return_value=proc):
            points = location.nearby_access_points()
        self.assertEqual([p["macAddress"] for p in points],
                         ["86:8E:3D:CE:33:5B", "9C:09:71:9A:08:80", "5C:7D:AE:CB:B7:3E"])
        self.assertEqual(points[0]["signalStrength"], -85)

    def test_wifi_payload_disables_ip_fallback(self):
        proc = subprocess.CompletedProcess(args=[], returncode=0, stdout=NMCLI_OUTPUT, stderr="")
        opener = fake_urlopen({"location": {"lat": 48.8, "lng": 2.3}, "accuracy": 30})
        with mock.patch("subprocess.run", return_value=proc), mock.patch("urllib.request.urlopen", opener):
            lat, lon = location.from_wifi()
        body = json.loads(opener.call_args[0][0].data.decode())
        self.assertFalse(body["considerIp"])
        self.assertAlmostEqual(lat, 48.8)
        self.assertAlmostEqual(lon, 2.3)

    def test_wifi_miss_points_at_city_lookup(self):
        proc = subprocess.CompletedProcess(args=[], returncode=0, stdout=NMCLI_OUTPUT, stderr="")
        error = urllib.error.HTTPError("url", 404, "Not Found", None, None)
        with mock.patch("subprocess.run", return_value=proc), \
                mock.patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(RuntimeError) as ctx:
                location.from_wifi()
        self.assertIn("--city", str(ctx.exception))


class CoordsTest(unittest.TestCase):
    def test_parse_coords_accepts_fullwidth_comma(self):
        self.assertEqual(location.parse_coords("48.86，2.35"), (48.86, 2.35))

    def test_parse_coords_rejects_out_of_range(self):
        for text in ("91,0", "0,181", "45"):
            with self.assertRaises(ValueError):
                location.parse_coords(text)


if __name__ == "__main__":
    unittest.main()
