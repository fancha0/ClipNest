from __future__ import annotations

import unittest

from clipboard_manager.services.update_service import (
    UpdateService,
    _parse_manifest,
    _pick_asset,
    build_updater_bat,
    is_newer,
    parse_version,
    validate_update_archive,
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
                "sha256": "a" * 64,
            }
        )
        self.assertIsNotNone(info)
        self.assertEqual(info["version"], "0.2.0")
        self.assertEqual(info["tag"], "v0.2.0")
        self.assertEqual(info["body"], "修复了一些问题")
        self.assertEqual(info["size"], 12345)
        self.assertEqual(info["sha256"], "a" * 64)

    def test_manifest_requires_version_and_url(self) -> None:
        self.assertIsNone(_parse_manifest({"version": "0.2.0"}))
        self.assertIsNone(_parse_manifest({"url": "https://x/y.zip"}))
        self.assertIsNone(_parse_manifest({}))

    def test_manifest_requires_sha256(self) -> None:
        self.assertIsNone(
            _parse_manifest(
                {"version": "0.2.0", "url": "https://x/y.zip", "sha256": "bad"}
            )
        )

    def test_manifest_includes_optional_setup_asset(self) -> None:
        info = _parse_manifest(
            {
                "version": "0.2.0",
                "url": "https://x/y.zip",
                "size": 10,
                "sha256": "a" * 64,
                "setup_url": "https://x/ClipNest-Setup.exe",
                "setup_size": 20,
                "setup_sha256": "b" * 64,
            }
        )
        self.assertIsNotNone(info)
        self.assertEqual(info["setup_url"], "https://x/ClipNest-Setup.exe")
        self.assertEqual(info["setup_size"], 20)
        self.assertEqual(info["setup_sha256"], "b" * 64)

    def test_invalid_setup_digest_disables_setup_asset(self) -> None:
        info = _parse_manifest(
            {
                "version": "0.2.0",
                "url": "https://x/y.zip",
                "sha256": "a" * 64,
                "setup_url": "https://x/ClipNest-Setup.exe",
                "setup_sha256": "bad",
            }
        )
        self.assertEqual(info["setup_url"], "")


class UpdateInfoSelectionTests(unittest.TestCase):
    def _info(self) -> dict:
        return {
            "version": "0.2.0",
            "url": "https://x/ClipNest-Windows.zip",
            "size": 10,
            "sha256": "a" * 64,
            "setup_url": "https://x/ClipNest-Setup.exe",
            "setup_size": 20,
            "setup_sha256": "b" * 64,
        }

    def test_installed_build_prefers_setup(self) -> None:
        from unittest import mock

        from clipboard_manager.services import update_service

        with mock.patch.object(
            update_service, "is_installed_install", return_value=True
        ):
            selected = UpdateService.prepare_update_info(self._info())
        self.assertEqual(selected["kind"], "setup")
        self.assertEqual(selected["url"], "https://x/ClipNest-Setup.exe")
        self.assertEqual(selected["size"], 20)
        self.assertEqual(selected["sha256"], "b" * 64)

    def test_portable_build_uses_zip(self) -> None:
        from unittest import mock

        from clipboard_manager.services import update_service

        with mock.patch.object(
            update_service, "is_installed_install", return_value=False
        ):
            selected = UpdateService.prepare_update_info(self._info())
        self.assertEqual(selected["kind"], "zip")
        self.assertEqual(selected["url"], "https://x/ClipNest-Windows.zip")
        self.assertEqual(selected["size"], 10)


class SetupUpdateTests(unittest.TestCase):
    def test_setup_launch_is_silent_and_uses_install_dir(self) -> None:
        import tempfile
        from unittest import mock

        from clipboard_manager.services import update_service

        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as setup_file:
            setup_file.write(b"MZ")
            setup_path = setup_file.name
        service = UpdateService()
        try:
            with mock.patch.object(
                update_service, "is_installed_install", return_value=True
            ), mock.patch(
                "PySide6.QtWidgets.QApplication.applicationDirPath",
                return_value=r"C:\Apps\ClipNest",
            ), mock.patch.object(
                update_service.subprocess, "Popen"
            ) as popen:
                ok, error = service._apply_setup_update(setup_path)
            self.assertTrue(ok, error)
            args = popen.call_args.args[0]
            self.assertIn("/VERYSILENT", args)
            self.assertIn("/SUPPRESSMSGBOXES", args)
            self.assertIn("/CLOSEAPPLICATIONS", args)
            self.assertIn(r"/DIR=C:\Apps\ClipNest", args)
            self.assertNotIn("/RESTARTAPPLICATIONS", args)
            self.assertIn("startupinfo", popen.call_args.kwargs)
        finally:
            import os

            os.remove(setup_path)


class UpdaterBatTests(unittest.TestCase):
    def test_bat_contains_copy_launch_and_self_delete(self) -> None:
        bat = build_updater_bat("C:\\tmp\\new", "C:\\apps\\ClipNest", "ClipNest.exe")
        self.assertIn("robocopy", bat)
        self.assertIn('"C:\\tmp\\new"', bat)
        self.assertIn('"C:\\apps\\ClipNest"', bat)
        self.assertIn("/R:2", bat)
        self.assertIn('start "" "C:\\apps\\ClipNest\\ClipNest.exe"', bat)
        self.assertIn('del "%~f0"', bat)
        self.assertIn('if errorlevel 8 goto update_failed', bat)
        self.assertIn('/LOG:"%TEMP%\\clipnest-update.log"', bat)
        self.assertIn('clipnest-update-error.txt', bat)
        self.assertNotIn('pause', bat)
        failure_branch = bat.split(':update_failed\r\n', 1)[1]
        self.assertIn('start ""', failure_branch)


class UpdateErrorMarkerTests(unittest.TestCase):
    def test_consume_error_marker_reads_once(self) -> None:
        import tempfile
        from unittest import mock

        from clipboard_manager.services import update_service

        with tempfile.TemporaryDirectory() as directory:
            marker = f"{directory}/clipnest-update-error.txt"
            with open(marker, "w", encoding="utf-8") as handle:
                handle.write("failed")
            with mock.patch.object(
                update_service.tempfile, "gettempdir", return_value=directory
            ):
                self.assertTrue(update_service.consume_update_error())
                self.assertFalse(update_service.consume_update_error())


class UpdateArchiveValidationTests(unittest.TestCase):
    def test_requires_application_executable(self) -> None:
        import tempfile
        import zipfile

        with tempfile.TemporaryDirectory() as directory:
            path = f"{directory}/package.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("readme.txt", "not an app")
            self.assertIn("缺少 ClipNest.exe", validate_update_archive(path))

    def test_rejects_path_traversal(self) -> None:
        import tempfile
        import zipfile

        with tempfile.TemporaryDirectory() as directory:
            path = f"{directory}/package.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("ClipNest.exe", "binary")
                archive.writestr("../outside.txt", "bad")
            self.assertIn("不安全", validate_update_archive(path))

    def test_accepts_valid_update_archive(self) -> None:
        import tempfile
        import zipfile

        with tempfile.TemporaryDirectory() as directory:
            path = f"{directory}/package.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("ClipNest.exe", "binary")
                archive.writestr("_internal/library.dll", "library")
            self.assertIsNone(validate_update_archive(path))


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


class SslDefenseTests(unittest.TestCase):
    def test_sanitize_ssl_env_removes_stale_paths(self) -> None:
        import os
        from unittest import mock

        from clipboard_manager.services import update_service

        env = {
            "SSL_CERT_FILE": r"C:\gone\cacert.pem",
            "SSL_CERT_DIR": r"C:\gone\certs",
            "REQUESTS_CA_BUNDLE": r"C:\gone\bundle.pem",
            "PATH": os.environ.get("PATH", ""),
        }
        with mock.patch.dict(os.environ, env, clear=True):
            update_service._sanitize_ssl_env()
            self.assertNotIn("SSL_CERT_FILE", os.environ)
            self.assertNotIn("SSL_CERT_DIR", os.environ)
            self.assertNotIn("REQUESTS_CA_BUNDLE", os.environ)
            self.assertIn("PATH", os.environ)

    def test_sanitize_ssl_env_keeps_existing_paths(self) -> None:
        import os
        import tempfile
        from unittest import mock

        from clipboard_manager.services import update_service

        with tempfile.NamedTemporaryFile(suffix=".pem") as tmp:
            with mock.patch.dict(os.environ, {"SSL_CERT_FILE": tmp.name}, clear=True):
                update_service._sanitize_ssl_env()
                self.assertEqual(os.environ["SSL_CERT_FILE"], tmp.name)

    def test_build_ssl_context_returns_context(self) -> None:
        from clipboard_manager.services import update_service

        context = update_service._build_ssl_context()
        self.assertIsInstance(context, update_service.ssl.SSLContext)
        self.assertTrue(context.check_hostname)


if __name__ == "__main__":
    unittest.main()
