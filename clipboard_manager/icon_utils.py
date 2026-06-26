from __future__ import annotations

import ctypes
import logging
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QStyle

from .config import APP_NAME

logger = logging.getLogger(__name__)


def resolve_app_icon(app: QApplication | None = None) -> QIcon:
    candidates: list[Path] = []

    if getattr(sys, "_MEIPASS", None):
        base = Path(getattr(sys, "_MEIPASS"))
        candidates.extend(
            [
                base / "assets" / "clipnest.ico",
                base / "assets" / "clipnest.png",
            ]
        )

    project_root = Path(__file__).resolve().parent.parent
    candidates.extend(
        [
            project_root / "assets" / "clipnest.ico",
            project_root / "assets" / "clipnest.png",
        ]
    )

    for path in candidates:
        if not path.exists():
            continue
        icon = QIcon(str(path))
        if not icon.isNull():
            return icon

    instance = app or QApplication.instance()
    if instance is not None:
        exe_icon = QIcon(instance.applicationFilePath())
        if not exe_icon.isNull():
            return exe_icon
        return instance.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView)

    return QIcon()


def set_windows_app_user_model_id(app_id: str | None = None) -> None:
    if sys.platform != "win32":
        return
    final_id = app_id or f"{APP_NAME}.{APP_NAME}"
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(final_id)
    except Exception as exc:  # pragma: no cover - best effort on Windows.
        logger.warning("Failed to set AppUserModelID '%s': %s", final_id, exc)
