from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

ThemeMode = Literal["follow_system", "light", "dark"]
THEME_MODES: tuple[str, ...] = ("follow_system", "light", "dark")


def normalize_theme_mode(value: str | None) -> ThemeMode:
    text = (value or "").strip().lower()
    if text in THEME_MODES:
        return text  # type: ignore[return-value]
    return "follow_system"


@dataclass(frozen=True, slots=True)
class AppearanceSettings:
    window_bg: str
    font_size: int
    item_bg: str
    item_selected_bg: str
    show_scrollbar: bool
    item_antialias: bool


def default_appearance_settings() -> AppearanceSettings:
    return AppearanceSettings(
        window_bg="#f6f8fb",
        font_size=13,
        item_bg="#ffffff",
        item_selected_bg="#eef7ff",
        show_scrollbar=True,
        item_antialias=True,
    )


def default_dark_appearance_settings() -> AppearanceSettings:
    return AppearanceSettings(
        window_bg="#1d2430",
        font_size=13,
        item_bg="#27303f",
        item_selected_bg="#32445c",
        show_scrollbar=True,
        item_antialias=True,
    )


def resolve_dark_mode(mode: ThemeMode, system_dark: bool) -> bool:
    if mode == "dark":
        return True
    if mode == "light":
        return False
    return bool(system_dark)


def effective_appearance(
    mode: ThemeMode,
    user_appearance: AppearanceSettings,
    system_dark: bool,
) -> AppearanceSettings:
    """Return the appearance to render: dark palette when dark is in effect,
    otherwise the user's customized (light) palette."""
    if resolve_dark_mode(mode, system_dark):
        dark = default_dark_appearance_settings()
        return replace(
            dark,
            font_size=max(10, min(28, int(user_appearance.font_size))),
            show_scrollbar=bool(user_appearance.show_scrollbar),
            item_antialias=bool(user_appearance.item_antialias),
        )
    return user_appearance


@dataclass(frozen=True, slots=True)
class ThemeTokens:
    main_window_bg: str
    window_start: str
    window_end: str
    text_primary: str
    text_secondary: str
    panel_bg: str
    panel_border: str
    input_bg: str
    input_border: str
    input_focus_border: str
    input_selection_bg: str
    input_selection_text: str
    item_bg: str
    item_border: str
    item_hover_bg: str
    item_hover_border: str
    item_selected_bg: str
    item_selected_border: str
    item_selected_text: str
    tab_list_bg: str
    item_list_bg: str
    primary_button_bg: str
    primary_button_hover_bg: str
    primary_button_text: str
    primary_button_border: str
    secondary_button_bg: str
    secondary_button_border: str
    secondary_button_hover_bg: str
    secondary_button_hover_border: str
    secondary_button_pressed_bg: str
    tool_button_bg: str
    tool_button_border: str
    tool_button_hover_bg: str
    tool_button_hover_border: str
    tool_button_pressed_bg: str
    menu_bg: str
    menu_border: str
    menu_item_bg: str
    menu_item_border: str
    menu_item_selected_bg: str
    menu_item_selected_border: str
    menu_item_pressed_bg: str
    menu_item_pressed_border: str
    menu_item_disabled_text: str
    menu_item_disabled_bg: str
    menu_item_disabled_border: str
    menu_separator: str
    menu_item_text: str
    menu_item_selected_text: str
    focus_ring: str
    dialog_bg: str
    dialog_label_text: str
    splitter_handle_bg: str
    statusbar_bg: str
    statusbar_border: str
    statusbar_text: str
    label_text: str
    scrollbar_track: str
    scrollbar_handle: str
    scrollbar_handle_hover: str
    scrollbar_handle_pressed: str
    base_font_size: int
    show_scrollbar: bool
    is_dark: bool = False
    note_badge_bg_alpha: int = 52
    note_badge_radius: int = 7
    note_badge_padding_x: int = 8
    note_badge_padding_y: int = 3


def _clamp(value: int) -> int:
    return max(0, min(255, int(value)))


def _parse_hex(color: str, fallback: str) -> tuple[int, int, int]:
    text = (color or "").strip()
    if len(text) == 7 and text.startswith("#"):
        try:
            return int(text[1:3], 16), int(text[3:5], 16), int(text[5:7], 16)
        except ValueError:
            pass
    return _parse_hex(fallback, "#f6f7fa") if color != fallback else (246, 247, 250)


def normalize_hex_color(value: str | None, fallback: str) -> str:
    r, g, b = _parse_hex(value or "", fallback)
    return f"#{r:02x}{g:02x}{b:02x}"


def _hex_to_rgb(color: str, fallback: str) -> tuple[int, int, int]:
    return _parse_hex(color, fallback)


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    r, g, b = rgb
    return f"#{_clamp(r):02x}{_clamp(g):02x}{_clamp(b):02x}"


def _mix(c1: tuple[int, int, int], c2: tuple[int, int, int], ratio: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, float(ratio)))
    return (
        _clamp(round(c1[0] * (1.0 - t) + c2[0] * t)),
        _clamp(round(c1[1] * (1.0 - t) + c2[1] * t)),
        _clamp(round(c1[2] * (1.0 - t) + c2[2] * t)),
    )


def _lighten(color: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    return _mix(color, (255, 255, 255), amount)


def _darken(color: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    return _mix(color, (0, 0, 0), amount)


def _tone(color: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    if amount >= 0:
        return _darken(color, amount)
    return _lighten(color, abs(amount))


def _luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = rgb
    return 0.299 * r + 0.587 * g + 0.114 * b


def _contrast_text(background: tuple[int, int, int]) -> str:
    return "#f5f8ff" if _luminance(background) < 145 else "#242a33"


def build_theme_tokens_from_appearance(appearance: AppearanceSettings) -> ThemeTokens:
    defaults = default_appearance_settings()
    window_hex = normalize_hex_color(appearance.window_bg, defaults.window_bg)
    item_hex = normalize_hex_color(appearance.item_bg, defaults.item_bg)
    selected_hex = normalize_hex_color(appearance.item_selected_bg, defaults.item_selected_bg)
    font_size = max(10, min(28, int(appearance.font_size)))
    show_scrollbar = bool(appearance.show_scrollbar)

    window_rgb = _hex_to_rgb(window_hex, defaults.window_bg)
    item_rgb = _hex_to_rgb(item_hex, defaults.item_bg)
    selected_rgb = _hex_to_rgb(selected_hex, defaults.item_selected_bg)
    is_dark_window = _luminance(window_rgb) < 145

    if is_dark_window:
        text_primary = "#e2e9f5"
        text_secondary = "#a8b4c8"
        panel_bg = _rgb_to_hex(_lighten(window_rgb, 0.10))
        panel_border = _rgb_to_hex(_lighten(window_rgb, 0.22))
        input_bg = _rgb_to_hex(_lighten(window_rgb, 0.14))
        input_border = _rgb_to_hex(_lighten(window_rgb, 0.26))
        input_focus = _rgb_to_hex(_lighten(selected_rgb, 0.16))
        selection_bg = _rgb_to_hex(_darken(selected_rgb, 0.10))
        selection_text = "#f5f8ff"
        disabled_bg = _rgb_to_hex(_lighten(window_rgb, 0.08))
        disabled_border = _rgb_to_hex(_lighten(window_rgb, 0.18))
        menu_bg = _rgb_to_hex(_lighten(window_rgb, 0.12))
        menu_item_bg = _rgb_to_hex(_lighten(window_rgb, 0.16))
        scrollbar_track = _rgb_to_hex(_lighten(window_rgb, 0.20))
        scrollbar_handle = _rgb_to_hex(_lighten(window_rgb, 0.36))
        scrollbar_handle_hover = _rgb_to_hex(_lighten(window_rgb, 0.46))
        scrollbar_handle_pressed = _rgb_to_hex(_lighten(window_rgb, 0.56))
    else:
        text_primary = "#1f2937"
        text_secondary = "#7b8493"
        panel_bg = "#fbfcfe"
        panel_border = "#e8edf4"
        input_bg = "#ffffff"
        input_border = "#e0e7f0"
        input_focus = "#39a7d9"
        selection_bg = "#dff3ff"
        selection_text = "#172554"
        disabled_bg = "#f4f7fb"
        disabled_border = "#e8edf4"
        menu_bg = "#ffffff"
        menu_item_bg = "#ffffff"
        scrollbar_track = "#edf2f7"
        scrollbar_handle = "#cbd5e1"
        scrollbar_handle_hover = "#aebccd"
        scrollbar_handle_pressed = "#8ea0b5"

    item_selected_text = _contrast_text(selected_rgb)
    primary_button_bg = _rgb_to_hex(_darken(selected_rgb, 0.18))
    primary_button_hover_bg = _rgb_to_hex(_darken(selected_rgb, 0.25))
    primary_button_border = _rgb_to_hex(_darken(selected_rgb, 0.32))
    primary_button_text = _contrast_text(_hex_to_rgb(primary_button_bg, "#4b76bb"))

    secondary_bg = input_bg
    secondary_border = _rgb_to_hex(_tone(window_rgb, 0.18 if not is_dark_window else -0.24))
    secondary_hover_bg = _rgb_to_hex(_lighten(_hex_to_rgb(secondary_bg, input_bg), 0.03))
    secondary_hover_border = _rgb_to_hex(_darken(selected_rgb, 0.20))
    secondary_pressed_bg = _rgb_to_hex(_darken(_hex_to_rgb(secondary_bg, input_bg), 0.06))

    menu_item_selected_bg = selected_hex
    menu_item_selected_border = _rgb_to_hex(_darken(selected_rgb, 0.24))
    menu_item_pressed_bg = _rgb_to_hex(_darken(selected_rgb, 0.08))
    menu_item_pressed_border = _rgb_to_hex(_darken(selected_rgb, 0.30))
    menu_item_selected_text = _contrast_text(selected_rgb)

    return ThemeTokens(
        main_window_bg=window_hex,
        window_start=window_hex,
        window_end=window_hex,
        text_primary=text_primary,
        text_secondary=text_secondary,
        panel_bg=panel_bg,
        panel_border=panel_border,
        input_bg=input_bg,
        input_border=input_border,
        input_focus_border=input_focus,
        input_selection_bg=selection_bg,
        input_selection_text=selection_text,
        item_bg=item_hex,
        item_border="#e8edf4" if not is_dark_window else _rgb_to_hex(_tone(item_rgb, -0.18)),
        item_hover_bg=item_hex,
        item_hover_border="#dbe7f3" if not is_dark_window else _rgb_to_hex(_tone(item_rgb, -0.30)),
        item_selected_bg=selected_hex,
        item_selected_border="#38a7dc" if not is_dark_window else _rgb_to_hex(_darken(selected_rgb, 0.24)),
        item_selected_text=item_selected_text,
        tab_list_bg=panel_bg,
        item_list_bg=panel_bg,
        primary_button_bg=primary_button_bg,
        primary_button_hover_bg=primary_button_hover_bg,
        primary_button_text=primary_button_text,
        primary_button_border=primary_button_border,
        secondary_button_bg=secondary_bg,
        secondary_button_border=secondary_border,
        secondary_button_hover_bg=secondary_hover_bg,
        secondary_button_hover_border=secondary_hover_border,
        secondary_button_pressed_bg=secondary_pressed_bg,
        tool_button_bg=secondary_bg,
        tool_button_border=secondary_border,
        tool_button_hover_bg=secondary_hover_bg,
        tool_button_hover_border=secondary_hover_border,
        tool_button_pressed_bg=secondary_pressed_bg,
        menu_bg=menu_bg,
        menu_border=_rgb_to_hex(_tone(window_rgb, 0.16 if not is_dark_window else -0.28)),
        menu_item_bg=menu_item_bg,
        menu_item_border=menu_item_bg,
        menu_item_selected_bg=menu_item_selected_bg,
        menu_item_selected_border=menu_item_selected_border,
        menu_item_pressed_bg=menu_item_pressed_bg,
        menu_item_pressed_border=menu_item_pressed_border,
        menu_item_disabled_text=_rgb_to_hex(_tone(window_rgb, 0.40 if not is_dark_window else -0.50)),
        menu_item_disabled_bg=disabled_bg,
        menu_item_disabled_border=disabled_border,
        menu_separator=_rgb_to_hex(_tone(window_rgb, 0.12 if not is_dark_window else -0.22)),
        menu_item_text=text_primary,
        menu_item_selected_text=menu_item_selected_text,
        focus_ring=input_focus,
        dialog_bg=panel_bg,
        dialog_label_text=text_primary,
        splitter_handle_bg=_rgb_to_hex(_tone(window_rgb, 0.12 if not is_dark_window else -0.20)),
        statusbar_bg=panel_bg,
        statusbar_border=_rgb_to_hex(_tone(window_rgb, 0.12 if not is_dark_window else -0.20)),
        statusbar_text=text_secondary,
        label_text=text_primary,
        scrollbar_track=scrollbar_track,
        scrollbar_handle=scrollbar_handle,
        scrollbar_handle_hover=scrollbar_handle_hover,
        scrollbar_handle_pressed=scrollbar_handle_pressed,
        base_font_size=font_size,
        show_scrollbar=show_scrollbar,
        is_dark=is_dark_window,
        note_badge_bg_alpha=34,
        note_badge_radius=6,
    )


def default_light_business_theme() -> ThemeTokens:
    # Backward-compatible alias.
    return build_theme_tokens_from_appearance(default_appearance_settings())


def build_theme_tokens(_theme_mode: str = "") -> ThemeTokens:
    # Backward-compatible alias. Theme mode has been replaced by DIY appearance.
    return build_theme_tokens_from_appearance(default_appearance_settings())


def build_app_stylesheet(tokens: ThemeTokens) -> str:
    scroll_v_size = "8px" if tokens.show_scrollbar else "0px"
    scroll_h_size = "8px" if tokens.show_scrollbar else "0px"
    handle_v_min = "32px" if tokens.show_scrollbar else "0px"
    handle_h_min = "32px" if tokens.show_scrollbar else "0px"
    if tokens.is_dark:
        accent_bg = "#2f7fb8"
        accent_hover_bg = "#3a8ec7"
        accent_pressed_bg = "#2a6f9f"
        accent_border = "#3f92c9"
        left_panel_bg = tokens.panel_bg
        tab_hover_bg = "rgba(255, 255, 255, 26)"
        tab_selected_bg = tokens.item_selected_bg
        tab_selected_border = tokens.item_selected_border
        nav_bg = tokens.panel_bg
        nav_hover_bg = "rgba(255, 255, 255, 22)"
        row_bg = tokens.item_bg
        row_border = tokens.item_border
        footer_bg = tokens.panel_bg
    else:
        accent_bg = "#2f7cd6"
        accent_hover_bg = "#3a88e0"
        accent_pressed_bg = "#2a6cbb"
        accent_border = "#2b71c4"
        left_panel_bg = "#fbfcfe"
        tab_hover_bg = "rgba(15, 23, 42, 14)"
        tab_selected_bg = "#e8f1fd"
        tab_selected_border = "#b6d4f5"
        nav_bg = "#f3f5f8"
        nav_hover_bg = "rgba(15, 23, 42, 12)"
        row_bg = "#ffffff"
        row_border = "#e6eaf0"
        footer_bg = "#f7f9fb"
    return f"""
        QMainWindow {{
            background: {tokens.main_window_bg};
        }}
        QWidget#rootGlass {{
            background: {tokens.window_start};
        }}
        QWidget {{
            background: transparent;
            color: {tokens.text_primary};
            font-size: {tokens.base_font_size}px;
        }}
        QDialog, QMessageBox, QInputDialog {{
            background: {tokens.dialog_bg};
            color: {tokens.text_primary};
            border: 1px solid {tokens.panel_border};
        }}
        QDialog QLabel, QMessageBox QLabel, QInputDialog QLabel {{
            background: transparent;
            color: {tokens.dialog_label_text};
        }}
        QDialog QTextEdit,
        QDialog QListWidget,
        QDialog QLineEdit,
        QDialog QKeySequenceEdit,
        QDialog QComboBox {{
            background: {tokens.input_bg};
            border: 1px solid {tokens.input_border};
            border-radius: 6px;
            color: {tokens.text_primary};
            selection-background-color: {tokens.input_selection_bg};
            selection-color: {tokens.input_selection_text};
        }}
        QDialog QTextEdit:focus,
        QDialog QLineEdit:focus,
        QDialog QKeySequenceEdit:focus,
        QDialog QComboBox:focus {{
            border: 1px solid {tokens.input_focus_border};
        }}
        QComboBox {{
            background: {tokens.input_bg};
            border: 1px solid {tokens.input_border};
            border-radius: 6px;
            color: {tokens.text_primary};
            padding: 4px 26px 4px 8px;
            min-height: 22px;
        }}
        QComboBox:hover {{
            background: {tokens.input_bg};
            border-color: {tokens.item_hover_border};
        }}
        QComboBox:on {{
            background: {tokens.item_selected_bg};
            border-color: {tokens.input_focus_border};
            color: {tokens.item_selected_text};
        }}
        QComboBox::drop-down {{
            subcontrol-origin: padding;
            subcontrol-position: top right;
            width: 20px;
            border-left: 1px solid {tokens.input_border};
            background: {tokens.input_bg};
            border-top-right-radius: 5px;
            border-bottom-right-radius: 5px;
        }}
        QComboBox QAbstractItemView {{
            background: {tokens.menu_bg};
            color: {tokens.text_primary};
            border: 1px solid {tokens.menu_border};
            border-radius: 6px;
            padding: 3px;
            outline: 0;
            selection-background-color: {tokens.menu_item_selected_bg};
            selection-color: {tokens.menu_item_selected_text};
        }}
        QComboBox QAbstractItemView::item {{
            min-height: 20px;
            padding: 5px 7px;
            margin: 1px 0;
            border-radius: 8px;
            background: {tokens.menu_item_bg};
            color: {tokens.menu_item_text};
        }}
        QComboBox QAbstractItemView::item:hover {{
            background: {tokens.menu_item_selected_bg};
            border: 1px solid {tokens.menu_item_selected_border};
            color: {tokens.menu_item_selected_text};
        }}
        QComboBox QAbstractItemView::item:selected {{
            background: {tokens.menu_item_selected_bg};
            border: 1px solid {tokens.menu_item_selected_border};
            color: {tokens.menu_item_selected_text};
        }}
        QWidget#leftPanel {{
            background: {left_panel_bg};
            border-right: 1px solid {tokens.panel_border};
            border-radius: 0px;
        }}
        QWidget#rightPanel {{
            background: transparent;
            border: none;
            border-radius: 0px;
        }}
        QListWidget, QTextEdit {{
            background: {tokens.input_bg};
            border: 1px solid {tokens.input_border};
            border-radius: 6px;
            padding: 3px;
        }}
        QListWidget:focus {{
            outline: none;
        }}
        QListWidget::item:focus {{
            outline: none;
        }}
        QListWidget::item {{
            margin: 1px 0;
            padding: 5px 7px;
            border-radius: 8px;
            background: {tokens.item_bg};
            border: 1px solid {tokens.item_border};
        }}
        QListWidget::item:hover {{
            background: {tokens.item_bg};
            border: 1px solid {tokens.item_hover_border};
        }}
        QListWidget::item:selected {{
            background: {tokens.item_selected_bg};
            color: {tokens.item_selected_text};
            border: 1px solid {tokens.item_selected_border};
        }}
        QAbstractItemView::item:selected {{
            background: {tokens.item_selected_bg};
            color: {tokens.item_selected_text};
            border: 1px solid {tokens.item_selected_border};
        }}
        QListWidget#tabList {{
            background: transparent;
            border: none;
            padding: 2px 8px 2px 2px;
            outline: none;
        }}
        QListWidget#tabList::item {{
            margin: 2px 6px 2px 0;
            padding: 8px 10px;
            min-height: 22px;
            border-radius: 6px;
            background: transparent;
            border: 1px solid transparent;
            color: {tokens.text_primary};
        }}
        QListWidget#tabList::item:hover {{
            background: {tab_hover_bg};
            border: 1px solid {tokens.item_hover_border};
        }}
        QListWidget#tabList::item:selected {{
            background: {tab_selected_bg};
            border: 1px solid {tab_selected_border};
            color: {tokens.text_primary};
        }}
        QListWidget#itemList {{
            background: transparent;
            border: none;
            padding: 10px 14px 14px 14px;
            outline: none;
        }}
        QListWidget#itemList::item {{
            margin: 6px 2px;
            padding: 0px;
            border-radius: 10px;
            background: transparent;
            border: none;
        }}
        QListWidget#itemList::item:hover,
        QListWidget#itemList::item:selected,
        QListWidget#itemList::item:focus {{
            background: transparent;
            border: none;
        }}
        QLineEdit, QTextEdit, QKeySequenceEdit {{
            background: {tokens.input_bg};
            color: {tokens.text_primary};
            border: 1px solid {tokens.input_border};
            border-radius: 6px;
            selection-background-color: {tokens.input_selection_bg};
            selection-color: {tokens.input_selection_text};
        }}
        QLineEdit:focus, QTextEdit:focus, QKeySequenceEdit:focus {{
            border: 1px solid {tokens.input_focus_border};
        }}
        QPushButton {{
            background: {tokens.secondary_button_bg};
            border: 1px solid {tokens.secondary_button_border};
            border-radius: 6px;
            padding: 6px 12px;
        }}
        QPushButton:hover {{
            background: {tokens.secondary_button_hover_bg};
            border-color: {tokens.secondary_button_hover_border};
        }}
        QPushButton:pressed {{
            background: {tokens.secondary_button_pressed_bg};
        }}
        QPushButton#primaryButton {{
            background: {accent_bg};
            color: #ffffff;
            border: 1px solid {accent_border};
            font-weight: 600;
            min-height: 32px;
            padding: 5px 15px;
        }}
        QPushButton#primaryButton:hover {{
            background: {accent_hover_bg};
        }}
        QPushButton#primaryButton:pressed {{
            background: {accent_pressed_bg};
        }}
        QLineEdit#globalSearchInput {{
            min-height: 34px;
            padding: 0 10px;
            border-radius: 6px;
        }}
        QToolButton {{
            background: {tokens.tool_button_bg};
            border: 1px solid {tokens.tool_button_border};
            border-radius: 6px;
            padding: 3px 6px;
        }}
        QToolButton:hover {{
            background: {tokens.tool_button_hover_bg};
            border-color: {tokens.tool_button_hover_border};
        }}
        QToolButton:pressed {{
            background: {tokens.tool_button_pressed_bg};
        }}
        QToolButton#settingsButton::menu-indicator {{
            width: 0px;
            image: none;
            subcontrol-origin: padding;
            subcontrol-position: top right;
        }}
        QLabel {{
            color: {tokens.label_text};
        }}
        QLabel#sidebarSectionLabel {{
            color: {tokens.text_secondary};
            font-size: {max(10, tokens.base_font_size - 2)}px;
            font-weight: 600;
            padding: 8px 2px 0px 2px;
        }}
        QLabel#subtleHint {{
            color: {tokens.text_secondary};
        }}
        QSplitter::handle {{
            background: transparent;
            width: 8px;
        }}
        QSplitter::handle:hover {{
            background: rgba(56, 167, 220, 36);
        }}
        QStatusBar {{
            background: {tokens.statusbar_bg};
            border-top: 1px solid {tokens.statusbar_border};
            color: {tokens.statusbar_text};
        }}

        QListWidget#settingsNav {{
            background: {nav_bg};
            border: none;
            border-right: 1px solid {tokens.panel_border};
            border-radius: 0px;
            padding: 10px 6px;
            outline: none;
        }}
        QListWidget#settingsNav::item {{
            padding: 7px 10px;
            margin: 1px 2px;
            border-radius: 5px;
            background: transparent;
            border: 1px solid transparent;
            color: {tokens.text_primary};
        }}
        QListWidget#settingsNav::item:hover {{
            background: {nav_hover_bg};
            border: 1px solid transparent;
        }}
        QListWidget#settingsNav::item:selected {{
            background: {tab_selected_bg};
            border: 1px solid {tab_selected_border};
            color: {tokens.text_primary};
        }}
        QStackedWidget#settingsPages, QScrollArea#settingsScroll {{
            background: {tokens.dialog_bg};
            border: none;
        }}
        QLabel#settingsPageTitle {{
            color: {tokens.text_primary};
            font-size: {tokens.base_font_size + 5}px;
            font-weight: 600;
            padding-bottom: 2px;
        }}
        QLabel#settingSectionTitle {{
            color: {tokens.text_secondary};
            font-size: {max(10, tokens.base_font_size - 1)}px;
            font-weight: 600;
            padding: 6px 2px 2px 2px;
        }}
        QFrame#settingRow {{
            background: {row_bg};
            border: 1px solid {row_border};
            border-radius: 6px;
        }}
        QLabel#settingRowTitle {{
            color: {tokens.text_primary};
        }}
        QLabel#settingRowDescription {{
            color: {tokens.text_secondary};
            font-size: {max(10, tokens.base_font_size - 2)}px;
        }}
        QWidget#settingsFooter {{
            background: {footer_bg};
            border-top: 1px solid {tokens.panel_border};
        }}
        QPushButton#colorPickButton {{
            text-align: left;
            padding: 5px 12px 5px 8px;
            min-width: 96px;
        }}

        QScrollBar:vertical {{
            background: {tokens.scrollbar_track};
            width: {scroll_v_size};
            margin: 4px 2px 4px 2px;
            border: none;
            border-radius: 4px;
        }}
        QScrollBar::handle:vertical {{
            background: {tokens.scrollbar_handle};
            min-height: {handle_v_min};
            border-radius: 4px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {tokens.scrollbar_handle_hover};
        }}
        QScrollBar::handle:vertical:pressed {{
            background: {tokens.scrollbar_handle_pressed};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
            background: transparent;
            border: none;
        }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            background: transparent;
        }}

        QScrollBar:horizontal {{
            background: {tokens.scrollbar_track};
            height: {scroll_h_size};
            margin: 2px 4px 2px 4px;
            border: none;
            border-radius: 4px;
        }}
        QScrollBar::handle:horizontal {{
            background: {tokens.scrollbar_handle};
            min-width: {handle_h_min};
            border-radius: 4px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background: {tokens.scrollbar_handle_hover};
        }}
        QScrollBar::handle:horizontal:pressed {{
            background: {tokens.scrollbar_handle_pressed};
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            width: 0px;
            background: transparent;
            border: none;
        }}
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
            background: transparent;
        }}
    """


def build_menu_stylesheet(tokens: ThemeTokens) -> str:
    return f"""
        QMenu#glassMenu {{
            background: {tokens.menu_bg};
            border: 1px solid {tokens.menu_border};
            border-radius: 8px;
            padding: 6px;
        }}
        QMenu#glassMenu::item {{
            margin: 1px 0;
            padding: 6px 10px;
            border-radius: 6px;
            color: {tokens.menu_item_text};
            background: {tokens.menu_item_bg};
            border: 1px solid {tokens.menu_item_border};
        }}
        QMenu#glassMenu::item:selected {{
            background: {tokens.menu_item_selected_bg};
            border: 1px solid {tokens.menu_item_selected_border};
            color: {tokens.menu_item_selected_text};
        }}
        QMenu#glassMenu::item:pressed {{
            background: {tokens.menu_item_pressed_bg};
            border: 1px solid {tokens.menu_item_pressed_border};
        }}
        QMenu#glassMenu::item:disabled {{
            color: {tokens.menu_item_disabled_text};
            background: {tokens.menu_item_disabled_bg};
            border: 1px solid {tokens.menu_item_disabled_border};
        }}
        QMenu#glassMenu::separator {{
            height: 1px;
            margin: 6px 8px;
            background: {tokens.menu_separator};
        }}
    """


def build_glass_menu_stylesheet(tokens: ThemeTokens) -> str:
    # Backward-compatible alias.
    return build_menu_stylesheet(tokens)
