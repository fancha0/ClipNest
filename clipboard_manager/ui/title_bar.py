from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QMouseEvent, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QWidget

from .icons import line_icon
from .theme import ThemeTokens


class TitleBar(QWidget):
    """Frameless window header: icon + title, drag area and window buttons."""

    collapse_requested = Signal()
    quit_requested = Signal()

    _HEIGHT = 40

    def __init__(
        self,
        title: str,
        icon: Optional[QPixmap] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("titleBar")
        self.setFixedHeight(self._HEIGHT)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 6, 0)
        layout.setSpacing(8)

        self._icon_label = QLabel(self)
        self._icon_label.setFixedSize(18, 18)
        if icon is not None and not icon.isNull():
            self._icon_label.setPixmap(icon.scaled(18, 18, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        layout.addWidget(self._icon_label)

        self._title_label = QLabel(title, self)
        self._title_label.setObjectName("titleBarTitle")
        layout.addWidget(self._title_label)
        layout.addStretch(1)

        self._collapse_btn = self._make_button("collapse", "收起")
        self._collapse_btn.clicked.connect(self.collapse_requested.emit)
        layout.addWidget(self._collapse_btn)

        self._close_btn = self._make_button("close", "关闭")
        self._close_btn.setObjectName("titleBarCloseButton")
        self._close_btn.clicked.connect(self.quit_requested.emit)
        layout.addWidget(self._close_btn)

    def _make_button(self, icon_kind: str, tooltip: str) -> QToolButton:
        button = QToolButton(self)
        button.setObjectName("titleBarButton")
        button.setToolTip(tooltip)
        button.setFixedSize(QSize(30, 26))
        button.setIcon(line_icon(icon_kind, "#4a5866", 15))
        button.setIconSize(QSize(15, 15))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setAutoRaise(True)
        return button

    def apply_theme(self, tokens: ThemeTokens) -> None:
        dark = bool(getattr(tokens, "is_dark", False))
        normal = "#c8d3e2" if dark else "#4a5866"
        self._collapse_btn.setIcon(line_icon("collapse", normal, 15))
        self._close_btn.setIcon(line_icon("close", normal, 15))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            window = self.window()
            handle = window.windowHandle()
            if handle is not None:
                begin = getattr(window, "begin_system_drag", None)
                if begin is not None:
                    begin()
                handle.startSystemMove()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            window = self.window()
            if window.isMaximized():
                window.showNormal()
            else:
                window.showMaximized()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)
