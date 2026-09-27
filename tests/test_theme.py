from __future__ import annotations

import dataclasses
import unittest

from PySide6.QtGui import QColor

from clipboard_manager.ui.settings_dialog import PRESET_COLORS
from clipboard_manager.ui.theme import (
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


class PresetTests(unittest.TestCase):
    def test_five_distinct_presets(self) -> None:
        self.assertEqual(len(PRESET_COLORS), 5)
        combos = set(PRESET_COLORS.values())
        self.assertEqual(len(combos), 5)
        self.assertIn("石墨夜", PRESET_COLORS)

    def test_dark_preset_window_is_dark(self) -> None:
        window_bg, _item_bg, _selected = PRESET_COLORS["石墨夜"]
        self.assertLess(QColor(window_bg).lightness(), 128)


if __name__ == "__main__":
    unittest.main()
