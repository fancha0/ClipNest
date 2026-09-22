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


if __name__ == "__main__":
    unittest.main()
