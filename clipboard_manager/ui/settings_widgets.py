from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .theme import current_theme_tokens


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


class ToggleSwitch(QWidget):
    """Windows 11 style toggle: pill track + sliding knob, drawn with theme colors."""

    toggled = Signal(bool)

    _TRACK_W = 42
    _TRACK_H = 22
    _KNOB = 16
    _MARGIN = 3
    _ACCENT = ("#2f7cd6", "#2f7fb8")
    _TRACK_OFF = ("#cfd8e3", "#4a5768")
    _TRACK_OFF_HOVER = ("#c2cdd9", "#566477")

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._checked = False
        self._position = 0.0
        self._hovered = False
        self.setFixedSize(self._TRACK_W + 2, self._TRACK_H + 2)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(140)
        self._anim.valueChanged.connect(self._on_position)
        self._start_anim()

    def _on_position(self, value) -> None:
        self._position = float(value)
        self.update()

    def _start_anim(self) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._position)
        self._anim.setEndValue(1.0 if self._checked else 0.0)
        self._anim.start()

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool) -> None:
        checked = bool(checked)
        if checked == self._checked:
            return
        self._checked = checked
        self._start_anim()
        self.toggled.emit(checked)

    def _toggle(self) -> None:
        self.setChecked(not self._checked)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._toggle()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._toggle()
            return
        super().keyPressEvent(event)

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:
        tokens = current_theme_tokens()
        dark = bool(getattr(tokens, "is_dark", False))
        index = 1 if dark else 0
        accent = QColor(self._ACCENT[index])
        if self._checked:
            track = accent.lighter(108) if self._hovered else accent
        else:
            off = QColor(self._TRACK_OFF_HOVER[index] if self._hovered else self._TRACK_OFF[index])
            track = off

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        track_rect = QRectF(1, 1, self._TRACK_W, self._TRACK_H)
        painter.setBrush(track)
        painter.drawRoundedRect(track_rect, self._TRACK_H / 2.0, self._TRACK_H / 2.0)

        span = self._TRACK_W - self._KNOB - self._MARGIN * 2
        knob_x = self._MARGIN + self._position * span
        knob_y = (self._TRACK_H - self._KNOB) / 2.0
        knob_rect = QRectF(1 + knob_x, 1 + knob_y, self._KNOB, self._KNOB)
        painter.setBrush(QColor("#ffffff"))
        painter.setPen(QPen(QColor(0, 0, 0, 26 if dark else 38), 1))
        painter.drawEllipse(knob_rect)
        painter.end()


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
    """A titled group of setting rows: gray title above one rounded card.

    Rows share a single card and are separated by hairlines (Windows 11 style).
    """

    def __init__(self, title: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        if title:
            header = QLabel(title, self)
            header.setObjectName("settingSectionTitle")
            self._layout.addWidget(header)

        self._card = QFrame(self)
        self._card.setObjectName("settingsSectionCard")
        self._card_layout = QVBoxLayout(self._card)
        self._card_layout.setContentsMargins(0, 0, 0, 0)
        self._card_layout.setSpacing(0)
        self._layout.addWidget(self._card)
        self._row_count = 0

    def add_row(self, row: QWidget) -> None:
        if self._row_count > 0:
            separator = QFrame(self._card)
            separator.setObjectName("settingRowSeparator")
            separator.setFixedHeight(1)
            self._card_layout.addWidget(separator)
        self._row_count += 1
        row.setParent(self._card)
        self._card_layout.addWidget(row)

    def add_widget(self, widget: QWidget) -> None:
        self._layout.addWidget(widget)
