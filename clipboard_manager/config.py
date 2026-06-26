from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "ClipNest"
LEGACY_APP_NAMES = ("FluxClip", "CrossClipboard")
MAX_ITEMS_PER_TAB = 500
DEFAULT_TABS = ["常用语", "代码", "地址", "账号"]
AUTO_HIDE_ON_PASTE = True


def _has_database(path: Path) -> bool:
    return (path / "clipboard.db").exists()


def default_hotkey() -> str:
    if sys.platform == "darwin":
        return "Cmd+Shift+V"
    return "Ctrl+Shift+V"


def app_data_dir() -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("APPDATA", Path.home()))
        new_path = root / APP_NAME
        for legacy_name in LEGACY_APP_NAMES:
            legacy_path = root / legacy_name
            if _has_database(legacy_path):
                return legacy_path
        return new_path
    if sys.platform == "darwin":
        new_path = Path.home() / "Library" / "Application Support" / APP_NAME
        for legacy_name in LEGACY_APP_NAMES:
            legacy_path = Path.home() / "Library" / "Application Support" / legacy_name
            if _has_database(legacy_path):
                return legacy_path
        return new_path
    return Path.home() / f".{APP_NAME.lower()}"


def database_path() -> Path:
    data_dir = app_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "clipboard.db"
