from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class ItemPasteModeMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.instance() or QApplication([])

    def test_text_action_enabled_when_item_has_text(self) -> None:
        from PySide6.QtWidgets import QListWidgetItem, QMenu

        from clipboard_manager.ui.main_window import ITEM_TEXT_ROLE, MainWindow

        window = MainWindow()
        item = QListWidgetItem()
        item.setData(ITEM_TEXT_ROLE, "可粘贴文字")
        menu = QMenu()
        default_action, text_action = window._add_paste_mode_menu(menu, item, False)
        self.assertEqual(default_action.text(), "保留原格式")
        self.assertEqual(text_action.text(), "粘贴为纯文本")
        self.assertTrue(text_action.isEnabled())
        window.deleteLater()

    def test_text_action_disabled_without_text(self) -> None:
        from PySide6.QtWidgets import QListWidgetItem, QMenu

        from clipboard_manager.ui.main_window import ITEM_TEXT_ROLE, MainWindow

        window = MainWindow()
        item = QListWidgetItem()
        item.setData(ITEM_TEXT_ROLE, "")
        menu = QMenu()
        _, text_action = window._add_paste_mode_menu(menu, item, False)
        self.assertFalse(text_action.isEnabled())
        window.deleteLater()

    def test_shift_click_requests_text_paste(self) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication, QListWidgetItem

        from clipboard_manager.ui.main_window import (
            ITEM_ID_ROLE,
            ITEM_PINNED_ROLE,
            ITEM_TAB_ID_ROLE,
            ITEM_TEXT_ROLE,
            ITEM_TYPE_ROLE,
            MainWindow,
        )

        app = QApplication.instance() or QApplication([])
        window = MainWindow()
        window.resize(980, 620)
        window.show()
        app.processEvents()

        tab = QListWidgetItem("标签")
        tab.setData(ITEM_ID_ROLE, 1)
        window.tab_list.addItem(tab)
        window.tab_list.setCurrentItem(tab)

        item = QListWidgetItem("HTML 条目")
        item.setData(ITEM_ID_ROLE, 5)
        item.setData(ITEM_TYPE_ROLE, "html")
        item.setData(ITEM_TEXT_ROLE, "纯文本内容")
        item.setData(ITEM_TAB_ID_ROLE, 1)
        item.setData(ITEM_PINNED_ROLE, False)
        window.item_list.addItem(item)
        app.processEvents()

        events: list[tuple[str, int]] = []
        window.item_activated.connect(lambda item_id: events.append(("default", item_id)))
        window.item_paste_text_requested.connect(
            lambda item_id: events.append(("text", item_id))
        )
        rect = window.item_list.visualItemRect(item)
        QTest.mouseClick(
            window.item_list.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.ShiftModifier,
            rect.center(),
        )
        app.processEvents()
        self.assertEqual(events, [("text", 5)])
        window.close()
        window.deleteLater()


class _FakeRepository:
    def __init__(self, payload: dict | None) -> None:
        self._payload = payload
        self.used_ids: list[int] = []

    def get_item_payload_typed(self, _item_id: int) -> dict | None:
        return self._payload

    def mark_item_used(self, item_id: int) -> None:
        self.used_ids.append(item_id)


class _FakePasteService:
    def __init__(self) -> None:
        self.texts: list[str] = []

    def paste_text(self, text: str, _target, hide_window=None) -> bool:
        self.texts.append(text)
        return True


class _FakeWindow:
    def __init__(self) -> None:
        self.errors: list[str] = []

    @staticmethod
    def hide() -> None:
        return

    def show_error(self, message: str) -> None:
        self.errors.append(message)


class ItemPasteTextControllerTests(unittest.TestCase):
    def test_plain_text_paste_uses_item_text_and_marks_used(self) -> None:
        from types import SimpleNamespace

        from clipboard_manager.controller import AppController

        controller = object.__new__(AppController)
        controller._repository = _FakeRepository(None)
        controller._repository.get_item = lambda _item_id: SimpleNamespace(
            plain_text="只粘贴文字",
            text="",
            content_type="html",
        )
        controller._paste_service = _FakePasteService()
        controller._window = _FakeWindow()
        controller._pending_focus_target = None
        controller._auto_hide_on_paste = False
        AppController._on_item_paste_text_requested(controller, 7)
        self.assertEqual(controller._paste_service.texts, ["只粘贴文字"])
        self.assertEqual(controller._repository.used_ids, [7])
        self.assertEqual(controller._window.errors, [])

    def test_plain_text_paste_reports_missing_text(self) -> None:
        from types import SimpleNamespace

        from clipboard_manager.controller import AppController

        controller = object.__new__(AppController)
        controller._repository = _FakeRepository(None)
        controller._repository.get_item = lambda _item_id: SimpleNamespace(
            plain_text="",
            text="",
            content_type="image",
        )
        controller._paste_service = _FakePasteService()
        controller._window = _FakeWindow()
        controller._pending_focus_target = None
        controller._auto_hide_on_paste = False
        AppController._on_item_paste_text_requested(controller, 8)
        self.assertEqual(controller._paste_service.texts, [])
        self.assertEqual(len(controller._window.errors), 1)


class ItemPlainTextResolutionTests(unittest.TestCase):
    @staticmethod
    def _resolve(initial_text: str, payload: dict | None) -> str:
        from clipboard_manager.controller import AppController

        controller = object.__new__(AppController)
        controller._repository = _FakeRepository(payload)
        return AppController._resolve_item_plain_text(controller, 1, initial_text)

    def test_initial_text_wins(self) -> None:
        self.assertEqual(self._resolve("直接文本", None), "直接文本")

    def test_payload_plain_text_used(self) -> None:
        self.assertEqual(
            self._resolve("", {"plain_text": "HTML 纯文本", "text": ""}),
            "HTML 纯文本",
        )

    def test_file_paths_joined(self) -> None:
        self.assertEqual(
            self._resolve(
                "",
                {
                    "plain_text": "",
                    "text": "",
                    "file_paths": ["C:\\a.txt", "C:\\b.txt"],
                },
            ),
            "C:\\a.txt\nC:\\b.txt",
        )

    def test_raw_text_part_used(self) -> None:
        self.assertEqual(
            self._resolve(
                "",
                {
                    "plain_text": "",
                    "text": "",
                    "file_paths": [],
                    "raw_parts": [
                        {"mime_type": "text/plain", "payload_blob": b"raw text"}
                    ],
                },
            ),
            "raw text",
        )

    def test_no_text_returns_empty(self) -> None:
        self.assertEqual(
            self._resolve(
                "",
                {"plain_text": "", "text": "", "file_paths": [], "raw_parts": []},
            ),
            "",
        )


if __name__ == "__main__":
    unittest.main()

