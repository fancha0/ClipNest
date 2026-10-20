from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from clipboard_manager.ui.main_window import MainWindow


def _update_info(version: str = "9.9.9") -> dict:
    return {
        "version": version,
        "body": "更新说明",
        "url": "https://example.com/ClipNest-Windows.zip",
        "size": 104857600,
        "sha256": "a" * 64,
    }


class UpdateButtonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        QApplication.instance() or QApplication([])

    def _make_window(self) -> MainWindow:
        window = MainWindow()

        def cleanup() -> None:
            dialog = window._update_dialog
            if dialog is not None:
                dialog.close()
                dialog.deleteLater()
            window.close()
            window.deleteLater()
            app = QApplication.instance()
            if app is not None:
                app.processEvents()

        self.addCleanup(cleanup)
        return window

    def test_available_shows_button_without_opening_dialog(self) -> None:
        window = self._make_window()
        window.show_update_available(_update_info())
        self.assertFalse(window.update_button.isHidden())
        self.assertEqual(window.update_button.text(), "更新")
        self.assertIn("9.9.9", window.update_button.toolTip())
        self.assertIsNone(window._update_dialog)

    def test_progress_and_ready_survive_dialog_close(self) -> None:
        window = self._make_window()
        info = _update_info()
        window.show_update_available(info)
        window._on_update_button_clicked()
        dialog = window._update_dialog
        self.assertIsNotNone(dialog)

        dialog.close()
        window.show_update_progress(50 * 1024 * 1024, 100 * 1024 * 1024)
        self.assertEqual(window.update_button.text(), "50%")

        window._on_update_button_clicked()
        self.assertIs(window._update_dialog, dialog)
        self.assertEqual(dialog._progress.value(), 50)

        window.show_update_ready("C:/tmp/ClipNest-Windows.zip", "9.9.9")
        self.assertEqual(window.update_button.text(), "安装")

        dialog.close()
        window._on_update_button_clicked()
        self.assertIs(window._update_dialog, dialog)
        self.assertEqual(dialog._action_btn.text(), "立即安装并重启")
        self.assertEqual(dialog._zip_path, "C:/tmp/ClipNest-Windows.zip")

    def test_download_failure_exposes_retry(self) -> None:
        window = self._make_window()
        window.show_update_available(_update_info())
        window.show_update_error("网络中断")
        self.assertEqual(window.update_button.text(), "重试")
        self.assertIn("网络中断", window.update_button.toolTip())

    def test_clear_update_hides_button(self) -> None:
        window = self._make_window()
        window.show_update_available(_update_info())
        window._on_update_button_clicked()
        window.clear_update_available()
        self.assertTrue(window.update_button.isHidden())
        self.assertIsNone(window._update_dialog)

    def test_checking_disables_update_button(self) -> None:
        window = self._make_window()
        window.show_update_available(_update_info())
        window.set_update_checking(True)
        self.assertFalse(window.update_button.isEnabled())
        window.set_update_checking(False)
        self.assertTrue(window.update_button.isEnabled())
