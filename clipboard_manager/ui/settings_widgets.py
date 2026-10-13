from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .theme import current_theme_tokens, theme_style_colors


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
        accent = QColor(getattr(tokens, "accent_bg", None) or self._ACCENT[index])
        if not accent.isValid():
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
        self._search_text = f"{title} {description}".lower()

    def search_text(self) -> str:
        return self._search_text


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
        self._rows: list[SettingRow] = []
        self._separators: list[QFrame] = []

    def add_row(self, row: QWidget) -> None:
        if self._row_count > 0:
            separator = QFrame(self._card)
            separator.setObjectName("settingRowSeparator")
            separator.setFixedHeight(1)
            self._card_layout.addWidget(separator)
            self._separators.append(separator)
        self._row_count += 1
        row.setParent(self._card)
        self._card_layout.addWidget(row)
        if isinstance(row, SettingRow):
            self._rows.append(row)

    def add_widget(self, widget: QWidget) -> None:
        self._layout.addWidget(widget)

    def apply_filter(self, query: str) -> bool:
        """Show only rows matching query; return True when anything is visible."""
        query = (query or "").strip().lower()
        if not query:
            for row in self._rows:
                row.setVisible(True)
            for separator in self._separators:
                separator.setVisible(True)
            self.setVisible(True)
            return True
        any_visible = False
        visible_flags: list[bool] = []
        for row in self._rows:
            visible = query in row.search_text()
            row.setVisible(visible)
            visible_flags.append(visible)
            any_visible = any_visible or visible
        for separator in self._separators:
            separator.setVisible(False)
        for idx in range(1, len(visible_flags)):
            if visible_flags[idx] and visible_flags[idx - 1]:
                self._separators[idx - 1].setVisible(True)
        self.setVisible(any_visible)
        return any_visible


class SegmentedControl(QWidget):
    """Pill-shaped segmented selector: light / dark / follow-system style choices."""

    valueChanged = Signal(str)

    _HEIGHT = 32

    def __init__(
        self,
        options: list[tuple[str, str]],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._options = list(options)
        self._current = self._options[0][0] if self._options else ""
        self.setFixedHeight(self._HEIGHT)
        self.setMinimumWidth(90 * max(1, len(self._options)))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self._hover_index = -1

    def current_key(self) -> str:
        return self._current

    def set_current(self, key: str) -> None:
        if key == self._current:
            return
        for option_key, _label in self._options:
            if option_key == key:
                self._current = key
                self.update()
                return

    def _index_at(self, x: float) -> int:
        if not self._options:
            return -1
        width = self.width() / len(self._options)
        index = int(x // width)
        return max(0, min(len(self._options) - 1, index))

    def mousePressEvent(self, event) -> None:
        index = self._index_at(event.position().x())
        if index < 0:
            return
        key = self._options[index][0]
        if key != self._current:
            self._current = key
            self.update()
            self.valueChanged.emit(key)

    def mouseMoveEvent(self, event) -> None:
        index = self._index_at(event.position().x())
        if index != self._hover_index:
            self._hover_index = index
            self.update()

    def leaveEvent(self, event) -> None:
        self._hover_index = -1
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:
        tokens = current_theme_tokens()
        dark = bool(getattr(tokens, "is_dark", False))
        accent = QColor(tokens.accent_bg)
        text_color = QColor(tokens.text_primary)
        muted = QColor(tokens.text_secondary)
        track = QColor(255, 255, 255, 40) if dark else QColor(15, 23, 42, 16)
        border = QColor(255, 255, 255, 60) if dark else QColor(15, 23, 42, 30)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        painter.setPen(QPen(border, 1))
        painter.setBrush(track)
        radius = rect.height() / 2.0
        painter.drawRoundedRect(rect, radius, radius)

        if not self._options:
            painter.end()
            return

        seg_w = rect.width() / len(self._options)
        for idx, (_key, label) in enumerate(self._options):
            seg = QRectF(rect.left() + idx * seg_w + 2, rect.top() + 2, seg_w - 4, rect.height() - 4)
            selected = _key == self._current
            if selected:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(accent)
                painter.drawRoundedRect(seg, seg.height() / 2.0, seg.height() / 2.0)
            font = QFont(self.font())
            font.setBold(selected)
            painter.setFont(font)
            if selected:
                painter.setPen(QColor("#ffffff"))
            elif idx == self._hover_index:
                painter.setPen(text_color)
            else:
                painter.setPen(muted)
            painter.drawText(seg, Qt.AlignmentFlag.AlignCenter, label)
        painter.end()


class AppearancePreview(QWidget):
    """Small live preview of the window: nav strip, normal item and selected item."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("appearancePreview")
        self.setMinimumHeight(132)
        self._window = "#e9f1ea"
        self._item = "#ffffff"
        self._selected = "#a9cdb4"
        self._accent = "#1677c8"

    def set_colors(self, window_bg: str, item_bg: str, selected_bg: str, accent: str = "") -> None:
        self._window = window_bg
        self._item = item_bg
        self._selected = selected_bg
        if accent:
            self._accent = accent
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        radius = 12.0
        painter.setPen(QPen(QColor(0, 0, 0, 30), 1))
        painter.setBrush(QColor(self._window))
        painter.drawRoundedRect(rect, radius, radius)

        nav_w = 56.0
        nav = QRectF(rect.left() + 8, rect.top() + 8, nav_w, rect.height() - 16)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 18))
        painter.drawRoundedRect(nav, 8, 8)
        painter.setBrush(QColor(self._accent))
        for i in range(3):
            chip = QRectF(nav.left() + 8, nav.top() + 10 + i * 18, nav.width() - 16, 10)
            painter.setBrush(QColor(self._accent) if i == 0 else QColor(255, 255, 255, 90))
            painter.drawRoundedRect(chip, 5, 5)

        body_left = nav.right() + 10
        body_w = rect.right() - 8 - body_left
        row_h = (rect.height() - 16 - 8) / 2.0
        for i in range(2):
            row = QRectF(body_left, rect.top() + 8 + i * (row_h + 8), body_w, row_h)
            selected = i == 1
            painter.setBrush(QColor(self._selected) if selected else QColor(self._item))
            painter.setPen(QPen(QColor(self._accent), 1.4) if selected else QPen(QColor(0, 0, 0, 24), 1))
            painter.drawRoundedRect(row, 8, 8)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 60) if selected else QColor(0, 0, 0, 40))
            painter.drawRoundedRect(
                QRectF(row.left() + 10, row.top() + 8, min(70.0, row.width() * 0.4), 7),
                3,
                3,
            )
        painter.end()


class NotePreview(QWidget):
    """Small preview of a pinned item with a note line."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("notePreview")
        self.setMinimumHeight(96)
        self._note_color = "#1f2937"
        self._note_size = 13
        self._pinned_color = "#1fb8cb"

    def set_style(self, note_color: str, note_size: int, pinned_color: str) -> None:
        self._note_color = note_color or self._note_color
        self._note_size = max(10, int(note_size))
        self._pinned_color = pinned_color or self._pinned_color
        self.update()

    def paintEvent(self, _event) -> None:
        tokens = current_theme_tokens()
        item_bg = tokens.item_bg
        accent = QColor(self._pinned_color)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        painter.setPen(QPen(QColor(0, 0, 0, 30), 1))
        painter.setBrush(QColor(item_bg))
        painter.drawRoundedRect(rect, 9, 9)

        bar = QRectF(rect.left(), rect.top() + 6, 4, rect.height() - 12)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent)
        painter.drawRoundedRect(bar, 2, 2)

        text_x = rect.left() + 16
        painter.setPen(QColor(tokens.text_primary))
        body_font = QFont(self.font())
        body_font.setPointSize(max(10, tokens.base_font_size))
        painter.setFont(body_font)
        painter.drawText(
            QRectF(text_x, rect.top() + 12, rect.width() - 28, 20),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "这是一条示例条目内容",
        )

        pin_badge = QRectF(rect.right() - 46, rect.top() + 10, 38, 16)
        painter.setBrush(accent)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(pin_badge, 8, 8)
        painter.setPen(QColor("#ffffff"))
        badge_font = QFont(self.font())
        badge_font.setPointSize(max(8, tokens.base_font_size - 3))
        painter.setFont(badge_font)
        painter.drawText(pin_badge, Qt.AlignmentFlag.AlignCenter, "置顶")

        note_font = QFont(self.font())
        note_font.setPointSize(self._note_size)
        painter.setFont(note_font)
        painter.setPen(QColor(self._note_color))
        painter.drawText(
            QRectF(text_x, rect.top() + 40, rect.width() - 28, rect.height() - 50),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
            "备注：演示备注文字效果",
        )
        painter.end()


class ThemeStyleSelector(QWidget):
    """Grid of clickable theme style cards, each with a mini color preview."""

    styleSelected = Signal(str)

    def __init__(
        self,
        styles: list[tuple[str, str]],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._current = styles[0][0] if styles else ""
        self._cards: dict[str, _StyleCard] = {}
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(8)
        columns = 3
        for idx, (key, label) in enumerate(styles):
            card = _StyleCard(key, label, self)
            card.clicked.connect(self._on_card_clicked)
            card.set_selected(key == self._current)
            self._cards[key] = card
            grid.addWidget(card, idx // columns, idx % columns)

    def current_style(self) -> str:
        return self._current

    def set_current(self, style: str) -> None:
        if style == self._current or style not in self._cards:
            return
        self._current = style
        for key, card in self._cards.items():
            card.set_selected(key == style)

    def _on_card_clicked(self, key: str) -> None:
        if key == self._current:
            return
        self._current = key
        for card_key, card in self._cards.items():
            card.set_selected(card_key == key)
        self.styleSelected.emit(key)


class _StyleCard(QFrame):
    clicked = Signal(str)

    def __init__(self, key: str, label: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._key = key
        self._label = label
        self._selected = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(66)
        window_bg, item_bg, selected_bg = theme_style_colors(key)
        self._colors = (window_bg, item_bg, selected_bg)

    def set_selected(self, selected: bool) -> None:
        self._selected = bool(selected)
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._key)
            return
        super().mousePressEvent(event)

    def paintEvent(self, _event) -> None:
        tokens = current_theme_tokens()
        accent = QColor(tokens.accent_bg)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        if self._selected:
            painter.setPen(QPen(accent, 2))
            painter.setBrush(QColor(self._colors[0]))
        else:
            painter.setPen(QPen(QColor(0, 0, 0, 34), 1))
            painter.setBrush(QColor(self._colors[0]))
        painter.drawRoundedRect(rect, 9, 9)

        swatch_y = rect.top() + 9
        swatch_h = 20.0
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self._colors[1]))
        painter.drawRoundedRect(
            QRectF(rect.left() + 9, swatch_y, rect.width() - 18, swatch_h), 5, 5
        )
        painter.setBrush(QColor(self._colors[2]))
        painter.drawRoundedRect(
            QRectF(rect.left() + 9, swatch_y + swatch_h + 4, (rect.width() - 18) * 0.55, 10),
            4,
            4,
        )

        painter.setPen(QColor(tokens.text_primary))
        font = QFont(self.font())
        font.setBold(self._selected)
        painter.setFont(font)
        painter.drawText(
            QRectF(rect.left() + 9, rect.bottom() - 20, rect.width() - 18, 16),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self._label,
        )
        painter.end()


class ColorPickerDialog(QDialog):
    """Theme-aware color picker: preset swatches plus an advanced native picker."""

    _PRESETS: tuple[str, ...] = (
        "#ffffff", "#f6f9ff", "#eef6f1", "#e9f1ea", "#e8edf5", "#edf7ff",
        "#f5e6c8", "#fdf2f2", "#f2f0fb", "#e2e8f0", "#cbd5e1", "#94a3b8",
        "#64748b", "#475569", "#334155", "#1d2430", "#1677c8", "#28b7d6",
        "#4f9d69", "#d97706", "#8b5cf6", "#d0534b", "#db2777", "#0f766e",
    )

    def __init__(self, parent: Optional[QWidget], title: str, current_hex: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self._color = QColor(current_hex)
        if not self._color.isValid():
            self._color = QColor("#ffffff")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(12)

        self._preview = QLabel(self)
        self._preview.setObjectName("colorPreviewLabel")
        self._preview.setFixedHeight(34)
        layout.addWidget(self._preview)

        grid = QGridLayout()
        grid.setSpacing(6)
        columns = 8
        for idx, color_hex in enumerate(self._PRESETS):
            btn = QPushButton(self)
            btn.setFixedSize(QSize(30, 30))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(color_hex.upper())
            btn.setStyleSheet(
                f"QPushButton {{ background: {color_hex}; border: 1px solid rgba(0,0,0,40);"
                f" border-radius: 7px; }}"
            )
            btn.clicked.connect(lambda _=False, c=color_hex: self._set_color(c))
            grid.addWidget(btn, idx // columns, idx % columns)
        layout.addLayout(grid)

        advanced = QPushButton("更多颜色…", self)
        advanced.clicked.connect(self._open_native)
        layout.addWidget(advanced)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setText("确定")
            ok_btn.setObjectName("primaryButton")
        cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_btn is not None:
            cancel_btn.setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._sync_preview()

    def _set_color(self, color_hex: str) -> None:
        color = QColor(color_hex)
        if color.isValid():
            self._color = color
            self._sync_preview()

    def _open_native(self) -> None:
        chosen = QColorDialog.getColor(self._color, self, "选择颜色")
        if chosen.isValid():
            self._color = chosen
            self._sync_preview()

    def _sync_preview(self) -> None:
        self._preview.setStyleSheet(
            f"QLabel#colorPreviewLabel {{ background: {self._color.name()};"
            f" border: 1px solid rgba(0,0,0,50); border-radius: 8px; }}"
        )
        self._preview.setToolTip(self._color.name().upper())

    def selected_color(self) -> str:
        return self._color.name()


def pick_color(parent: Optional[QWidget], title: str, current_hex: str) -> Optional[str]:
    dialog = ColorPickerDialog(parent, title, current_hex)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return dialog.selected_color()
    return None

