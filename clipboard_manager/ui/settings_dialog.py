from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .theme import AppearanceSettings, default_appearance_settings

PRESET_COLORS = {
    "简约浅灰": ("#f6f8fb", "#ffffff", "#eef7ff"),
    "商务蓝灰": ("#eef2f7", "#ffffff", "#dbeafe"),
    "高对比": ("#ffffff", "#ffffff", "#cde8ff"),
}


@dataclass(frozen=True, slots=True)
class SettingsPayload:
    hotkey: str
    capture_tab_id: Optional[int]
    capture_tab_max: int
    autostart: bool
    appearance: AppearanceSettings
    note_color: str
    note_font_size: int
    pinned_color: str


class SettingsDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        *,
        hotkey: str,
        capture_tab_id: Optional[int],
        capture_tab_max: int,
        autostart: bool,
        appearance: AppearanceSettings,
        note_color: str,
        note_font_size: int,
        pinned_color: str,
        tabs: list[tuple[int, str]],
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setModal(True)
        self.resize(540, 520)

        self._tabs = list(tabs)
        self._appearance = appearance
        self._note_color = note_color
        self._pinned_color = pinned_color
        self._hotkey_initial = hotkey
        self._capture_tab_initial = capture_tab_id
        self._capture_max_initial = capture_tab_max
        self._autostart_initial = autostart
        self._note_font_size_initial = note_font_size
        self._export_requested = False
        self._import_requested = False

        self._build_ui()

    # ---------- UI ----------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        self._tabs_widget = QTabWidget(self)
        self._tabs_widget.addTab(self._build_general_tab(), "通用")
        self._tabs_widget.addTab(self._build_appearance_tab(), "外观")
        self._tabs_widget.addTab(self._build_note_tab(), "备注与置顶")
        self._tabs_widget.addTab(self._build_data_tab(), "数据")
        layout.addWidget(self._tabs_widget)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        save_btn = buttons.button(QDialogButtonBox.StandardButton.Save)
        if save_btn is not None:
            save_btn.setText("保存")
            save_btn.setDefault(True)
        cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_btn is not None:
            cancel_btn.setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _build_general_tab(self) -> QWidget:
        tab = QWidget(self)
        form = QFormLayout(tab)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(12)

        self.hotkey_edit = QKeySequenceEdit(tab)
        self.hotkey_edit.setMaximumSequenceLength(1)
        if self._hotkey_initial:
            self.hotkey_edit.setKeySequence(QKeySequence(self._hotkey_initial))
        form.addRow("全局快捷键：", self.hotkey_edit)

        self.capture_tab_combo = QComboBox(tab)
        for tab_id, tab_name in self._tabs:
            self.capture_tab_combo.addItem(tab_name, tab_id)
        if self._capture_tab_initial is not None:
            index = self.capture_tab_combo.findData(self._capture_tab_initial)
            if index >= 0:
                self.capture_tab_combo.setCurrentIndex(index)
        form.addRow("监听存储标签：", self.capture_tab_combo)

        self.capture_max_spin = QSpinBox(tab)
        self.capture_max_spin.setRange(50, 5000)
        self.capture_max_spin.setSingleStep(50)
        self.capture_max_spin.setValue(int(self._capture_max_initial))
        form.addRow("监听标签条目上限：", self.capture_max_spin)

        self.autostart_chk = QCheckBox("开机自动启动", tab)
        self.autostart_chk.setChecked(bool(self._autostart_initial))
        form.addRow("", self.autostart_chk)

        hint = QLabel("提示：快捷键要求至少一个修饰键 + 一个主键（如 Ctrl+Shift+V）。", tab)
        hint.setWordWrap(True)
        form.addRow("", hint)
        return tab

    def _build_appearance_tab(self) -> QWidget:
        tab = QWidget(self)
        form = QFormLayout(tab)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(12)

        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("一键配色：", tab))
        for preset_name in PRESET_COLORS:
            btn = QPushButton(preset_name, tab)
            btn.clicked.connect(lambda _=False, name=preset_name: self._apply_preset(name))
            preset_row.addWidget(btn)
        preset_row.addStretch(1)
        form.addRow("", preset_row)

        self.window_bg_btn = QPushButton(tab)
        self.window_bg_btn.clicked.connect(lambda: self._pick_appearance_color("window_bg"))
        self._apply_color_preview(self.window_bg_btn, self._appearance.window_bg)
        form.addRow("背景颜色：", self.window_bg_btn)

        self.font_size_spin = QSpinBox(tab)
        self.font_size_spin.setRange(10, 28)
        self.font_size_spin.setValue(int(self._appearance.font_size))
        form.addRow("全局字体大小：", self.font_size_spin)

        self.item_bg_btn = QPushButton(tab)
        self.item_bg_btn.clicked.connect(lambda: self._pick_appearance_color("item_bg"))
        self._apply_color_preview(self.item_bg_btn, self._appearance.item_bg)
        form.addRow("正常条目背景：", self.item_bg_btn)

        self.item_selected_bg_btn = QPushButton(tab)
        self.item_selected_bg_btn.clicked.connect(lambda: self._pick_appearance_color("item_selected_bg"))
        self._apply_color_preview(self.item_selected_bg_btn, self._appearance.item_selected_bg)
        form.addRow("选中条目背景：", self.item_selected_bg_btn)

        self.show_scrollbar_chk = QCheckBox("显示滚动条", tab)
        self.show_scrollbar_chk.setChecked(bool(self._appearance.show_scrollbar))
        form.addRow("", self.show_scrollbar_chk)

        self.antialias_chk = QCheckBox("条目抗锯齿", tab)
        self.antialias_chk.setChecked(bool(self._appearance.item_antialias))
        form.addRow("", self.antialias_chk)

        reset_btn = QPushButton("重置默认", tab)
        reset_btn.clicked.connect(self._reset_appearance_defaults)
        form.addRow("", reset_btn)
        return tab

    def _build_note_tab(self) -> QWidget:
        tab = QWidget(self)
        form = QFormLayout(tab)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(12)

        self.note_color_btn = QPushButton(tab)
        self.note_color_btn.clicked.connect(self._pick_note_color)
        self._apply_color_preview(self.note_color_btn, self._note_color)
        form.addRow("备注文字颜色：", self.note_color_btn)

        self.note_font_spin = QSpinBox(tab)
        self.note_font_spin.setRange(10, 28)
        self.note_font_spin.setValue(int(self._note_font_size_initial))
        form.addRow("备注文字大小：", self.note_font_spin)

        self.pinned_color_btn = QPushButton(tab)
        self.pinned_color_btn.clicked.connect(self._pick_pinned_color)
        self._apply_color_preview(self.pinned_color_btn, self._pinned_color)
        form.addRow("置顶颜色：", self.pinned_color_btn)
        return tab

    def _build_data_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.setSpacing(10)

        export_btn = QPushButton("导出标签页与条目...", tab)
        export_btn.clicked.connect(self._request_export)
        layout.addWidget(export_btn)

        import_btn = QPushButton("导入标签页与条目...", tab)
        import_btn.clicked.connect(self._request_import)
        layout.addWidget(import_btn)

        hint = QLabel(
            "导入/导出会打开独立的操作窗口，本次设置窗口将先关闭。",
            tab,
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)
        return tab


    # ---------- behavior ----------

    def _request_export(self) -> None:
        self._export_requested = True
        self.accept()

    def _request_import(self) -> None:
        self._import_requested = True
        self.accept()

    def _pick_appearance_color(self, key: str) -> None:
        current = getattr(self._appearance, key)
        color = QColorDialog.getColor(QColor(current), self, "选择颜色")
        if not color.isValid():
            return
        from dataclasses import replace

        self._appearance = replace(self._appearance, **{key: color.name()})
        button = {
            "window_bg": self.window_bg_btn,
            "item_bg": self.item_bg_btn,
            "item_selected_bg": self.item_selected_bg_btn,
        }[key]
        self._apply_color_preview(button, color.name())

    def _pick_note_color(self) -> None:
        color = QColorDialog.getColor(QColor(self._note_color), self, "选择备注文字颜色")
        if not color.isValid():
            return
        self._note_color = color.name()
        self._apply_color_preview(self.note_color_btn, self._note_color)

    def _pick_pinned_color(self) -> None:
        color = QColorDialog.getColor(QColor(self._pinned_color), self, "选择置顶颜色")
        if not color.isValid():
            return
        self._pinned_color = color.name()
        self._apply_color_preview(self.pinned_color_btn, self._pinned_color)

    def _apply_preset(self, preset_name: str) -> None:
        from dataclasses import replace

        colors = PRESET_COLORS.get(preset_name)
        if colors is None:
            return
        window_bg, item_bg, item_selected_bg = colors
        self._appearance = replace(
            self._appearance,
            window_bg=window_bg,
            item_bg=item_bg,
            item_selected_bg=item_selected_bg,
        )
        self._apply_color_preview(self.window_bg_btn, window_bg)
        self._apply_color_preview(self.item_bg_btn, item_bg)
        self._apply_color_preview(self.item_selected_bg_btn, item_selected_bg)

    def _reset_appearance_defaults(self) -> None:
        self._appearance = default_appearance_settings()
        self.font_size_spin.setValue(int(self._appearance.font_size))
        self.show_scrollbar_chk.setChecked(bool(self._appearance.show_scrollbar))
        self.antialias_chk.setChecked(bool(self._appearance.item_antialias))
        self._apply_color_preview(self.window_bg_btn, self._appearance.window_bg)
        self._apply_color_preview(self.item_bg_btn, self._appearance.item_bg)
        self._apply_color_preview(self.item_selected_bg_btn, self._appearance.item_selected_bg)

    @staticmethod
    def _apply_color_preview(button: QPushButton, color_hex: str) -> None:
        color = QColor(color_hex)
        if not color.isValid():
            color = QColor("#ffffff")
        luminance = (0.299 * color.redF()) + (0.587 * color.greenF()) + (0.114 * color.blueF())
        text_color = "#111827" if luminance >= 0.62 else "#F9FAFB"
        button.setText(color_hex.upper())
        button.setStyleSheet(
            "text-align: left; padding-left: 10px; padding-right: 10px; border-radius: 6px;"
            f"background: {color.name()};"
            f"border: 1px solid {color.darker(120).name()};"
            f"color: {text_color};"
        )

    # ---------- results ----------

    def export_requested(self) -> bool:
        return bool(getattr(self, "_export_requested", False))

    def import_requested(self) -> bool:
        return bool(getattr(self, "_import_requested", False))

    def result_payload(self) -> SettingsPayload:
        hotkey = self.hotkey_edit.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
        capture_tab_data = self.capture_tab_combo.currentData()
        return SettingsPayload(
            hotkey=hotkey,
            capture_tab_id=int(capture_tab_data) if capture_tab_data is not None else None,
            capture_tab_max=int(self.capture_max_spin.value()),
            autostart=bool(self.autostart_chk.isChecked()),
            appearance=self._appearance,
            note_color=self._note_color,
            note_font_size=int(self.note_font_spin.value()),
            pinned_color=self._pinned_color,
        )
