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
