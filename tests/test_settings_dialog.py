from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QKeySequence

from clipboard_manager.services.hotkey_service import HotkeyService
from clipboard_manager.ui.settings_dialog import _to_qt_hotkey_text


class QtHotkeyTextTests(unittest.TestCase):
    def test_win_modifier_translated_to_meta(self) -> None:
        self.assertEqual(_to_qt_hotkey_text("Win+A"), "Meta+A")
        self.assertEqual(_to_qt_hotkey_text("Ctrl+Win+V"), "Ctrl+Meta+V")

    def test_other_modifiers_untouched(self) -> None:
        self.assertEqual(_to_qt_hotkey_text("Ctrl+Shift+V"), "Ctrl+Shift+V")
        self.assertEqual(_to_qt_hotkey_text(""), "")

    def test_win_hotkey_round_trips_through_qkeysequence(self) -> None:
        stored = "Win+A"
        sequence = QKeySequence(_to_qt_hotkey_text(stored))
        self.assertFalse(sequence.isEmpty())
        self.assertEqual(
            sequence.toString(QKeySequence.SequenceFormat.PortableText),
            "Meta+A",
        )
        normalized, error = HotkeyService.normalize_hotkey(
            sequence.toString(QKeySequence.SequenceFormat.PortableText)
        )
        self.assertIsNone(error)
        self.assertEqual(normalized, stored)


class SettingsDialogApplyTests(unittest.TestCase):
    @staticmethod
    def _make_dialog():
        from PySide6.QtWidgets import QApplication, QWidget

        from clipboard_manager.ui.settings_dialog import SettingsDialog
        from clipboard_manager.ui.theme import default_appearance_settings

        QApplication.instance() or QApplication([])
        parent = QWidget()
        dialog = SettingsDialog(
            parent,
            hotkey="Ctrl+Shift+V",
            capture_tab_id=None,
            capture_tab_max=200,
            autostart=False,
            appearance=default_appearance_settings(),
            theme_mode="follow_system",
            note_color="#1f2937",
            note_font_size=13,
            pinned_color="#1fb8cb",
            tabs=[],
        )
        dialog._test_parent = parent
        return dialog

    def test_apply_emits_payload_without_closing(self) -> None:
        dialog = self._make_dialog()
        received: list = []
        dialog.apply_requested.connect(received.append)
        dialog._on_apply_clicked()
        self.assertEqual(len(received), 1)
        payload = received[0]
        self.assertEqual(payload.hotkey, "Ctrl+Shift+V")
        self.assertFalse(payload.apply_only)

    def test_apply_feedback_sets_inline_label(self) -> None:
        dialog = self._make_dialog()
        dialog.set_apply_feedback("已应用")
        self.assertEqual(dialog.apply_status_label.text(), "已应用")

    def test_capture_enabled_defaults_true(self) -> None:
        dialog = self._make_dialog()
        self.assertTrue(dialog.result_payload().capture_enabled)

    def test_capture_enabled_toggle_reflected_in_payload(self) -> None:
        dialog = self._make_dialog()
        dialog.capture_enabled_chk.setChecked(False)
        self.assertFalse(dialog.result_payload().capture_enabled)

    def test_capture_toggle_hotkey_defaults_to_ctrl_shift_p(self) -> None:
        dialog = self._make_dialog()
        self.assertEqual(dialog.result_payload().capture_toggle_hotkey, "Ctrl+Shift+P")

    def test_backdrop_blur_default_true(self) -> None:
        dialog = self._make_dialog()
        self.assertTrue(dialog.result_payload().appearance.backdrop_blur)

    def test_backdrop_blur_toggle_reflected_in_payload(self) -> None:
        dialog = self._make_dialog()
        dialog.backdrop_blur_chk.setChecked(False)
        self.assertFalse(dialog.result_payload().appearance.backdrop_blur)

    def test_display_toggles_reflected_in_payload(self) -> None:
        dialog = self._make_dialog()
        dialog.show_scrollbar_chk.setChecked(False)
        dialog.antialias_chk.setChecked(False)
        appearance = dialog.result_payload().appearance
        self.assertFalse(appearance.show_scrollbar)
        self.assertFalse(appearance.item_antialias)

    def test_font_size_reflected_in_payload(self) -> None:
        dialog = self._make_dialog()
        dialog.font_size_spin.setValue(20)
        self.assertEqual(dialog.result_payload().appearance.font_size, 20)

    def test_data_stats_labels_update(self) -> None:
        dialog = self._make_dialog()
        dialog.set_data_stats({"tabs": 3, "items": 12, "images": 4, "db_bytes": 2048})
        self.assertEqual(dialog.data_tabs_label.text(), "3")
        self.assertEqual(dialog.data_items_label.text(), "12")
        self.assertEqual(dialog.data_images_label.text(), "4")
        self.assertIn("KB", dialog.data_size_label.text())

    def test_shortcut_overview_rows(self) -> None:
        dialog = self._make_dialog()
        rows = dict(dialog._shortcut_rows())
        self.assertIn("打开面板", rows)
        self.assertIn("搜索条目", rows)
        self.assertEqual(rows["搜索条目"], "Ctrl + F")

    def test_settings_search_filters_rows(self) -> None:
        from clipboard_manager.ui.settings_widgets import SettingRow

        dialog = self._make_dialog()
        dialog._apply_settings_filter("开机")
        rows = dialog.findChildren(SettingRow)
        matched = [row for row in rows if "开机" in row.search_text()]
        unmatched = [row for row in rows if "滚动条" in row.search_text()]
        self.assertTrue(matched)
        self.assertTrue(all(not row.isHidden() for row in matched))
        self.assertTrue(all(row.isHidden() for row in unmatched))
        dialog._apply_settings_filter("")
        self.assertTrue(all(not row.isHidden() for row in rows))

    def test_about_page_shows_versions(self) -> None:
        dialog = self._make_dialog()
        self.assertIn("当前版本 v", dialog.current_version_label.text())
        self.assertIn("未知", dialog.latest_version_label.text())

    def test_set_latest_version_reflects_result(self) -> None:
        dialog = self._make_dialog()
        dialog.set_latest_version("0.2.0", True)
        self.assertIn("v0.2.0", dialog.latest_version_label.text())
        self.assertIn("发现新版本", dialog.latest_version_label.text())
        dialog.set_latest_version("0.2.0", False)
        self.assertIn("已是最新", dialog.latest_version_label.text())

    def test_auto_check_update_round_trips_through_payload(self) -> None:
        dialog = self._make_dialog()
        self.assertTrue(dialog.result_payload().auto_check_update)
        dialog.auto_update_chk.setChecked(False)
        self.assertFalse(dialog.result_payload().auto_check_update)

    def test_shortcut_overview_updates_after_editing(self) -> None:
        dialog = self._make_dialog()
        dialog.hotkey_edit.setKeySequence(QKeySequence("Ctrl+Alt+K"))
        dialog.capture_toggle_hotkey_edit.setKeySequence(QKeySequence("Ctrl+Alt+P"))
        self.assertEqual(
            dialog._shortcut_value_labels["打开面板"].text(),
            "Ctrl+Alt+K",
        )
        self.assertEqual(
            dialog._shortcut_value_labels["暂停/恢复监听"].text(),
            "Ctrl+Alt+P",
        )

    def test_shortcut_overview_uses_two_column_grid(self) -> None:
        dialog = self._make_dialog()
        self.assertEqual(dialog._shortcut_grid._COLUMNS, 2)
        self.assertEqual(len(dialog._shortcut_grid._cells), 6)

    def test_shortcut_grid_filter_hides_non_matching_cells(self) -> None:
        dialog = self._make_dialog()
        grid = dialog._shortcut_grid
        self.assertTrue(grid.apply_filter("Enter"))
        visible = [cell for cell in grid._cells if not cell.isHidden()]
        self.assertEqual(len(visible), 1)
        self.assertIn("Enter", grid.value_labels["粘贴选中条目"].text())
        grid.apply_filter("")
        self.assertTrue(all(not cell.isHidden() for cell in grid._cells))

    def test_duplicate_hotkeys_show_inline_error_and_block_apply(self) -> None:
        dialog = self._make_dialog()
        dialog.hotkey_edit.setKeySequence(QKeySequence("Ctrl+Shift+P"))
        self.assertFalse(dialog._refresh_hotkey_validation(probe=False))
        self.assertIn("不能使用同一个快捷键", dialog.hotkey_validation_label.text())
        self.assertTrue(dialog.hotkey_edit.property("invalid"))
        self.assertTrue(dialog.capture_toggle_hotkey_edit.property("invalid"))
        received: list = []
        dialog.apply_requested.connect(received.append)
        dialog._on_apply_clicked()
        self.assertEqual(received, [])

    def test_invalid_hotkey_format_shows_inline_error(self) -> None:
        dialog = self._make_dialog()
        dialog.hotkey_edit.setKeySequence(QKeySequence("A"))
        self.assertFalse(dialog._refresh_hotkey_validation(probe=False))
        self.assertIn("快捷键无效", dialog.hotkey_validation_label.text())
        self.assertTrue(dialog.hotkey_edit.property("invalid"))

    def test_registration_failure_shows_inline_error(self) -> None:
        from unittest.mock import patch

        dialog = self._make_dialog()
        dialog.hotkey_edit.setKeySequence(QKeySequence("Ctrl+Alt+K"))
        with patch.object(
            HotkeyService,
            "validate_registration",
            return_value="被其他程序占用",
        ):
            self.assertFalse(dialog._refresh_hotkey_validation(probe=True))
        self.assertIn("注册失败", dialog.hotkey_validation_label.text())
        self.assertIn("被其他程序占用", dialog.hotkey_validation_label.text())
        self.assertTrue(dialog.hotkey_edit.property("invalid"))

    def test_valid_hotkey_clears_error_and_can_apply(self) -> None:
        from unittest.mock import patch

        dialog = self._make_dialog()
        dialog.hotkey_edit.setKeySequence(QKeySequence("Ctrl+Alt+K"))
        with patch.object(HotkeyService, "validate_registration", return_value=None):
            self.assertTrue(dialog._refresh_hotkey_validation(probe=True))
            received: list = []
            dialog.apply_requested.connect(received.append)
            dialog._on_apply_clicked()
        self.assertTrue(dialog.hotkey_validation_label.isHidden())
        self.assertFalse(dialog.hotkey_edit.property("invalid"))
        self.assertEqual(len(received), 1)

    def test_save_is_blocked_on_hotkey_conflict(self) -> None:
        dialog = self._make_dialog()
        dialog.hotkey_edit.setKeySequence(QKeySequence("Ctrl+Shift+P"))
        dialog._on_save_clicked()
        self.assertEqual(dialog.result(), 0)
        self.assertIn("不能使用同一个快捷键", dialog.hotkey_validation_label.text())

    def test_registration_validator_rejects_invalid_format(self) -> None:
        self.assertIsNotNone(HotkeyService.validate_registration("A"))


class SettingsDialogGlassTests(unittest.TestCase):
    def test_window_is_frameless_and_translucent(self) -> None:
        from PySide6.QtCore import Qt

        dialog = SettingsDialogApplyTests._make_dialog()
        self.assertTrue(
            bool(dialog.windowFlags() & Qt.WindowType.FramelessWindowHint)
        )
        self.assertTrue(
            dialog.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        )
        self.assertEqual(dialog.objectName(), "settingsDialog")

    def test_glass_layers_and_custom_titlebar_exist(self) -> None:
        from PySide6.QtWidgets import QWidget

        dialog = SettingsDialogApplyTests._make_dialog()
        glass_root = dialog.findChild(QWidget, "glassDialogRoot")
        self.assertIsNotNone(glass_root)
        self.assertIsNotNone(dialog._frosted_overlay)
        self.assertEqual(dialog._title_bar.objectName(), "titleBar")
        self.assertTrue(dialog._title_bar._collapse_btn.isHidden())

    def test_dialog_accepts_cancel_after_frameless_change(self) -> None:
        dialog = SettingsDialogApplyTests._make_dialog()
        dialog.reject()
        self.assertEqual(dialog.result(), 0)


class ToggleSwitchTests(unittest.TestCase):
    def test_toggle_state_and_signal(self) -> None:
        from PySide6.QtWidgets import QApplication

        from clipboard_manager.ui.settings_widgets import ToggleSwitch

        QApplication.instance() or QApplication([])
        switch = ToggleSwitch()
        self.assertFalse(switch.isChecked())
        received: list[bool] = []
        switch.toggled.connect(received.append)
        switch.setChecked(True)
        self.assertTrue(switch.isChecked())
        switch.setChecked(False)
        self.assertFalse(switch.isChecked())
        self.assertEqual(received, [True, False])

    def test_duplicate_set_checked_emits_no_signal(self) -> None:
        from PySide6.QtWidgets import QApplication

        from clipboard_manager.ui.settings_widgets import ToggleSwitch

        QApplication.instance() or QApplication([])
        switch = ToggleSwitch()
        received: list[bool] = []
        switch.toggled.connect(received.append)
        switch.setChecked(True)
        switch.setChecked(True)
        self.assertEqual(received, [True])


class SettingsSectionCardTests(unittest.TestCase):
    def test_rows_share_one_card_with_separators(self) -> None:
        from PySide6.QtWidgets import QApplication, QWidget

        from clipboard_manager.ui.settings_widgets import SettingRow, SettingsSection

        QApplication.instance() or QApplication([])
        section = SettingsSection("测试分组")
        section.add_row(SettingRow("选项 A", QWidget()))
        section.add_row(SettingRow("选项 B", QWidget()))
        separators = [
            child
            for child in section._card.children()
            if getattr(child, "objectName", lambda: "")() == "settingRowSeparator"
        ]
        self.assertEqual(section._row_count, 2)
        self.assertEqual(len(separators), 1)

    def test_nav_items_have_icons(self) -> None:
        dialog = SettingsDialogApplyTests._make_dialog()
        for i in range(dialog.nav_list.count()):
            with self.subTest(index=i):
                self.assertFalse(dialog.nav_list.item(i).icon().isNull())


if __name__ == "__main__":
    unittest.main()
