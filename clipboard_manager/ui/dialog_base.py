from __future__ import annotations

import json
import logging
import sys
from typing import Optional

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout, QWidget

from .frosted_overlay import FrostedOverlay
from .theme import current_theme_tokens
from .title_bar import TitleBar
from .window_effects import apply_acrylic, argb_tint, disable_backdrop

logger = logging.getLogger(__name__)

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
    """Glass dialog shell with a themed title bar and remembered size."""

    _size_key = ""
    _default_size = (640, 560)
    _min_size = (420, 360)
    _frameless_glass = True
    _frameless_resize = True
    _maximizable = True
    _show_titlebar_close = True

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, False)
        self._frosted_overlay: Optional[FrostedOverlay] = None
        self.setProperty("glassDialog", True)
        if self._frameless_glass:
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self._build_glass_shell()
        else:
            self.content_layout = QVBoxLayout(self)
            self.content_layout.setContentsMargins(18, 14, 18, 16)
            self.content_layout.setSpacing(10)
        self.setMinimumSize(
            max(1, int(self._min_size[0])),
            max(1, int(self._min_size[1])),
        )
        stored = get_dialog_size(self._size_key) if self._size_key else None
        if stored is not None:
            self.resize(*stored)
        else:
            self.resize(*self._default_size)

    def _build_glass_shell(self) -> None:
        shell = QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        self._glass_root = QWidget(self)
        self._glass_root.setObjectName("glassDialogRoot")
        shell.addWidget(self._glass_root)

        root = QVBoxLayout(self._glass_root)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(0)

        app = QApplication.instance()
        app_icon = app.windowIcon() if app is not None else None
        icon_pixmap = (
            app_icon.pixmap(18, 18)
            if app_icon is not None and not app_icon.isNull()
            else None
        )
        self._title_bar = TitleBar(self.windowTitle(), icon_pixmap, self._glass_root)
        self._title_bar.set_collapse_visible(False)
        self._title_bar.set_close_visible(self._show_titlebar_close)
        self._title_bar.set_maximize_enabled(self._maximizable)
        self._title_bar.quit_requested.connect(self.reject)
        root.addWidget(self._title_bar)

        self._content_host = QWidget(self._glass_root)
        self._content_host.setObjectName("glassDialogContent")
        root.addWidget(self._content_host, 1)
        self.content_layout = QVBoxLayout(self._content_host)
        self.content_layout.setContentsMargins(18, 14, 18, 16)
        self.content_layout.setSpacing(10)

        self._frosted_overlay = FrostedOverlay(self._glass_root)
        self._frosted_overlay.setGeometry(self._glass_root.rect())
        self._frosted_overlay.raise_()

    def setWindowTitle(self, title: str) -> None:
        super().setWindowTitle(title)
        bar = getattr(self, "_title_bar", None)
        if bar is not None:
            bar.set_title(title)

    def closeEvent(self, event) -> None:
        self._remember_size()
        super().closeEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._frameless_glass:
            self._apply_titlebar_theme()
            return
        tokens = current_theme_tokens()
        self._title_bar.apply_theme(tokens)
        self._apply_glass_backdrop(tokens)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        overlay = getattr(self, "_frosted_overlay", None)
        if overlay is not None:
            overlay.setGeometry(self._glass_root.rect())
            overlay.raise_()

    def _apply_glass_backdrop(self, tokens=None) -> None:
        tokens = tokens or current_theme_tokens()
        try:
            hwnd = int(self.winId())
        except Exception:
            return
        if tokens.backdrop_blur and tokens.glass_strength == "transparent":
            apply_acrylic(hwnd, argb_tint(tokens.main_window_bg, 120))
        else:
            disable_backdrop(hwnd)

    def nativeEvent(self, event_type, message):
        if (
            self._frameless_glass
            and self._frameless_resize
            and sys.platform == "win32"
            and event_type == b"windows_generic_MSG"
        ):
            try:
                import ctypes
                from ctypes import wintypes

                msg = wintypes.MSG.from_address(int(message))
                if msg.message == 0x0084 and not self.isMaximized():  # WM_NCHITTEST
                    x = ctypes.c_short(msg.lParam & 0xFFFF).value
                    y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
                    dpr = self.devicePixelRatioF() or 1.0
                    local = self.mapFromGlobal(QPoint(int(x / dpr), int(y / dpr)))
                    code = self._resize_hit_code(local)
                    if code:
                        return True, code
            except Exception:
                logger.debug("frameless dialog WM_NCHITTEST failed", exc_info=True)
        return super().nativeEvent(event_type, message)

    def _resize_hit_code(self, local: QPoint) -> int:
        border = 6
        width = self.width()
        height = self.height()
        x = local.x()
        y = local.y()
        left = x <= border
        right = x >= width - border
        top = y <= border
        bottom = y >= height - border
        if top and left:
            return 13  # HTTOPLEFT
        if top and right:
            return 14  # HTTOPRIGHT
        if bottom and left:
            return 16  # HTBOTTOMLEFT
        if bottom and right:
            return 17  # HTBOTTOMRIGHT
        if left:
            return 10  # HTLEFT
        if right:
            return 11  # HTRIGHT
        if top:
            return 12  # HTTOP
        if bottom:
            return 15  # HTBOTTOM
        return 0

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
