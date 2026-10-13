from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from clipboard_manager.ui.main_window import MainWindow


class PanelVisibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        QApplication.instance() or QApplication([])

    def test_panel_is_tool_window(self) -> None:
        window = MainWindow()
        self.assertTrue(bool(window.windowFlags() & Qt.WindowType.Tool))
        window.deleteLater()

    def test_should_hide_follows_panel_state(self) -> None:
        window = MainWindow()
        window.show()
        self.assertTrue(window.should_hide_on_hotkey())
        window.hide_panel()
        self.assertFalse(window.should_hide_on_hotkey())
        self.assertFalse(window._panel_visible)
        window.deleteLater()

    def test_hide_panel_bumps_foreground_generation(self) -> None:
        window = MainWindow()
        window.show()
        before = window._foreground_generation
        window.hide_panel()
        self.assertGreater(window._foreground_generation, before)
        window.deleteLater()

    def _armed_window(self) -> MainWindow:
        window = MainWindow()
        window.show()
        window._tray_icon = mock.MagicMock()
        window._tray_icon.isVisible.return_value = True
        window._auto_hide_suspend_count = 0
        window._allow_close = False
        return window

    def test_watch_hides_when_other_app_foreground(self) -> None:
        window = self._armed_window()
        window._panel_had_focus = True
        window._foreground_window_owner_is_self = lambda: False
        window._check_panel_foreground()
        self.assertFalse(window._panel_visible)
        window.deleteLater()

    def test_watch_ignores_self_foreground(self) -> None:
        window = self._armed_window()
        window._panel_had_focus = True
        window._foreground_window_owner_is_self = lambda: True
        window._check_panel_foreground()
        self.assertTrue(window._panel_visible)
        window.deleteLater()

    def test_watch_ignores_when_never_focused(self) -> None:
        window = self._armed_window()
        window._panel_had_focus = False
        window._foreground_window_owner_is_self = lambda: False
        window._check_panel_foreground()
        self.assertTrue(window._panel_visible)
        window.deleteLater()

    def test_watch_ignores_unknown_foreground(self) -> None:
        window = self._armed_window()
        window._panel_had_focus = True
        window._foreground_window_owner_is_self = lambda: None
        window._check_panel_foreground()
        self.assertTrue(window._panel_visible)
        window.deleteLater()


if __name__ == "__main__":
    unittest.main()
