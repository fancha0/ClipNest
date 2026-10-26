from __future__ import annotations

import json
from typing import Optional

from PySide6.QtCore import QEvent, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout, QWidget

from .frosted_overlay import FrostedOverlay
from .theme import current_theme_tokens
from .title_bar import TitleBar
from .window_effects import apply_acrylic, argb_tint, disable_backdrop

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
        self._app_event_filter_installed = False
        self._resize_cursor_shape = None
        self._manual_resize_edges = Qt.Edge(0)
        self._manual_resize_start_global: Optional[QPoint] = None
        self._manual_resize_start_geometry: Optional[QRect] = None
        self._resize_cursor_timer = QTimer(self)
        self._resize_cursor_timer.setInterval(80)
        self._resize_cursor_timer.timeout.connect(self._update_resize_cursor)
        self._resize_drag_poll_timer = QTimer(self)
        self._resize_drag_poll_timer.setInterval(100)
        self._resize_drag_poll_timer.timeout.connect(self._poll_resize_end)
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
        self._cleanup_resize_state()
        super().closeEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._frameless_glass:
            self._apply_titlebar_theme()
            return
        tokens = current_theme_tokens()
        self._title_bar.apply_theme(tokens)
        self._apply_glass_backdrop(tokens)
        if self._frameless_resize:
            self._install_app_event_filter()
            if not self._resize_cursor_timer.isActive():
                self._resize_cursor_timer.start()

    def hideEvent(self, event) -> None:
        self._cleanup_resize_state()
        super().hideEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        overlay = getattr(self, "_frosted_overlay", None)
        if overlay is not None:
            overlay.setGeometry(self._glass_root.rect())
            overlay.raise_()

    def eventFilter(self, watched, event: QEvent) -> bool:
        if (
            self._frameless_glass
            and self._frameless_resize
            and isinstance(watched, QWidget)
            and watched.window() is self
        ):
            if self._manual_resize_edges:
                if event.type() == QEvent.Type.MouseMove:
                    self._apply_manual_resize(event)
                    return True
                if event.type() == QEvent.Type.MouseButtonRelease:
                    self._manual_resize_edges = Qt.Edge(0)
                    self._manual_resize_start_global = None
                    self._manual_resize_start_geometry = None
                    return True
            if (
                event.type() == QEvent.Type.MouseButtonPress
                and self.isVisible()
                and not self.isMaximized()
            ):
                button = getattr(event, "button", None)
                if button is not None and button() == Qt.MouseButton.LeftButton:
                    global_pos = event.globalPosition().toPoint()
                    edges = self._edge_resize_edges(self.mapFromGlobal(global_pos))
                    if edges:
                        self._resize_cursor_timer.stop()
                        self._apply_resize_cursor(None)
                        self._resize_drag_poll_timer.start()
                        self._manual_resize_edges = edges
                        self._manual_resize_start_global = global_pos
                        self._manual_resize_start_geometry = QRect(self.geometry())
                        return True
        return super().eventFilter(watched, event)

    def _manual_resize_geometry(self, delta: QPoint) -> QRect:
        start = self._manual_resize_start_geometry
        if start is None:
            return QRect(self.geometry())
        edges = self._manual_resize_edges
        left = start.left()
        top = start.top()
        right = start.right()
        bottom = start.bottom()
        min_width = max(1, self.minimumWidth())
        min_height = max(1, self.minimumHeight())
        if edges & Qt.Edge.LeftEdge:
            left += delta.x()
        if edges & Qt.Edge.RightEdge:
            right += delta.x()
        if edges & Qt.Edge.TopEdge:
            top += delta.y()
        if edges & Qt.Edge.BottomEdge:
            bottom += delta.y()
        if right - left + 1 < min_width:
            if edges & Qt.Edge.LeftEdge:
                left = right - min_width + 1
            else:
                right = left + min_width - 1
        if bottom - top + 1 < min_height:
            if edges & Qt.Edge.TopEdge:
                top = bottom - min_height + 1
            else:
                bottom = top + min_height - 1
        return QRect(left, top, right - left + 1, bottom - top + 1)

    def _apply_manual_resize(self, event: QEvent) -> None:
        if self._manual_resize_start_global is None:
            return
        try:
            current = event.globalPosition().toPoint()
        except Exception:
            return
        delta = current - self._manual_resize_start_global
        self.setGeometry(self._manual_resize_geometry(delta))

    def _install_app_event_filter(self) -> None:
        app = QApplication.instance()
        if app is not None and not self._app_event_filter_installed:
            app.installEventFilter(self)
            self._app_event_filter_installed = True

    def _remove_app_event_filter(self) -> None:
        app = QApplication.instance()
        if app is not None and self._app_event_filter_installed:
            app.removeEventFilter(self)
            self._app_event_filter_installed = False

    def _cleanup_resize_state(self) -> None:
        self._resize_cursor_timer.stop()
        self._resize_drag_poll_timer.stop()
        self._apply_resize_cursor(None)
        self._remove_app_event_filter()

    def _edge_resize_edges(self, local: QPoint):
        border = 12
        edges = Qt.Edge(0)
        if local.x() <= border:
            edges |= Qt.Edge.LeftEdge
        if local.x() >= self.width() - border:
            edges |= Qt.Edge.RightEdge
        if local.y() <= border:
            edges |= Qt.Edge.TopEdge
        if local.y() >= self.height() - border:
            edges |= Qt.Edge.BottomEdge
        return edges

    def _cursor_for_edges(self, edges):
        if not edges:
            return None
        left = bool(edges & Qt.Edge.LeftEdge)
        right = bool(edges & Qt.Edge.RightEdge)
        top = bool(edges & Qt.Edge.TopEdge)
        bottom = bool(edges & Qt.Edge.BottomEdge)
        if (left and top) or (right and bottom):
            return Qt.CursorShape.SizeFDiagCursor
        if (right and top) or (left and bottom):
            return Qt.CursorShape.SizeBDiagCursor
        if left or right:
            return Qt.CursorShape.SizeHorCursor
        return Qt.CursorShape.SizeVerCursor

    def _apply_resize_cursor(self, shape) -> None:
        if shape == self._resize_cursor_shape:
            return
        if self._resize_cursor_shape is not None:
            QApplication.restoreOverrideCursor()
        if shape is not None:
            QApplication.setOverrideCursor(shape)
        self._resize_cursor_shape = shape

    def _update_resize_cursor(self) -> None:
        active_modal = QApplication.activeModalWidget()
        if (
            not self.isVisible()
            or self.isMaximized()
            or (active_modal is not None and active_modal is not self)
        ):
            self._apply_resize_cursor(None)
            return
        local = self.mapFromGlobal(QCursor.pos())
        if not self.rect().contains(local):
            self._apply_resize_cursor(None)
            return
        self._apply_resize_cursor(self._cursor_for_edges(self._edge_resize_edges(local)))

    def _poll_resize_end(self) -> None:
        if QApplication.mouseButtons() & Qt.MouseButton.LeftButton:
            return
        self._resize_drag_poll_timer.stop()
        self._manual_resize_edges = Qt.Edge(0)
        self._manual_resize_start_global = None
        self._manual_resize_start_geometry = None
        if self.isVisible() and not self._resize_cursor_timer.isActive():
            self._resize_cursor_timer.start()

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
