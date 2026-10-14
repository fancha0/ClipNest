from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class FeedbackWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.instance() or QApplication([])

    def test_message_dialog_builds(self) -> None:
        from clipboard_manager.ui.feedback import MessageDialog

        dialog = MessageDialog(None, "出错了", "测试消息", kind="error")
        self.assertEqual(dialog.windowTitle(), "出错了")
        dialog.deleteLater()

    def test_confirm_dialog_destructive_button(self) -> None:
        from clipboard_manager.ui.feedback import ConfirmDialog

        dialog = ConfirmDialog(
            None,
            "清空列表",
            "确认清空？",
            confirm_text="删除",
            destructive=True,
        )
        self.assertEqual(dialog.windowTitle(), "清空列表")
        dialog.deleteLater()

    def test_text_input_dialog_value(self) -> None:
        from clipboard_manager.ui.feedback import TextInputDialog

        dialog = TextInputDialog(None, "新增标签页", "标签页名称：", text="测试")
        self.assertEqual(dialog.value(), "测试")
        dialog.deleteLater()

    def test_note_edit_dialog_value_and_count(self) -> None:
        from clipboard_manager.ui.feedback import NoteEditDialog

        dialog = NoteEditDialog(None, "一段备注")
        self.assertEqual(dialog.value(), "一段备注")
        self.assertIn("4 个字符", dialog._count_label.text())
        dialog.deleteLater()

    def test_status_icon_renders(self) -> None:
        from clipboard_manager.ui.icons import (
            line_icon,
            menu_icon,
            status_icon,
        )

        for kind in ("success", "error", "warning", "info"):
            self.assertFalse(status_icon(kind).isNull())
        for kind in ("search", "add", "gear", "pin", "edit", "note", "move", "delete"):
            self.assertFalse(line_icon(kind).isNull())
        self.assertFalse(menu_icon("delete", is_dark=False, danger=True).isNull())

    def test_segmented_control_selection(self) -> None:
        from clipboard_manager.ui.settings_widgets import SegmentedControl

        control = SegmentedControl([("a", "A"), ("b", "B")])
        self.assertEqual(control.current_key(), "a")
        events: list[str] = []
        control.valueChanged.connect(events.append)
        control.set_current("b")
        self.assertEqual(control.current_key(), "b")

    def test_theme_style_selector(self) -> None:
        from clipboard_manager.ui.settings_widgets import ThemeStyleSelector

        selector = ThemeStyleSelector([("eye_green", "护眼豆沙"), ("graphite_night", "石墨夜")])
        self.assertEqual(selector.current_style(), "eye_green")
        selector.set_current("graphite_night")
        self.assertEqual(selector.current_style(), "graphite_night")

    def test_color_picker_dialog_default(self) -> None:
        from clipboard_manager.ui.settings_widgets import ColorPickerDialog

        dialog = ColorPickerDialog(None, "选择颜色", "#1677c8")
        self.assertEqual(dialog.selected_color(), "#1677c8")
        dialog._set_color("#ff0000")
        self.assertEqual(dialog.selected_color(), "#ff0000")
        dialog.deleteLater()

    def test_appearance_preview_set_colors(self) -> None:
        from clipboard_manager.ui.settings_widgets import AppearancePreview

        preview = AppearancePreview()
        preview.set_colors("#ffffff", "#f0f0f0", "#dddddd", "#123456")
        self.assertEqual(preview._window, "#ffffff")
        self.assertEqual(preview._accent, "#123456")

    def test_acrylic_tint_packing(self) -> None:
        from clipboard_manager.ui.window_effects import argb_tint

        self.assertEqual(argb_tint("#ffffff", 255), 0xFFFFFFFF)
        self.assertEqual(argb_tint("#0000ff", 0), 0x00FF0000)
        self.assertEqual(argb_tint("#0000ff", 128), 0x80FF0000)
        self.assertEqual(argb_tint("bad-value", 0), 0x00FEFAF6)



if __name__ == "__main__":
    unittest.main()
