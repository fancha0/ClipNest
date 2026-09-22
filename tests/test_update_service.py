from __future__ import annotations

import unittest

from clipboard_manager.services.update_service import (
    _parse_manifest,
    _pick_asset,
    build_updater_bat,
    is_newer,
    parse_version,
)


class VersionParseTests(unittest.TestCase):
    def test_parse_version(self) -> None:
        self.assertEqual(parse_version("v1.2.3"), (1, 2, 3))
        self.assertEqual(parse_version("0.1.0"), (0, 1, 0))
        self.assertEqual(parse_version("v2"), (2,))
        self.assertEqual(parse_version(""), (0,))
        self.assertEqual(parse_version("v1.2.0-beta"), (1, 2, 0))

    def test_is_newer(self) -> None:
        self.assertTrue(is_newer("0.2.0", "0.1.0"))
        self.assertTrue(is_newer("v1.0.0", "0.9.9"))
        self.assertFalse(is_newer("0.1.0", "0.1.0"))
        self.assertFalse(is_newer("0.0.9", "0.1.0"))


class PickAssetTests(unittest.TestCase):
    def test_prefers_canonical_asset_name(self) -> None:
        release = {
            "assets": [
                {"name": "other.zip", "browser_download_url": "https://x/other.zip"},
                {"name": "ClipNest-Windows.zip", "browser_download_url": "https://x/canon.zip"},
            ]
        }
        self.assertEqual(_pick_asset(release)["name"], "ClipNest-Windows.zip")

    def test_falls_back_to_any_zip(self) -> None:
        release = {"assets": [{"name": "whatever.zip"}]}
        self.assertIsNotNone(_pick_asset(release))

    def test_none_when_no_zip(self) -> None:
        self.assertIsNone(_pick_asset({"assets": [{"name": "readme.txt"}]}))
        self.assertIsNone(_pick_asset({}))


class ManifestParseTests(unittest.TestCase):
    def test_parse_manifest(self) -> None:
        info = _parse_manifest(
            {
                "version": "v0.2.0",
                "notes": "修复了一些问题",
                "url": "https://example.com/clipnest/ClipNest-Windows.zip",
                "size": 12345,
            }
        )
        self.assertIsNotNone(info)
        self.assertEqual(info["version"], "0.2.0")
        self.assertEqual(info["tag"], "v0.2.0")
        self.assertEqual(info["body"], "修复了一些问题")
        self.assertEqual(info["size"], 12345)

    def test_manifest_requires_version_and_url(self) -> None:
        self.assertIsNone(_parse_manifest({"version": "0.2.0"}))
        self.assertIsNone(_parse_manifest({"url": "https://x/y.zip"}))
        self.assertIsNone(_parse_manifest({}))


class UpdaterBatTests(unittest.TestCase):
    def test_bat_contains_copy_launch_and_self_delete(self) -> None:
        bat = build_updater_bat("C:\\tmp\\new", "C:\\apps\\ClipNest", "ClipNest.exe")
        self.assertIn("robocopy", bat)
        self.assertIn('"C:\\tmp\\new"', bat)
        self.assertIn('"C:\\apps\\ClipNest"', bat)
        self.assertIn("/R:2", bat)
        self.assertIn('start "" "C:\\apps\\ClipNest\\ClipNest.exe"', bat)
        self.assertIn('del "%~f0"', bat)


class HttpJsonTests(unittest.TestCase):
    def test_http_json_tolerates_utf8_bom(self) -> None:
        import io
        from unittest import mock

        from clipboard_manager.services import update_service

        fake = io.BytesIO(b"\xef\xbb\xbf{\"version\": \"0.2.0\"}")
        fake.headers = {}
        with mock.patch.object(
            update_service.urllib.request, "urlopen", return_value=fake
        ):
            data = update_service._http_json("https://example.com/latest.json")
        self.assertEqual(data["version"], "0.2.0")


if __name__ == "__main__":
    unittest.main()
