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

    def test_panel_is_frameless(self) -> None:
        window = MainWindow()
        self.assertTrue(bool(window.windowFlags() & Qt.WindowType.FramelessWindowHint))
        window.deleteLater()

    def test_resize_hit_zone_reaches_visible_glass_edge(self) -> None:
        from PySide6.QtCore import QPoint

        window = MainWindow()
        window.resize(800, 560)
        cases = {
            QPoint(8, 280): Qt.Edge.LeftEdge,
            QPoint(792, 280): Qt.Edge.RightEdge,
            QPoint(400, 8): Qt.Edge.TopEdge,
            QPoint(400, 552): Qt.Edge.BottomEdge,
            QPoint(8, 8): Qt.Edge.LeftEdge | Qt.Edge.TopEdge,
            QPoint(792, 552): Qt.Edge.RightEdge | Qt.Edge.BottomEdge,
            QPoint(400, 280): Qt.Edge(0),
        }
        for point, expected in cases.items():
            with self.subTest(point=point):
                self.assertEqual(window._edge_resize_edges(point), expected)
        window.deleteLater()

    def test_edge_drag_resizes_window(self) -> None:
        from PySide6.QtCore import QEvent, QPoint, QPointF
        from PySide6.QtGui import QMouseEvent

        app = QApplication.instance() or QApplication([])
        window = MainWindow()
        window.resize(800, 560)
        window.show()
        app.processEvents()
        target = window.centralWidget()
        start = window.mapToGlobal(QPoint(window.width() - 4, window.height() // 2))

        def send(event_type, global_pos, button, buttons) -> None:
            local = target.mapFromGlobal(global_pos)
            event = QMouseEvent(
                event_type,
                QPointF(local),
                QPointF(global_pos),
                button,
                buttons,
                Qt.KeyboardModifier.NoModifier,
            )
            app.sendEvent(target, event)
            app.processEvents()

        start_width = window.width()
        send(
            QEvent.Type.MouseButtonPress,
            start,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
        )
        send(
            QEvent.Type.MouseMove,
            start + QPoint(50, 0),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
        )
        send(
            QEvent.Type.MouseButtonRelease,
            start + QPoint(50, 0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
        )
        self.assertEqual(window.width(), start_width + 50)
        window.hide()
        window.deleteLater()

    def test_manual_resize_geometry_respects_edges_and_minimum(self) -> None:
        from PySide6.QtCore import QPoint, QRect

        window = MainWindow()
        window.setMinimumSize(500, 360)
        window._manual_resize_edges = Qt.Edge.RightEdge | Qt.Edge.BottomEdge
        window._manual_resize_start_geometry = QRect(100, 100, 800, 560)
        grown = window._manual_resize_geometry(QPoint(50, 30))
        self.assertEqual(grown, QRect(100, 100, 850, 590))

        window._manual_resize_edges = Qt.Edge.LeftEdge | Qt.Edge.TopEdge
        clamped = window._manual_resize_geometry(QPoint(1000, 1000))
        self.assertEqual(clamped.width(), 500)
        self.assertEqual(clamped.height(), 360)
        self.assertEqual(clamped.right(), 899)
        self.assertEqual(clamped.bottom(), 659)
        window.deleteLater()

    def test_titlebar_collapse_hides_panel(self) -> None:
        window = MainWindow()
        window.show()
        self.assertTrue(window.should_hide_on_hotkey())
        window._title_bar._collapse_btn.click()
        self.assertFalse(window._panel_visible)
        window.deleteLater()

    def test_capture_button_state_without_text_width_jump(self) -> None:
        window = MainWindow()
        window.set_capture_enabled(False)
        self.assertEqual(window.capture_toggle_btn.text(), "")
        self.assertTrue(window.capture_toggle_btn.property("paused"))
        self.assertTrue(window.capture_status_dot.property("paused"))
        window.set_capture_enabled(True)
        self.assertEqual(window.capture_toggle_btn.text(), "")
        self.assertFalse(window.capture_toggle_btn.property("paused"))
        self.assertFalse(window.capture_status_dot.property("paused"))
        self.assertEqual(window.capture_toggle_btn.size(), window.add_item_btn.size())
        window.deleteLater()

    def test_toolbar_utility_buttons_share_glass_group(self) -> None:
        window = MainWindow()
        group = window.toolbar_button_group
        self.assertEqual(group.objectName(), "toolbarButtonGroup")
        for button in (
            window.capture_toggle_btn,
            window.add_item_btn,
            window.settings_button,
        ):
            self.assertIs(button.parentWidget(), group)
            self.assertEqual(button.size().width(), button.size().height())
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
