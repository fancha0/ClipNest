from __future__ import annotations

import json
import hashlib
import logging
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
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


def cleanup_update_temp_dirs(max_age_seconds: int = 7 * 24 * 3600) -> None:
    """Remove stale update download/extract directories left by interrupted updates."""
    now = time.time()
    temp_root = tempfile.gettempdir()
    for entry in os.scandir(temp_root):
        if not entry.is_dir() or not entry.name.startswith("clipnest-"):
            continue
        try:
            if now - entry.stat().st_mtime > max_age_seconds:
                shutil.rmtree(entry.path, ignore_errors=True)
        except OSError:
            continue

_REPO = "fancha0/ClipNest"
_API_URL = f"https://api.github.com/repos/{_REPO}/releases/latest"
_ASSET_NAME = "ClipNest-Windows.zip"
_REQUEST_TIMEOUT = 15
_MAX_UPDATE_SIZE = 1024 * 1024 * 1024
_MAX_UPDATE_ENTRIES = 100_000
_MAX_UNPACKED_SIZE = 2 * 1024 * 1024 * 1024

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
    sha256 = str(payload.get("sha256") or "").strip().lower()
    if not version or not url or not re.fullmatch(r"[0-9a-f]{64}", sha256):
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
        "sha256": sha256,
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


def validate_update_archive(zip_path: str) -> str | None:
    if not zipfile.is_zipfile(zip_path):
        return "更新包已损坏，请重新下载。"
    try:
        with zipfile.ZipFile(zip_path) as archive:
            infos = archive.infolist()
            if len(infos) > _MAX_UPDATE_ENTRIES:
                return "更新包文件数量异常。"
            total_size = 0
            names: set[str] = set()
            has_executable = False
            for info in infos:
                normalized = info.filename.replace("\\", "/")
                if (normalized.startswith("/") or ".." in normalized.split("/")
                        or re.match(r"^[A-Za-z]:", normalized)
                        or normalized in names):
                    return "更新包包含不安全或重复的文件路径。"
                names.add(normalized)
                total_size += info.file_size
                if total_size > _MAX_UNPACKED_SIZE:
                    return "更新包解压体积超过限制。"
                if normalized == "ClipNest.exe":
                    has_executable = True
            if not has_executable:
                return "更新包缺少 ClipNest.exe。"
            if archive.testzip() is not None:
                return "更新包内容校验失败，请重新下载。"
    except (OSError, zipfile.BadZipFile, RuntimeError, zipfile.LargeZipFile) as exc:
        return f"更新包结构无效：{exc}"
    return None


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
            "sha256": str(asset.get("digest") or "").removeprefix("sha256:").lower(),
        }
        if not re.fullmatch(r"[0-9a-f]{64}", info["sha256"]):
            self._signals.failed.emit("GitHub 发布信息缺少有效的 SHA-256 摘要")
            return
        logger.info("[Update] latest release = %s", info["tag"])
        self._signals.finished.emit(info)


class _DownloadSignals(QObject):
    progress = Signal(int, int)
    finished = Signal(str, str)
    failed = Signal(str)


class _DownloadTask(QRunnable):
    def __init__(self, signals: _DownloadSignals, url: str, version: str,
                 expected_size: int = 0, expected_sha256: str = "") -> None:
        super().__init__()
        self._signals = signals
        self._url = url
        self._version = version
        self._expected_size = int(expected_size or 0)
        self._expected_sha256 = str(expected_sha256 or "").lower()

    def run(self) -> None:
        temp_dir = tempfile.mkdtemp(prefix="clipnest-download-")
        zip_path = os.path.join(temp_dir, f"ClipNest-{_ASSET_NAME}")
        try:
            if not re.fullmatch(r"[0-9a-f]{64}", self._expected_sha256):
                raise ValueError("发布信息缺少有效的 SHA-256 摘要。")
            request = urllib.request.Request(
                self._url, headers={"User-Agent": "ClipNest"}
            )
            with urllib.request.urlopen(
                request, timeout=_REQUEST_TIMEOUT, context=_build_ssl_context()
            ) as response:
                total = int(response.headers.get("Content-Length") or 0)
                if total > _MAX_UPDATE_SIZE or (
                    self._expected_size and total and total != self._expected_size
                ):
                    raise ValueError("更新包大小与发布信息不符。")
                received = 0
                digest = hashlib.sha256()
                with open(zip_path, "wb") as output:
                    while True:
                        chunk = response.read(64 * 1024)
                        if not chunk:
                            break
                        received += len(chunk)
                        if received > _MAX_UPDATE_SIZE:
                            raise ValueError("更新包超过允许的最大大小。")
                        output.write(chunk)
                        digest.update(chunk)
                        self._signals.progress.emit(received, total)
            if self._expected_size and received != self._expected_size:
                raise ValueError("更新包下载不完整。")
            if self._expected_sha256 and digest.hexdigest() != self._expected_sha256:
                raise ValueError("更新包 SHA-256 校验失败。")
            logger.info("[Update] downloaded %s -> %s", self._version, zip_path)
            self._signals.finished.emit(zip_path, self._version)
        except Exception as exc:
            shutil.rmtree(temp_dir, ignore_errors=True)
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
        cleanup_update_temp_dirs()
        self._check_signals = _CheckSignals()
        self._check_signals.finished.connect(self.check_succeeded)
        self._check_signals.failed.connect(self.check_failed)
        self._download_signals = _DownloadSignals()
        self._download_signals.progress.connect(self.download_progress)
        self._download_signals.finished.connect(self.download_succeeded)
        self._download_signals.failed.connect(self.download_failed)

    def check_async(self) -> None:
        QThreadPool.globalInstance().start(_CheckTask(self._check_signals))

    def download_async(self, url: str, version: str, expected_size: int = 0,
                       expected_sha256: str = "") -> None:
        QThreadPool.globalInstance().start(
            _DownloadTask(
                self._download_signals, url, version, expected_size, expected_sha256
            )
        )

    def apply_update(self, zip_path: str) -> tuple[bool, str]:
        """Extract the new build and hand off to a detached updater script."""
        from PySide6.QtWidgets import QApplication

        if not is_frozen():
            return False, "开发模式下无法自动安装更新。"
        validation_error = validate_update_archive(zip_path)
        if validation_error:
            return False, validation_error

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
