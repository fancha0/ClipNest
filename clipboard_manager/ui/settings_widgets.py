from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


def make_color_chip_icon(color_hex: str, size: int = 18) -> QIcon:
    """A rounded color swatch used instead of showing raw hex text."""
    color = QColor(color_hex)
    if not color.isValid():
        color = QColor("#ffffff")
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setBrush(color)
    painter.setPen(QPen(color.darker(135), 1))
    painter.drawRoundedRect(1, 1, size - 2, size - 2, 4, 4)
    painter.end()
    return QIcon(pixmap)


COLOR_NAME_ANCHORS: tuple[tuple[str, tuple[int, int, int]], ...] = (
    ("白色", (255, 255, 255)),
    ("浅灰", (240, 242, 245)),
    ("灰色", (150, 156, 165)),
    ("深灰", (70, 76, 85)),
    ("近黑", (24, 28, 34)),
    ("蓝色", (55, 120, 220)),
    ("浅蓝", (200, 226, 250)),
    ("青色", (35, 180, 190)),
    ("绿色", (60, 170, 90)),
    ("黄色", (235, 200, 60)),
    ("橙色", (240, 150, 50)),
    ("红色", (220, 70, 70)),
    ("粉色", (235, 140, 175)),
    ("紫色", (150, 100, 210)),
)


def describe_color(color_hex: str) -> str:
    """Human-friendly color name so the UI does not show raw hex codes."""
    color = QColor(color_hex)
    if not color.isValid():
        return "自定义"
    target = (color.red(), color.green(), color.blue())
    best_name = "自定义"
    best_distance: float | None = None
    for name, anchor in COLOR_NAME_ANCHORS:
        distance = sum((target[i] - anchor[i]) ** 2 for i in range(3))
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best_name = name
    return best_name


class ColorPickButton(QPushButton):
    """Native-looking color control: swatch icon + readable name (hex in tooltip)."""

    def __init__(self, color_hex: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("colorPickButton")
        self.setIconSize(QSize(18, 18))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.set_color(color_hex)

    def set_color(self, color_hex: str) -> None:
        color = QColor(color_hex)
        if not color.isValid():
            color = QColor("#ffffff")
        self._color_hex = color.name()
        self.setIcon(make_color_chip_icon(self._color_hex))
        self.setText(describe_color(self._color_hex))
        self.setToolTip(f"当前颜色 {self._color_hex.upper()}（点击更改）")

    def color_hex(self) -> str:
        return self._color_hex


class SettingRow(QFrame):
    """One settings entry: title + optional description on the left, control on the right."""

    def __init__(
        self,
        title: str,
        control: QWidget,
        description: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("settingRow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 11, 14, 11)
        layout.setSpacing(12)

        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 0, 0, 0)
        text_column.setSpacing(2)

        title_label = QLabel(title, self)
        title_label.setObjectName("settingRowTitle")
        title_label.setWordWrap(True)
        text_column.addWidget(title_label)

        if description:
            desc_label = QLabel(description, self)
            desc_label.setObjectName("settingRowDescription")
            desc_label.setWordWrap(True)
            text_column.addWidget(desc_label)

        layout.addLayout(text_column, 1)
        control.setParent(self)
        layout.addWidget(control, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)


class SettingsSection(QWidget):
    """A titled group of setting rows."""

    def __init__(self, title: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        if title:
            header = QLabel(title, self)
            header.setObjectName("settingSectionTitle")
            self._layout.addWidget(header)

    def add_row(self, row: QWidget) -> None:
        self._layout.addWidget(row)

    def add_widget(self, widget: QWidget) -> None:
        self._layout.addWidget(widget)
