from __future__ import annotations

import json
import logging
import os
import re
import ssl
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from typing import Optional

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from ..version import APP_VERSION

logger = logging.getLogger(__name__)


def _sanitize_ssl_env() -> None:
    """Drop leftover SSL env vars pointing at files that no longer exist.

    Machines that once had Anaconda/Git or similar tools often keep
    SSL_CERT_FILE / SSL_CERT_DIR / REQUESTS_CA_BUNDLE pointing into an
    uninstalled program folder, which breaks HTTPS requests.
    """
    for key in ("SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE"):
        path = os.environ.get(key)
        if path and not os.path.exists(path):
            logger.warning("[Update] ignoring stale %s=%s", key, path)
            os.environ.pop(key, None)


def _build_ssl_context() -> ssl.SSLContext:
    """Default context; falls back to the Windows certificate store directly."""
    _sanitize_ssl_env()
    try:
        return ssl.create_default_context()
    except Exception:
        logger.exception("[Update] create_default_context failed, using Windows store")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    if sys.platform == "win32":
        try:
            for storename in ("CA", "ROOT"):
                for cert, encoding, _trust in ssl.enum_certificates(storename):
                    if encoding == "x509_asn":
                        context.load_verify_locations(cadata=cert)
        except Exception:
            logger.exception("[Update] loading Windows certificate store failed")
    return context

_REPO = "fancha0/ClipNest"
_API_URL = f"https://api.github.com/repos/{_REPO}/releases/latest"
_ASSET_NAME = "ClipNest-Windows.zip"
_REQUEST_TIMEOUT = 15

# Own-server update manifest, e.g. "https://clipnest.example.com/clipnest/latest.json".
# When set, it is checked first; the GitHub release is only a fallback for
# users who can reach GitHub (helps when the own server is down).
UPDATE_MANIFEST_URL = "https://fn.lshiya.top:18443/clipnest/latest.json"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def parse_version(text: str) -> tuple[int, ...]:
    cleaned = re.sub(r"^v", "", str(text or "").strip(), flags=re.IGNORECASE)
    parts: list[int] = []
    for chunk in cleaned.split("."):
        digits = re.match(r"\d+", chunk)
        parts.append(int(digits.group(0)) if digits else 0)
    return tuple(parts) if parts else (0,)


def is_newer(remote: str, local: str = APP_VERSION) -> bool:
    return parse_version(remote) > parse_version(local)


def _pick_asset(release: dict) -> Optional[dict]:
    assets = release.get("assets") or []
    for asset in assets:
        if asset.get("name") == _ASSET_NAME:
            return asset
    for asset in assets:
        if str(asset.get("name") or "").endswith(".zip"):
            return asset
    return None


def _parse_manifest(payload: dict) -> Optional[dict]:
    """Parse an own-server manifest: {version, notes, url, size}."""
    version = str(payload.get("version") or "").strip().lstrip("vV")
    url = str(payload.get("url") or "").strip()
    if not version or not url:
        return None
    try:
        size = int(payload.get("size") or 0)
    except (TypeError, ValueError):
        size = 0
    return {
        "version": version,
        "tag": f"v{version}",
        "body": str(payload.get("notes") or payload.get("body") or ""),
        "url": url,
        "size": size,
    }


def _http_json(url: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "ClipNest",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(
        request, timeout=_REQUEST_TIMEOUT, context=_build_ssl_context()
    ) as response:
        return json.loads(response.read().decode("utf-8-sig"))


def build_updater_bat(source_dir: str, install_dir: str, exe_name: str) -> str:
    return (
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        "timeout /t 2 /nobreak >nul\r\n"
        f'robocopy "{source_dir}" "{install_dir}" /E /NFL /NDL /NJH /NJS /NP /R:2 /W:2\r\n'
        f'start "" "{install_dir}\\{exe_name}"\r\n'
        '(goto) 2>nul & del "%~f0"\r\n'
    )


class _CheckSignals(QObject):
    finished = Signal(dict)
    failed = Signal(str)


class _CheckTask(QRunnable):
    def __init__(self, signals: _CheckSignals) -> None:
        super().__init__()
        self._signals = signals

    def run(self) -> None:
        errors: list[str] = []
        if UPDATE_MANIFEST_URL:
            try:
                parsed = _parse_manifest(_http_json(UPDATE_MANIFEST_URL))
                if parsed is not None:
                    logger.info("[Update] manifest latest = %s", parsed["tag"])
                    self._signals.finished.emit(parsed)
                    return
                errors.append("更新清单格式异常")
            except Exception as exc:
                logger.exception("[Update] manifest check failed")
                errors.append(str(exc))

        try:
            release = _http_json(_API_URL)
        except Exception as exc:
            logger.exception("[Update] github check failed")
            errors.append(str(exc))
            self._signals.failed.emit("；".join(errors))
            return

        tag = str(release.get("tag_name") or "").strip()
        asset = _pick_asset(release)
        if not tag or asset is None:
            errors.append("GitHub 发布信息格式异常")
            self._signals.failed.emit("；".join(errors))
            return
        info = {
            "version": tag.lstrip("vV"),
            "tag": tag,
            "body": str(release.get("body") or ""),
            "url": str(asset.get("browser_download_url") or ""),
            "size": int(asset.get("size") or 0),
        }
        logger.info("[Update] latest release = %s", info["tag"])
        self._signals.finished.emit(info)


class _DownloadSignals(QObject):
    progress = Signal(int, int)
    finished = Signal(str, str)
    failed = Signal(str)


class _DownloadTask(QRunnable):
    def __init__(self, signals: _DownloadSignals, url: str, version: str) -> None:
        super().__init__()
        self._signals = signals
        self._url = url
        self._version = version

    def run(self) -> None:
        temp_dir = tempfile.mkdtemp(prefix="clipnest-download-")
        zip_path = f"{temp_dir}\\ClipNest-{_ASSET_NAME}"
        try:
            request = urllib.request.Request(
                self._url, headers={"User-Agent": "ClipNest"}
            )
            with urllib.request.urlopen(
                request, timeout=_REQUEST_TIMEOUT, context=_build_ssl_context()
            ) as response:
                total = int(response.headers.get("Content-Length") or 0)
                received = 0
                with open(zip_path, "wb") as output:
                    while True:
                        chunk = response.read(64 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
                        received += len(chunk)
                        self._signals.progress.emit(received, total)
            logger.info("[Update] downloaded %s -> %s", self._version, zip_path)
            self._signals.finished.emit(zip_path, self._version)
        except Exception as exc:
            logger.exception("[Update] download failed")
            self._signals.failed.emit(str(exc))


class UpdateService(QObject):
    check_succeeded = Signal(dict)
    check_failed = Signal(str)
    download_progress = Signal(int, int)
    download_succeeded = Signal(str, str)
    download_failed = Signal(str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._check_signals = _CheckSignals()
        self._check_signals.finished.connect(self.check_succeeded)
        self._check_signals.failed.connect(self.check_failed)
        self._download_signals = _DownloadSignals()
        self._download_signals.progress.connect(self.download_progress)
        self._download_signals.finished.connect(self.download_succeeded)
        self._download_signals.failed.connect(self.download_failed)

    def check_async(self) -> None:
        QThreadPool.globalInstance().start(_CheckTask(self._check_signals))

    def download_async(self, url: str, version: str) -> None:
        QThreadPool.globalInstance().start(
            _DownloadTask(self._download_signals, url, version)
        )

    def apply_update(self, zip_path: str) -> tuple[bool, str]:
        """Extract the new build and hand off to a detached updater script."""
        from PySide6.QtWidgets import QApplication

        if not is_frozen():
            return False, "开发模式下无法自动安装更新。"
        if not zipfile.is_zipfile(zip_path):
            return False, "更新包已损坏，请重新下载。"

        install_dir = QApplication.applicationDirPath()
        extract_dir = tempfile.mkdtemp(prefix="clipnest-update-")
        try:
            with zipfile.ZipFile(zip_path) as archive:
                archive.extractall(extract_dir)
        except Exception as exc:
            return False, f"解压更新包失败：{exc}"

        exe_name = "ClipNest.exe"
        bat_path = f"{extract_dir}\\updater.bat"
        bat_content = build_updater_bat(extract_dir, install_dir, exe_name)
        try:
            with open(bat_path, "w", encoding="utf-8", newline="") as bat_file:
                bat_file.write(bat_content)
            subprocess.Popen(
                ["cmd", "/c", bat_path],
                creationflags=0x08000000,
                close_fds=True,
            )
        except Exception as exc:
            return False, f"启动安装程序失败：{exc}"
        logger.info("[Update] updater launched: %s -> %s", extract_dir, install_dir)
        return True, ""
