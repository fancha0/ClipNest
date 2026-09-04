from __future__ import annotations

import json
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QWidget

from .titlebar_theme import apply_titlebar_theme

_dialog_size_cache: dict[str, tuple[int, int]] = {}

# Caption colors for dialogs, kept in sync with the app theme by set_dialog_titlebar_theme().
_titlebar_state: dict[str, object] = {"dark": False, "caption": None, "text": None}


def set_dialog_titlebar_theme(
    dark: bool,
    caption_hex: str | None = None,
    text_hex: str | None = None,
) -> None:
    """Remember the caption style so every dialog opens with a themed title bar."""
    _titlebar_state["dark"] = bool(dark)
    _titlebar_state["caption"] = caption_hex
    _titlebar_state["text"] = text_hex


def get_dialog_size(key: str) -> tuple[int, int] | None:
    return _dialog_size_cache.get(key)


def store_dialog_size(key: str, size: tuple[int, int]) -> None:
    _dialog_size_cache[key] = (max(1, int(size[0])), max(1, int(size[1])))


def load_dialog_sizes_from_setting(raw: str) -> None:
    try:
        data = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return
    if not isinstance(data, dict):
        return
    for key, value in data.items():
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            continue
        try:
            store_dialog_size(str(key), (int(value[0]), int(value[1])))
        except (TypeError, ValueError):
            continue


def dump_dialog_sizes_to_setting() -> str:
    return json.dumps(
        {key: list(size) for key, size in _dialog_size_cache.items()}
    )


class ResizableDialog(QDialog):
    """Dialog that remembers its size and offers a maximize button."""

    _size_key = ""
    _default_size = (640, 560)
    _min_size = (420, 360)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, False)
        self.setMinimumSize(
            max(1, int(self._min_size[0])),
            max(1, int(self._min_size[1])),
        )
        stored = get_dialog_size(self._size_key) if self._size_key else None
        if stored is not None:
            self.resize(*stored)
        else:
            self.resize(*self._default_size)

    def closeEvent(self, event) -> None:
        self._remember_size()
        super().closeEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._apply_titlebar_theme()

    def _apply_titlebar_theme(self) -> None:
        try:
            hwnd = int(self.winId())
        except Exception:
            return
        apply_titlebar_theme(
            hwnd,
            dark=bool(_titlebar_state.get("dark")),
            caption_hex=_titlebar_state.get("caption"),  # type: ignore[arg-type]
            text_hex=_titlebar_state.get("text"),  # type: ignore[arg-type]
        )

    def done(self, result: int) -> None:
        self._remember_size()
        super().done(result)

    def _remember_size(self) -> None:
        if not self._size_key:
            return
        if self.windowState() & Qt.WindowState.WindowMaximized:
            return
        store_dialog_size(self._size_key, (self.width(), self.height()))
