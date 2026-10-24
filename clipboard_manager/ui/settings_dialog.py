from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional

from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialogButtonBox,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .theme import (
    AppearanceSettings,
    THEME_MODES,
    THEME_STYLE_LABELS,
    build_theme_tokens_from_appearance,
    current_theme_tokens,
    default_appearance_settings,
    normalize_theme_mode,
    theme_style_colors,
)
from .dialog_base import ResizableDialog
from .icons import line_icon
from .settings_widgets import (
    AppearancePreview,
    ColorPickButton,
    NotePreview,
    SegmentedControl,
    SettingRow,
    SettingsSection,
    ShortcutGrid,
    ThemeStyleSelector,
    ToggleSwitch,
    pick_color,
)
from ..version import APP_VERSION
from ..config import app_data_dir, default_hotkey, log_file_path

PRESET_COLORS = {
    "简约白": ("#f6f9ff", "#ffffff", "#8fc1f3"),
    "护眼豆沙": ("#e9f1ea", "#ffffff", "#a9cdb4"),
    "商务蓝灰": ("#e8edf5", "#ffffff", "#b7d0f0"),
    "冰川蓝": ("#edf7ff", "#ffffff", "#a8d8f0"),
    "雾松绿": ("#eef6f1", "#ffffff", "#b9d8c8"),
}

THEME_MODE_LABELS = {
    "follow_system": "跟随系统",
    "light": "浅色",
    "dark": "深色",
}



def _to_qt_hotkey_text(hotkey_text: str) -> str:
    """Translate the service-layer "Win" modifier to Qt's "Meta" for display.

    QKeySequence cannot round-trip "Win+<key>" (it parses but renders an empty
    string), while normalize_hotkey stores the Windows key as "Win".
    """
    parts = [part.strip() for part in str(hotkey_text or "").split("+") if part.strip()]
    return "+".join("Meta" if part.lower() == "win" else part for part in parts)

NAV_PAGES = (
    ("通用", "general"),
    ("外观", "appearance"),
    ("备注与置顶", "note"),
    ("数据", "data"),
    ("关于", "about"),
)


def _create_nav_icon(kind: str, color: str) -> QIcon:
    """Line icons for the settings nav, drawn consistently with the app icon set."""
    return line_icon(f"nav_{kind}", color, 18)


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
    apply_only: bool = False
    auto_check_update: bool = True
    diagnostic_logging: bool = True
    capture_enabled: bool = True
    capture_toggle_hotkey: str = "Ctrl+Shift+P"



class SettingsDialog(ResizableDialog):
    _size_key = "settings_v2"
    _default_size = (820, 680)
    _min_size = (700, 560)
    _frameless_glass = True

    apply_requested = Signal(object)
    check_update_requested = Signal()
    clear_data_requested = Signal()
    vacuum_database_requested = Signal()

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
        auto_check_update: bool = True,
        diagnostic_logging: bool = True,
        capture_enabled: bool = True,
        capture_toggle_hotkey: str = "Ctrl+Shift+P",
        data_stats: Optional[dict] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setObjectName("settingsDialog")

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
        self._auto_check_update_initial = bool(auto_check_update)
        self._diagnostic_logging_initial = bool(diagnostic_logging)
        self._capture_enabled_initial = bool(capture_enabled)
        self._capture_toggle_hotkey_initial = str(capture_toggle_hotkey or "Ctrl+Shift+P")
        self._data_stats = dict(data_stats or {})
        self._export_requested = False
        self._import_requested = False

        self._build_ui()

    # ---------- UI scaffolding ----------

    def _build_ui(self) -> None:
        root = self.content_layout
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.nav_list = QListWidget(self)
        self.nav_list.setObjectName("settingsNav")
        self.nav_list.setFixedWidth(168)
        self.nav_list.setSpacing(2)
        self.nav_list.setIconSize(QSize(17, 17))
        self.nav_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for label, kind in NAV_PAGES:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, kind)
            item.setSizeHint(QSize(0, 38))
            self.nav_list.addItem(item)
        self.nav_list.currentRowChanged.connect(self._refresh_nav_icons)
        body.addWidget(self.nav_list)

        self.pages = QStackedWidget(self)
        self.pages.setObjectName("settingsPages")
        self.pages.addWidget(self._wrap_scroll(self._build_general_page()))
        self.pages.addWidget(self._wrap_scroll(self._build_appearance_page()))
        self.pages.addWidget(self._wrap_scroll(self._build_note_page()))
        self.pages.addWidget(self._wrap_scroll(self._build_data_page()))
        self.pages.addWidget(self._wrap_scroll(self._build_about_page()))

        right_column = QWidget(self)
        right_layout = QVBoxLayout(right_column)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        search_wrap = QWidget(right_column)
        search_wrap_layout = QHBoxLayout(search_wrap)
        search_wrap_layout.setContentsMargins(20, 14, 20, 6)
        search_wrap_layout.setSpacing(0)
        self.settings_search = QLineEdit(search_wrap)
        self.settings_search.setObjectName("settingsSearchInput")
        self.settings_search.setPlaceholderText("搜索设置项…")
        self.settings_search.setClearButtonEnabled(True)
        self.settings_search.textChanged.connect(self._apply_settings_filter)
        search_wrap_layout.addWidget(self.settings_search)
        right_layout.addWidget(search_wrap)
        right_layout.addWidget(self.pages, 1)
        body.addWidget(right_column, 1)
        root.addLayout(body, 1)

        footer = QWidget(self)
        footer.setObjectName("settingsFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(18, 12, 18, 12)
        footer_layout.setSpacing(8)
        self.apply_status_label = QLabel(footer)
        self.apply_status_label.setObjectName("settingsApplyStatus")
        footer_layout.addWidget(self.apply_status_label)
        footer_layout.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.Cancel,
            parent=footer,
        )
        save_btn = buttons.button(QDialogButtonBox.StandardButton.Save)
        if save_btn is not None:
            save_btn.setText("保存")
            save_btn.setObjectName("primaryButton")
            save_btn.setDefault(True)
        apply_btn = buttons.button(QDialogButtonBox.StandardButton.Apply)
        if apply_btn is not None:
            apply_btn.setText("应用")
            apply_btn.clicked.connect(self._on_apply_clicked)
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
        scroll.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        scroll.viewport().setObjectName("settingsScrollViewport")
        scroll.viewport().setAutoFillBackground(False)
        page.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        scroll.setWidget(page)
        return scroll

    @staticmethod
    def _new_page(title: str, subtitle: str = "") -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(16)
        header_box = QVBoxLayout()
        header_box.setContentsMargins(0, 0, 0, 2)
        header_box.setSpacing(2)
        header = QLabel(title, page)
        header.setObjectName("settingsPageTitle")
        header_box.addWidget(header)
        if subtitle:
            sub = QLabel(subtitle, page)
            sub.setObjectName("settingsPageSubtitle")
            header_box.addWidget(sub)
        layout.addLayout(header_box)
        return page, layout

    def _refresh_nav_icons(self, current_row: int = -1) -> None:
        tokens = current_theme_tokens()
        accent = tokens.accent_bg
        secondary = tokens.text_secondary
        for idx in range(self.nav_list.count()):
            item = self.nav_list.item(idx)
            kind = str(item.data(Qt.ItemDataRole.UserRole) or "")
            if not kind:
                continue
            item.setIcon(_create_nav_icon(kind, accent if idx == current_row else secondary))

    # ---------- pages ----------

    def _build_general_page(self) -> QWidget:
        page, layout = self._new_page("通用", "快捷键、开机启动与剪贴板监听")

        self.hotkey_edit = QKeySequenceEdit(page)
        self.hotkey_edit.setMaximumSequenceLength(1)
        self.hotkey_edit.setFixedWidth(190)
        self.hotkey_edit.setAccessibleName("全局快捷键")
        self.hotkey_edit.setToolTip("点击后按下新的组合键")
        if self._hotkey_initial:
            self.hotkey_edit.setKeySequence(QKeySequence(_to_qt_hotkey_text(self._hotkey_initial)))

        hotkey_reset_btn = QPushButton("恢复默认", page)
        hotkey_reset_btn.setToolTip(f"恢复默认：{default_hotkey()}")
        hotkey_reset_btn.clicked.connect(self._reset_hotkey_to_default)
        hotkey_widget = QWidget(page)
        hotkey_layout = QHBoxLayout(hotkey_widget)
        hotkey_layout.setContentsMargins(0, 0, 0, 0)
        hotkey_layout.setSpacing(6)
        hotkey_layout.addWidget(self.hotkey_edit)
        hotkey_layout.addWidget(hotkey_reset_btn)

        self.capture_tab_combo = QComboBox(page)
        self.capture_tab_combo.setFixedWidth(190)
        self.capture_tab_combo.setAccessibleName("监听存储标签")
        for tab_id, tab_name in self._tabs:
            self.capture_tab_combo.addItem(tab_name, tab_id)
        if self._capture_tab_initial is not None:
            index = self.capture_tab_combo.findData(self._capture_tab_initial)
            if index >= 0:
                self.capture_tab_combo.setCurrentIndex(index)
        self.capture_tab_combo.currentIndexChanged.connect(
            self._refresh_capture_tab_tooltip
        )
        self._refresh_capture_tab_tooltip()

        self.capture_max_spin = QSpinBox(page)
        self.capture_max_spin.setRange(50, 5000)
        self.capture_max_spin.setSingleStep(50)
        self.capture_max_spin.setFixedWidth(120)
        self.capture_max_spin.setSuffix(" 条")
        self.capture_max_spin.setAccessibleName("监听标签条目上限")
        self.capture_max_spin.setToolTip("范围：50–5000 条")
        self.capture_max_spin.setValue(int(self._capture_max_initial))

        self.autostart_chk = ToggleSwitch(page)
        self.autostart_chk.setAccessibleName("开机自动启动")
        self.autostart_chk.setChecked(bool(self._autostart_initial))

        self.capture_toggle_hotkey_edit = QKeySequenceEdit(page)
        self.capture_toggle_hotkey_edit.setMaximumSequenceLength(1)
        self.capture_toggle_hotkey_edit.setFixedWidth(190)
        self.capture_toggle_hotkey_edit.setAccessibleName("暂停或恢复监听快捷键")
        self.capture_toggle_hotkey_edit.setToolTip("点击后按下新的组合键")
        if self._capture_toggle_hotkey_initial:
            self.capture_toggle_hotkey_edit.setKeySequence(
                QKeySequence(_to_qt_hotkey_text(self._capture_toggle_hotkey_initial))
            )

        self.capture_toggle_hotkey_reset_btn = QPushButton("恢复默认", page)
        self.capture_toggle_hotkey_reset_btn.setToolTip("恢复默认：Ctrl+Shift+P")
        self.capture_toggle_hotkey_reset_btn.clicked.connect(
            self._reset_capture_toggle_hotkey
        )
        toggle_hotkey_widget = QWidget(page)
        toggle_hotkey_layout = QHBoxLayout(toggle_hotkey_widget)
        toggle_hotkey_layout.setContentsMargins(0, 0, 0, 0)
        toggle_hotkey_layout.setSpacing(6)
        toggle_hotkey_layout.addWidget(self.capture_toggle_hotkey_edit)
        toggle_hotkey_layout.addWidget(self.capture_toggle_hotkey_reset_btn)

        section = SettingsSection("快捷键与启动", page)
        section.add_row(
            SettingRow(
                "全局快捷键",
                hotkey_widget,
                "打开面板的快捷键，至少一个修饰键加一个主键，例如 Ctrl+Shift+V。",
            )
        )
        section.add_row(
            SettingRow(
                "暂停/恢复监听快捷键",
                toggle_hotkey_widget,
                "一键暂停或恢复自动记录剪贴板，默认 Ctrl+Shift+P。",
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
        self.capture_enabled_chk = ToggleSwitch(page)
        self.capture_enabled_chk.setAccessibleName("自动记录剪贴板")
        self.capture_enabled_chk.setChecked(bool(self._capture_enabled_initial))
        capture_section.add_row(
            SettingRow(
                "自动记录剪贴板",
                self.capture_enabled_chk,
                "关闭后停止把新的复制内容保存到标签页，可随时重新开启。",
            )
        )
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

        self.shortcut_overview_section = SettingsSection("快捷键一览", page)
        self._shortcut_grid = ShortcutGrid(self._shortcut_rows(), page)
        self._shortcut_value_labels = self._shortcut_grid.value_labels
        self.shortcut_overview_section.add_card_widget(self._shortcut_grid)
        layout.addWidget(self.shortcut_overview_section)
        self.hotkey_edit.keySequenceChanged.connect(self._refresh_shortcut_overview)
        self.capture_toggle_hotkey_edit.keySequenceChanged.connect(
            self._refresh_shortcut_overview
        )
        layout.addStretch(1)
        return page

    def _shortcut_rows(self) -> list[tuple[str, str]]:
        open_panel = self.hotkey_edit.keySequence().toString(
            QKeySequence.SequenceFormat.PortableText
        ) or "未设置"
        toggle = self.capture_toggle_hotkey_edit.keySequence().toString(
            QKeySequence.SequenceFormat.PortableText
        ) or "未设置"
        return [
            ("打开面板", open_panel),
            ("暂停/恢复监听", toggle),
            ("搜索条目", "Ctrl + F"),
            ("新建条目", "Ctrl + N"),
            ("粘贴选中条目", "Enter"),
            ("快速粘贴第 1–9 条", "1 – 9"),
        ]

    def _refresh_shortcut_overview(self, *_args) -> None:
        grid = getattr(self, "_shortcut_grid", None)
        if grid is not None:
            grid.set_values(self._shortcut_rows())

    def _refresh_capture_tab_tooltip(self, *_args) -> None:
        text = self.capture_tab_combo.currentText().strip()
        self.capture_tab_combo.setToolTip(text or "没有可用的标签页")



    def _build_appearance_page(self) -> QWidget:
        page, layout = self._new_page("外观", "主题、配色与显示效果")

        self.theme_mode_segment = SegmentedControl(
            [(mode_key, THEME_MODE_LABELS[mode_key]) for mode_key in THEME_MODES],
            page,
        )
        self.theme_mode_segment.set_current(self._theme_mode_initial)
        self.theme_mode_segment.valueChanged.connect(lambda _=None: self._refresh_preview())

        mode_section = SettingsSection("主题", page)
        mode_section.add_row(
            SettingRow(
                "主题模式",
                self.theme_mode_segment,
                "跟随系统时会随 Windows 深浅色自动切换。",
            )
        )
        layout.addWidget(mode_section)

        self.theme_style_selector = ThemeStyleSelector(
            [(style_key, style_label) for style_key, style_label in THEME_STYLE_LABELS.items()],
            page,
        )
        self.theme_style_selector.set_current(self._appearance.theme_style)
        self.theme_style_selector.styleSelected.connect(self._on_theme_style_selected)

        style_section = SettingsSection("主题风格", page)
        style_section.add_widget(self.theme_style_selector)
        layout.addWidget(style_section)

        self.preview = AppearancePreview(page)
        preview_section = SettingsSection("预览", page)
        preview_section.add_widget(self.preview)
        layout.addWidget(preview_section)

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

        color_section = SettingsSection("自定义颜色", page)
        color_section.add_row(SettingRow("窗口背景", self.window_bg_btn))
        color_section.add_row(SettingRow("条目背景", self.item_bg_btn))
        color_section.add_row(SettingRow("选中条目背景", self.item_selected_bg_btn))
        layout.addWidget(color_section)

        self.show_scrollbar_chk = ToggleSwitch(page)
        self.show_scrollbar_chk.setChecked(bool(self._appearance.show_scrollbar))
        self.antialias_chk = ToggleSwitch(page)
        self.antialias_chk.setChecked(bool(self._appearance.item_antialias))
        self.backdrop_blur_chk = ToggleSwitch(page)
        self.backdrop_blur_chk.setChecked(bool(self._appearance.backdrop_blur))

        reset_btn = QPushButton("重置外观为默认", page)
        reset_btn.clicked.connect(self._reset_appearance_defaults)

        display_section = SettingsSection("显示", page)
        display_section.add_row(SettingRow("全局字体大小", self.font_size_spin))
        display_section.add_row(SettingRow("显示滚动条", self.show_scrollbar_chk))
        display_section.add_row(
            SettingRow("条目抗锯齿", self.antialias_chk, "关闭后绘制更快，边缘略硬。")
        )
        display_section.add_row(
            SettingRow(
                "背景模糊",
                self.backdrop_blur_chk,
                "「通透」档会模糊桌面背景；个别机器卡顿可关闭。",
            )
        )
        display_section.add_row(SettingRow("恢复默认外观", reset_btn))
        layout.addWidget(display_section)
        layout.addStretch(1)
        self._refresh_preview()
        return page

    def _build_note_page(self) -> QWidget:
        page, layout = self._new_page("备注与置顶", "备注文字与置顶标记样式")

        self.note_color_btn = ColorPickButton(self._note_color, page)
        self.note_color_btn.clicked.connect(self._pick_note_color)

        self.note_font_spin = QSpinBox(page)
        self.note_font_spin.setRange(10, 28)
        self.note_font_spin.setFixedWidth(120)
        self.note_font_spin.setSuffix(" px")
        self.note_font_spin.setValue(int(self._note_font_size_initial))
        self.note_font_spin.valueChanged.connect(lambda _=None: self._refresh_note_preview())

        self.pinned_color_btn = ColorPickButton(self._pinned_color, page)
        self.pinned_color_btn.clicked.connect(self._pick_pinned_color)

        self.note_preview = NotePreview(page)
        preview_section = SettingsSection("预览", page)
        preview_section.add_widget(self.note_preview)
        layout.addWidget(preview_section)

        note_section = SettingsSection("备注样式", page)
        note_section.add_row(
            SettingRow("备注文字颜色", self.note_color_btn, "深色模式下会自动提亮以保证可读。")
        )
        note_section.add_row(SettingRow("备注文字大小", self.note_font_spin))
        layout.addWidget(note_section)

        pinned_presets = QWidget(page)
        pinned_presets_layout = QHBoxLayout(pinned_presets)
        pinned_presets_layout.setContentsMargins(0, 0, 0, 0)
        pinned_presets_layout.setSpacing(6)
        for color_hex in ("#1fb8cb", "#1677c8", "#4f9d69", "#d97706", "#8b5cf6", "#d0534b"):
            swatch = QPushButton(pinned_presets)
            swatch.setFixedSize(QSize(26, 26))
            swatch.setCursor(Qt.CursorShape.PointingHandCursor)
            swatch.setToolTip(color_hex.upper())
            swatch.setStyleSheet(
                f"QPushButton {{ background: {color_hex}; border: 1px solid rgba(0,0,0,40);"
                f" border-radius: 7px; }}"
            )
            swatch.clicked.connect(
                lambda _=False, c=color_hex: self._set_pinned_color(c)
            )
            pinned_presets_layout.addWidget(swatch)

        pinned_section = SettingsSection("置顶标记", page)
        pinned_section.add_row(
            SettingRow("置顶强调色", self.pinned_color_btn, "用于置顶条目的左侧色条与描边。")
        )
        pinned_section.add_row(SettingRow("快速选择", pinned_presets))
        layout.addWidget(pinned_section)
        layout.addStretch(1)
        self._refresh_note_preview()
        return page

    def _set_pinned_color(self, color_hex: str) -> None:
        self._pinned_color = color_hex
        self.pinned_color_btn.set_color(color_hex)
        self._refresh_note_preview()

    def _refresh_note_preview(self) -> None:
        preview = getattr(self, "note_preview", None)
        if preview is None:
            return
        preview.set_style(
            self._note_color,
            int(self.note_font_spin.value()),
            self._pinned_color,
        )

    def _build_data_page(self) -> QWidget:
        page, layout = self._new_page("数据", "备份、迁移与数据管理")

        self.data_tabs_label = QLabel("—", page)
        self.data_items_label = QLabel("—", page)
        self.data_images_label = QLabel("—", page)
        self.data_size_label = QLabel("—", page)
        for label in (
            self.data_tabs_label,
            self.data_items_label,
            self.data_images_label,
            self.data_size_label,
        ):
            label.setObjectName("shortcutKeyLabel")

        stats_section = SettingsSection("数据统计", page)
        stats_section.add_row(SettingRow("标签页数量", self.data_tabs_label))
        stats_section.add_row(SettingRow("条目总数", self.data_items_label))
        stats_section.add_row(SettingRow("图片条目", self.data_images_label))
        stats_section.add_row(SettingRow("数据库占用", self.data_size_label))
        layout.addWidget(stats_section)

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

        open_dir_btn = QPushButton("打开数据目录", page)
        open_dir_btn.clicked.connect(self._open_data_dir)
        vacuum_btn = QPushButton("压缩数据库…", page)
        vacuum_btn.clicked.connect(self.vacuum_database_requested.emit)
        clear_btn = QPushButton("清空所有条目", page)
        clear_btn.setObjectName("dangerButton")
        clear_btn.clicked.connect(self.clear_data_requested.emit)

        manage_section = SettingsSection("数据管理", page)
        manage_section.add_row(
            SettingRow("数据目录", open_dir_btn, "打开存放数据库与日志的文件夹。")
        )
        manage_section.add_row(
            SettingRow(
                "压缩数据库",
                vacuum_btn,
                "把已删除条目占用的空间还给硬盘，大数据库可能需要几分钟。",
            )
        )
        manage_section.add_row(
            SettingRow(
                "清空所有条目",
                clear_btn,
                "删除全部标签页中的条目，标签页会保留。",
            )
        )
        layout.addWidget(manage_section)

        self._apply_data_stats()
        layout.addStretch(1)
        return page

    def _open_data_dir(self) -> None:
        target = app_data_dir()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    @staticmethod
    def _format_size(num_bytes: int) -> str:
        size = float(max(0, int(num_bytes)))
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024.0 or unit == "GB":
                if unit == "B":
                    return f"{int(size)} {unit}"
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} GB"

    def _apply_data_stats(self) -> None:
        stats = self._data_stats or {}
        self.data_tabs_label.setText(str(stats.get("tabs", "—")))
        self.data_items_label.setText(str(stats.get("items", "—")))
        self.data_images_label.setText(str(stats.get("images", "—")))
        db_bytes = stats.get("db_bytes")
        self.data_size_label.setText(
            self._format_size(db_bytes) if db_bytes is not None else "—"
        )

    def set_data_stats(self, stats: Optional[dict]) -> None:
        self._data_stats = dict(stats or {})
        self._apply_data_stats()

    def _build_about_page(self) -> QWidget:
        page, layout = self._new_page("关于", "版本信息、更新与诊断日志")

        header = QHBoxLayout()
        icon_label = QLabel(page)
        window_icon = self.windowIcon()
        if not window_icon.isNull():
            icon_label.setPixmap(window_icon.pixmap(44, 44))
        header.addWidget(icon_label)
        name_column = QVBoxLayout()
        name_column.setContentsMargins(0, 0, 0, 0)
        name_column.setSpacing(2)
        name_label = QLabel("ClipNest", page)
        name_label.setObjectName("aboutAppName")
        name_column.addWidget(name_label)
        self.current_version_label = QLabel(f"当前版本 v{APP_VERSION}", page)
        self.current_version_label.setObjectName("settingRowDescription")
        name_column.addWidget(self.current_version_label)
        header.addLayout(name_column)
        header.addStretch(1)
        layout.addLayout(header)

        self.latest_version_label = QLabel("最新版本：未知（点击检查更新）", page)
        repo_link = QLabel(
            '<a href="https://github.com/fancha0/ClipNest">github.com/fancha0/ClipNest</a>',
            page,
        )
        repo_link.setOpenExternalLinks(False)
        repo_link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        repo_link.linkActivated.connect(
            lambda url: QDesktopServices.openUrl(QUrl(url))
        )
        copy_btn = QPushButton("复制版本信息", page)
        copy_btn.clicked.connect(self._copy_version_info)

        info_section = SettingsSection("版本信息", page)
        info_section.add_row(SettingRow("最新版本", self.latest_version_label))
        info_section.add_row(SettingRow("仓库地址", repo_link))
        info_section.add_row(
            SettingRow("复制版本信息", copy_btn, "复制版本号与系统信息，便于反馈问题。")
        )
        layout.addWidget(info_section)

        self.check_update_btn = QPushButton("检查更新", page)
        self.check_update_btn.clicked.connect(self._on_check_update_clicked)

        self.auto_update_chk = ToggleSwitch(page)
        self.auto_update_chk.setChecked(self._auto_check_update_initial)

        update_section = SettingsSection("更新", page)
        update_section.add_row(
            SettingRow(
                "检查更新",
                self.check_update_btn,
                "从更新服务器获取最新版本并自动安装。",
            )
        )
        update_section.add_row(
            SettingRow(
                "启动时自动检查",
                self.auto_update_chk,
                "启动后自动静默检查，发现新版本时弹出更新窗口。",
            )
        )
        layout.addWidget(update_section)

        self.diagnostic_logging_chk = ToggleSwitch(page)
        self.diagnostic_logging_chk.setChecked(self._diagnostic_logging_initial)
        self.open_log_btn = QPushButton("打开日志", page)
        self.open_log_btn.clicked.connect(self._open_log_file)
        self.clear_log_btn = QPushButton("清空日志", page)
        self.clear_log_btn.clicked.connect(self._clear_log_file)
        log_actions = QWidget(page)
        log_actions_layout = QHBoxLayout(log_actions)
        log_actions_layout.setContentsMargins(0, 0, 0, 0)
        log_actions_layout.setSpacing(6)
        log_actions_layout.addWidget(self.open_log_btn)
        log_actions_layout.addWidget(self.clear_log_btn)

        self.log_info_label = QLabel("", page)
        self.log_info_label.setObjectName("settingRowDescription")
        self.log_info_label.setWordWrap(True)
        self._refresh_log_info()

        log_section = SettingsSection("诊断日志", page)
        log_section.add_row(
            SettingRow(
                "记录诊断日志",
                self.diagnostic_logging_chk,
                "遇到问题时开启，可帮助定位剪贴板抓取/粘贴异常。",
            )
        )
        log_section.add_row(SettingRow("日志操作", log_actions))
        log_section.add_row(SettingRow("日志文件", self.log_info_label))
        layout.addWidget(log_section)
        layout.addStretch(1)
        return page

    def _refresh_log_info(self) -> None:
        path = log_file_path()
        try:
            size = path.stat().st_size if path.exists() else 0
            self.log_info_label.setText(f"{path}\n占用 {self._format_size(size)}")
        except OSError:
            self.log_info_label.setText(str(path))

    def _copy_version_info(self) -> None:
        import platform

        text = (
            f"ClipNest v{APP_VERSION}\n"
            f"系统：{platform.system()} {platform.release()}\n"
            f"Python：{platform.python_version()}"
        )
        QApplication.clipboard().setText(text)
        self.set_apply_feedback("已复制版本信息")

    def _open_log_file(self) -> None:
        path = log_file_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _clear_log_file(self) -> None:
        try:
            log_file_path().write_text("", encoding="utf-8")
            self._refresh_log_info()
            self.set_apply_feedback("诊断日志已清空")
        except OSError as exc:
            self.set_apply_feedback(f"清空日志失败：{exc}")

    def set_latest_version(self, version: str, newer: bool) -> None:
        suffix = "发现新版本" if newer else "已是最新"
        self.latest_version_label.setText(f"最新版本 v{version}（{suffix}）")

    # ---------- behavior ----------

    def _request_export(self) -> None:
        self._export_requested = True
        self.accept()

    def _request_import(self) -> None:
        self._import_requested = True
        self.accept()

    def _pick_appearance_color(self, key: str) -> None:
        current = getattr(self._appearance, key)
        chosen = pick_color(self, "选择颜色", current)
        if not chosen:
            return
        self._appearance = replace(self._appearance, **{key: chosen})
        button = {
            "window_bg": self.window_bg_btn,
            "item_bg": self.item_bg_btn,
            "item_selected_bg": self.item_selected_bg_btn,
        }[key]
        button.set_color(chosen)
        self._refresh_preview()

    def _pick_note_color(self) -> None:
        chosen = pick_color(self, "选择备注文字颜色", self._note_color)
        if not chosen:
            return
        self._note_color = chosen
        self.note_color_btn.set_color(self._note_color)
        self._refresh_note_preview()

    def _pick_pinned_color(self) -> None:
        chosen = pick_color(self, "选择置顶颜色", self._pinned_color)
        if not chosen:
            return
        self._pinned_color = chosen
        self.pinned_color_btn.set_color(self._pinned_color)
        self._refresh_note_preview()

    def _on_theme_style_selected(self, style: str) -> None:
        if not style:
            return
        window_bg, item_bg, item_selected_bg = theme_style_colors(style)
        self._appearance = replace(
            self._appearance,
            theme_style=style,
            window_bg=window_bg,
            item_bg=item_bg,
            item_selected_bg=item_selected_bg,
        )
        self.window_bg_btn.set_color(window_bg)
        self.item_bg_btn.set_color(item_bg)
        self.item_selected_bg_btn.set_color(item_selected_bg)
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        preview = getattr(self, "preview", None)
        if preview is None:
            return
        accent = self.accent_color_combo.currentData() if hasattr(self, "accent_color_combo") else None
        candidate = replace(
            self._appearance,
            accent_color=str(accent or self._appearance.accent_color),
        )
        tokens = build_theme_tokens_from_appearance(candidate)
        preview.set_colors(
            tokens.main_window_bg,
            tokens.item_bg,
            tokens.item_selected_bg,
            tokens.accent_bg,
        )

    def _reset_appearance_defaults(self) -> None:
        self._appearance = default_appearance_settings()
        self.font_size_spin.setValue(int(self._appearance.font_size))
        self.show_scrollbar_chk.setChecked(bool(self._appearance.show_scrollbar))
        self.antialias_chk.setChecked(bool(self._appearance.item_antialias))
        self.backdrop_blur_chk.setChecked(bool(self._appearance.backdrop_blur))
        self.window_bg_btn.set_color(self._appearance.window_bg)
        self.item_bg_btn.set_color(self._appearance.item_bg)
        self.item_selected_bg_btn.set_color(self._appearance.item_selected_bg)
        self.theme_style_selector.set_current(self._appearance.theme_style)
        self._refresh_preview()

    # ---------- results ----------

    def _on_apply_clicked(self) -> None:
        self.apply_requested.emit(self.result_payload())

    def _apply_settings_filter(self, text: str) -> None:
        query = (text or "").strip()
        for section in self.findChildren(SettingsSection):
            section.apply_filter(query)

    def _reset_hotkey_to_default(self) -> None:
        self.hotkey_edit.setKeySequence(QKeySequence(_to_qt_hotkey_text(default_hotkey())))

    def _reset_capture_toggle_hotkey(self) -> None:
        self.capture_toggle_hotkey_edit.setKeySequence(
            QKeySequence(_to_qt_hotkey_text("Ctrl+Shift+P"))
        )

    def set_apply_feedback(self, text: str) -> None:
        self.apply_status_label.setText(text)
        self.apply_status_label.setToolTip(text)
        self.apply_status_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        generation = getattr(self, "_apply_feedback_generation", 0) + 1
        self._apply_feedback_generation = generation

        def _clear() -> None:
            if getattr(self, "_apply_feedback_generation", 0) == generation:
                self.apply_status_label.clear()
                self.apply_status_label.setToolTip("")

        QTimer.singleShot(5000, _clear)

    def _on_check_update_clicked(self) -> None:
        self.set_apply_feedback("正在检查更新...")
        self.check_update_requested.emit()

    def set_update_status(self, text: str) -> None:
        self.set_apply_feedback(text)

    def set_update_checking(self, checking: bool) -> None:
        self.check_update_btn.setEnabled(not checking)
        self.check_update_btn.setText("检查中..." if checking else "检查更新")

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
            appearance=replace(
                self._appearance,
                font_size=int(self.font_size_spin.value()),
                theme_style=str(self.theme_style_selector.current_style() or self._appearance.theme_style),
                backdrop_blur=bool(self.backdrop_blur_chk.isChecked()),
                show_scrollbar=bool(self.show_scrollbar_chk.isChecked()),
                item_antialias=bool(self.antialias_chk.isChecked()),
            ),
            theme_mode=normalize_theme_mode(
                str(self.theme_mode_segment.current_key() or "follow_system")
            ),
            note_color=self._note_color,
            note_font_size=int(self.note_font_spin.value()),
            pinned_color=self._pinned_color,
            auto_check_update=bool(self.auto_update_chk.isChecked()),
            diagnostic_logging=bool(self.diagnostic_logging_chk.isChecked()),
            capture_enabled=bool(self.capture_enabled_chk.isChecked()),
            capture_toggle_hotkey=(
                self.capture_toggle_hotkey_edit.keySequence()
                .toString(QKeySequence.SequenceFormat.PortableText)
            ),
        )
