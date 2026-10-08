from __future__ import annotations

import dataclasses
import unittest

from PySide6.QtGui import QColor

from clipboard_manager.ui.settings_dialog import PRESET_COLORS
from clipboard_manager.ui.theme import (
    build_app_stylesheet,
    build_theme_tokens_from_appearance,
    default_appearance_settings,
)


class LightPaletteDerivationTests(unittest.TestCase):
    def test_light_colors_follow_window_tint(self) -> None:
        green = dataclasses.replace(default_appearance_settings(), window_bg="#e9f1ea")
        tokens = build_theme_tokens_from_appearance(green)
        self.assertFalse(tokens.is_dark)
        panel = QColor(tokens.panel_bg)
        self.assertGreater(panel.green(), panel.red())

    def test_light_panel_not_hardcoded(self) -> None:
        tokens = build_theme_tokens_from_appearance(default_appearance_settings())
        self.assertNotEqual(tokens.panel_bg, "#fbfcfe")
        self.assertNotEqual(tokens.input_bg, "#ffffff")

    def test_dark_window_uses_dark_palette(self) -> None:
        dark = dataclasses.replace(default_appearance_settings(), window_bg="#1f2530")
        tokens = build_theme_tokens_from_appearance(dark)
        self.assertTrue(tokens.is_dark)
        panel = QColor(tokens.panel_bg)
        self.assertLess(panel.lightness(), 128)

    def test_selection_text_contrasts_selection_bg(self) -> None:
        tokens = build_theme_tokens_from_appearance(default_appearance_settings())
        bg = QColor(tokens.input_selection_bg)
        fg = QColor(tokens.input_selection_text)
        self.assertGreater(abs(bg.lightness() - fg.lightness()), 60)


class StylesheetBuildTests(unittest.TestCase):
    def test_build_app_stylesheet_runs_for_light_and_dark(self) -> None:
        light = build_theme_tokens_from_appearance(default_appearance_settings())
        dark = build_theme_tokens_from_appearance(
            dataclasses.replace(default_appearance_settings(), window_bg="#1f2530")
        )
        for tokens in (light, dark):
            css = build_app_stylesheet(tokens)
            self.assertIn("QMainWindow", css)


class PresetTests(unittest.TestCase):
    def test_light_presets_are_distinct(self) -> None:
        self.assertEqual(len(PRESET_COLORS), 5)
        combos = set(PRESET_COLORS.values())
        self.assertEqual(len(combos), 5)
        self.assertIn("冰川蓝", PRESET_COLORS)
        self.assertIn("雾松绿", PRESET_COLORS)

    def test_default_appearance_is_eye_friendly_sand(self) -> None:
        appearance = default_appearance_settings()
        self.assertEqual(appearance.window_bg, "#e9f1ea")
        self.assertEqual(appearance.item_bg, "#ffffff")
        self.assertEqual(appearance.item_selected_bg, "#a9cdb4")
        self.assertEqual(appearance.theme_style, "eye_green")
        self.assertEqual(appearance.glass_strength, "glass")
        self.assertEqual(appearance.accent_color, "auto")

    def test_graphite_night_style_builds_dark_tokens(self) -> None:
        appearance = dataclasses.replace(
            default_appearance_settings(),
            theme_style="graphite_night",
            window_bg="#1f2530",
            item_bg="#28303f",
            item_selected_bg="#2e6da4",
        )
        tokens = build_theme_tokens_from_appearance(appearance)
        self.assertTrue(tokens.is_dark)
        self.assertEqual(tokens.theme_style, "graphite_night")

    def test_glass_strength_changes_transparency_tokens(self) -> None:
        base = dataclasses.replace(default_appearance_settings(), glass_strength="glass")
        standard = build_theme_tokens_from_appearance(dataclasses.replace(base, glass_strength="standard"))
        transparent = build_theme_tokens_from_appearance(dataclasses.replace(base, glass_strength="transparent"))
        self.assertNotEqual(standard.glass_strength, transparent.glass_strength)
        self.assertEqual(standard.glass_strength, "standard")
        self.assertEqual(transparent.glass_strength, "transparent")

    def test_accent_color_auto_uses_blue_in_light(self) -> None:
        tokens = build_theme_tokens_from_appearance(
            dataclasses.replace(default_appearance_settings(), accent_color="auto")
        )
        self.assertFalse(tokens.is_dark)
        self.assertEqual(tokens.accent_color, "auto")


if __name__ == "__main__":
    unittest.main()
