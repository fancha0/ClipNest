from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialogButtonBox,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .theme import AppearanceSettings, default_appearance_settings, normalize_theme_mode
from .dialog_base import ResizableDialog
from .settings_widgets import ColorPickButton, SettingRow, SettingsSection

PRESET_COLORS = {
    "简约浅灰": ("#f6f8fb", "#ffffff", "#eef7ff"),
    "商务蓝灰": ("#eef2f7", "#ffffff", "#dbeafe"),
    "高对比": ("#ffffff", "#ffffff", "#cde8ff"),
}

THEME_MODE_LABELS = {
    "follow_system": "跟随系统",
    "light": "浅色",
    "dark": "深色",
}

NAV_PAGES = (
    ("通用", "\u2699"),
    ("外观", "\U0001F3A8"),
    ("备注与置顶", "\U0001F4CC"),
    ("数据", "\U0001F4BE"),
)


@dataclass(frozen=True, slots=True)
class SettingsPayload:
    hotkey: str
    capture_tab_id: Optional[int]
    capture_tab_max: int
    autostart: bool
    appearance: AppearanceSettings
    theme_mode: str
    note_color: str
    note_font_size: int
    pinned_color: str


class SettingsDialog(ResizableDialog):
    _size_key = "settings"
    _default_size = (720, 560)
    _min_size = (620, 460)

    def __init__(
        self,
        parent: QWidget,
        *,
        hotkey: str,
        capture_tab_id: Optional[int],
        capture_tab_max: int,
        autostart: bool,
        appearance: AppearanceSettings,
        theme_mode: str,
        note_color: str,
        note_font_size: int,
        pinned_color: str,
        tabs: list[tuple[int, str]],
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置")

        self._tabs = list(tabs)
        self._appearance = appearance
        self._note_color = note_color
        self._pinned_color = pinned_color
        self._hotkey_initial = hotkey
        self._capture_tab_initial = capture_tab_id
        self._capture_max_initial = capture_tab_max
        self._autostart_initial = autostart
        self._note_font_size_initial = note_font_size
        self._theme_mode_initial = normalize_theme_mode(theme_mode)
        self._export_requested = False
        self._import_requested = False

        self._build_ui()

    # ---------- UI scaffolding ----------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.nav_list = QListWidget(self)
        self.nav_list.setObjectName("settingsNav")
        self.nav_list.setFixedWidth(168)
        self.nav_list.setSpacing(2)
        self.nav_list.setIconSize(QSize(16, 16))
        self.nav_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for label, glyph in NAV_PAGES:
            item = QListWidgetItem(f"{glyph}   {label}")
            item.setSizeHint(QSize(0, 38))
            self.nav_list.addItem(item)
        body.addWidget(self.nav_list)

        self.pages = QStackedWidget(self)
        self.pages.setObjectName("settingsPages")
        self.pages.addWidget(self._wrap_scroll(self._build_general_page()))
        self.pages.addWidget(self._wrap_scroll(self._build_appearance_page()))
        self.pages.addWidget(self._wrap_scroll(self._build_note_page()))
        self.pages.addWidget(self._wrap_scroll(self._build_data_page()))
        body.addWidget(self.pages, 1)
        root.addLayout(body, 1)

        footer = QWidget(self)
        footer.setObjectName("settingsFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(18, 12, 18, 12)
        footer_layout.setSpacing(8)
        footer_layout.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel,
            parent=footer,
        )
        save_btn = buttons.button(QDialogButtonBox.StandardButton.Save)
        if save_btn is not None:
            save_btn.setText("保存")
            save_btn.setObjectName("primaryButton")
            save_btn.setDefault(True)
        cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_btn is not None:
            cancel_btn.setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        footer_layout.addWidget(buttons)
        root.addWidget(footer)

        self.nav_list.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav_list.setCurrentRow(0)

    @staticmethod
    def _wrap_scroll(page: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName("settingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(page)
        return scroll

    @staticmethod
    def _new_page(title: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)
        header = QLabel(title, page)
        header.setObjectName("settingsPageTitle")
        layout.addWidget(header)
        return page, layout

    # ---------- pages ----------

    def _build_general_page(self) -> QWidget:
        page, layout = self._new_page("通用")

        self.hotkey_edit = QKeySequenceEdit(page)
        self.hotkey_edit.setMaximumSequenceLength(1)
        self.hotkey_edit.setFixedWidth(190)
        if self._hotkey_initial:
            self.hotkey_edit.setKeySequence(QKeySequence(self._hotkey_initial))

        self.capture_tab_combo = QComboBox(page)
        self.capture_tab_combo.setFixedWidth(190)
        for tab_id, tab_name in self._tabs:
            self.capture_tab_combo.addItem(tab_name, tab_id)
        if self._capture_tab_initial is not None:
            index = self.capture_tab_combo.findData(self._capture_tab_initial)
            if index >= 0:
                self.capture_tab_combo.setCurrentIndex(index)

        self.capture_max_spin = QSpinBox(page)
        self.capture_max_spin.setRange(50, 5000)
        self.capture_max_spin.setSingleStep(50)
        self.capture_max_spin.setFixedWidth(120)
        self.capture_max_spin.setValue(int(self._capture_max_initial))

        self.autostart_chk = QCheckBox(page)
        self.autostart_chk.setChecked(bool(self._autostart_initial))

        section = SettingsSection("快捷键与启动", page)
        section.add_row(
            SettingRow(
                "全局快捷键",
                self.hotkey_edit,
                "至少一个修饰键加一个主键，例如 Ctrl+Shift+V。",
            )
        )
        section.add_row(
            SettingRow(
                "开机自动启动",
                self.autostart_chk,
                "登录 Windows 后自动在后台运行。",
            )
        )
        layout.addWidget(section)

        capture_section = SettingsSection("剪贴板监听", page)
        capture_section.add_row(
            SettingRow(
                "监听存储标签",
                self.capture_tab_combo,
                "自动记录的剪贴板内容会保存到这个标签页。",
            )
        )
        capture_section.add_row(
            SettingRow(
                "监听标签条目上限",
                self.capture_max_spin,
                "超出后自动删除最旧条目，置顶条目不受影响。",
            )
        )
        layout.addWidget(capture_section)
        layout.addStretch(1)
        return page

    def _build_appearance_page(self) -> QWidget:
        page, layout = self._new_page("外观")

        self.theme_mode_combo = QComboBox(page)
        self.theme_mode_combo.setFixedWidth(150)
        for mode_key, mode_label in THEME_MODE_LABELS.items():
            self.theme_mode_combo.addItem(mode_label, mode_key)
        mode_index = self.theme_mode_combo.findData(self._theme_mode_initial)
        if mode_index >= 0:
            self.theme_mode_combo.setCurrentIndex(mode_index)

        theme_section = SettingsSection("主题", page)
        theme_section.add_row(
            SettingRow(
                "主题模式",
                self.theme_mode_combo,
                "跟随系统时会随 Windows 深浅色自动切换。",
            )
        )
        layout.addWidget(theme_section)

        self.font_size_spin = QSpinBox(page)
        self.font_size_spin.setRange(10, 28)
        self.font_size_spin.setFixedWidth(120)
        self.font_size_spin.setValue(int(self._appearance.font_size))

        self.window_bg_btn = ColorPickButton(self._appearance.window_bg, page)
        self.window_bg_btn.clicked.connect(lambda: self._pick_appearance_color("window_bg"))
        self.item_bg_btn = ColorPickButton(self._appearance.item_bg, page)
        self.item_bg_btn.clicked.connect(lambda: self._pick_appearance_color("item_bg"))
        self.item_selected_bg_btn = ColorPickButton(self._appearance.item_selected_bg, page)
        self.item_selected_bg_btn.clicked.connect(
            lambda: self._pick_appearance_color("item_selected_bg")
        )

        preset_widget = QWidget(page)
        preset_layout = QHBoxLayout(preset_widget)
        preset_layout.setContentsMargins(0, 0, 0, 0)
        preset_layout.setSpacing(6)
        for preset_name in PRESET_COLORS:
            btn = QPushButton(preset_name, preset_widget)
            btn.clicked.connect(lambda _=False, name=preset_name: self._apply_preset(name))
            preset_layout.addWidget(btn)

        color_section = SettingsSection("配色（浅色模式生效）", page)
        color_section.add_row(SettingRow("预设配色", preset_widget, "一键套用推荐的配色组合。"))
        color_section.add_row(SettingRow("窗口背景", self.window_bg_btn))
        color_section.add_row(SettingRow("条目背景", self.item_bg_btn))
        color_section.add_row(SettingRow("选中条目背景", self.item_selected_bg_btn))
        layout.addWidget(color_section)

        self.show_scrollbar_chk = QCheckBox(page)
        self.show_scrollbar_chk.setChecked(bool(self._appearance.show_scrollbar))
        self.antialias_chk = QCheckBox(page)
        self.antialias_chk.setChecked(bool(self._appearance.item_antialias))

        reset_btn = QPushButton("重置外观为默认", page)
        reset_btn.clicked.connect(self._reset_appearance_defaults)

        display_section = SettingsSection("显示", page)
        display_section.add_row(SettingRow("全局字体大小", self.font_size_spin))
        display_section.add_row(SettingRow("显示滚动条", self.show_scrollbar_chk))
        display_section.add_row(
            SettingRow("条目抗锯齿", self.antialias_chk, "关闭后绘制更快，边缘略硬。")
        )
        display_section.add_row(SettingRow("恢复默认外观", reset_btn))
        layout.addWidget(display_section)
        layout.addStretch(1)
        return page

    def _build_note_page(self) -> QWidget:
        page, layout = self._new_page("备注与置顶")

        self.note_color_btn = ColorPickButton(self._note_color, page)
        self.note_color_btn.clicked.connect(self._pick_note_color)

        self.note_font_spin = QSpinBox(page)
        self.note_font_spin.setRange(10, 28)
        self.note_font_spin.setFixedWidth(120)
        self.note_font_spin.setValue(int(self._note_font_size_initial))

        self.pinned_color_btn = ColorPickButton(self._pinned_color, page)
        self.pinned_color_btn.clicked.connect(self._pick_pinned_color)

        note_section = SettingsSection("备注样式", page)
        note_section.add_row(
            SettingRow("备注文字颜色", self.note_color_btn, "深色模式下会自动提亮以保证可读。")
        )
        note_section.add_row(SettingRow("备注文字大小", self.note_font_spin))
        layout.addWidget(note_section)

        pinned_section = SettingsSection("置顶标记", page)
        pinned_section.add_row(
            SettingRow("置顶强调色", self.pinned_color_btn, "用于置顶条目的左侧色条与描边。")
        )
        layout.addWidget(pinned_section)
        layout.addStretch(1)
        return page

    def _build_data_page(self) -> QWidget:
        page, layout = self._new_page("数据")

        export_btn = QPushButton("导出…", page)
        export_btn.clicked.connect(self._request_export)
        import_btn = QPushButton("导入…", page)
        import_btn.clicked.connect(self._request_import)

        section = SettingsSection("备份与迁移", page)
        section.add_row(
            SettingRow(
                "导出标签页与条目",
                export_btn,
                "打包为 .fluxpkg 文件，可在其他电脑导入。",
            )
        )
        section.add_row(
            SettingRow(
                "导入标签页与条目",
                import_btn,
                "同名标签会合并，重复条目自动跳过。",
            )
        )
        layout.addWidget(section)

        hint = QLabel("选择导入或导出后，设置窗口会先关闭再打开文件选择。", page)
        hint.setObjectName("settingRowDescription")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)
        return page

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
        self._appearance = replace(self._appearance, **{key: color.name()})
        button = {
            "window_bg": self.window_bg_btn,
            "item_bg": self.item_bg_btn,
            "item_selected_bg": self.item_selected_bg_btn,
        }[key]
        button.set_color(color.name())

    def _pick_note_color(self) -> None:
        color = QColorDialog.getColor(QColor(self._note_color), self, "选择备注文字颜色")
        if not color.isValid():
            return
        self._note_color = color.name()
        self.note_color_btn.set_color(self._note_color)

    def _pick_pinned_color(self) -> None:
        color = QColorDialog.getColor(QColor(self._pinned_color), self, "选择置顶颜色")
        if not color.isValid():
            return
        self._pinned_color = color.name()
        self.pinned_color_btn.set_color(self._pinned_color)

    def _apply_preset(self, preset_name: str) -> None:
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
        self.window_bg_btn.set_color(window_bg)
        self.item_bg_btn.set_color(item_bg)
        self.item_selected_bg_btn.set_color(item_selected_bg)

    def _reset_appearance_defaults(self) -> None:
        self._appearance = default_appearance_settings()
        self.font_size_spin.setValue(int(self._appearance.font_size))
        self.show_scrollbar_chk.setChecked(bool(self._appearance.show_scrollbar))
        self.antialias_chk.setChecked(bool(self._appearance.item_antialias))
        self.window_bg_btn.set_color(self._appearance.window_bg)
        self.item_bg_btn.set_color(self._appearance.item_bg)
        self.item_selected_bg_btn.set_color(self._appearance.item_selected_bg)

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
            theme_mode=normalize_theme_mode(
                str(self.theme_mode_combo.currentData() or "follow_system")
            ),
            note_color=self._note_color,
            note_font_size=int(self.note_font_spin.value()),
            pinned_color=self._pinned_color,
        )
