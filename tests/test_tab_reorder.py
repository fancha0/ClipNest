from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import QApplication, QListWidgetItem

from clipboard_manager.ui.main_window import (
    ITEM_ID_ROLE,
    DragAutoScrollListWidget,
    MainWindow,
)


class TabReorderEmitTests(unittest.TestCase):
    @staticmethod
    def _make_window() -> MainWindow:
        app = QApplication.instance() or QApplication([])
        window = MainWindow()
        window.tab_list.clear()
        for tab_id in (11, 22, 33):
            item = QListWidgetItem(f"标签{tab_id}")
            item.setData(ITEM_ID_ROLE, tab_id)
            window.tab_list.addItem(item)
        return window

    def test_order_emit_sync_with_final_order(self) -> None:
        window = self._make_window()
        emitted: list[list[int]] = []
        window.tab_order_changed.connect(emitted.append)

        model = window.tab_list.model()
        model.moveRow(QModelIndex(), 0, QModelIndex(), 2)

        # Qt moveRow 语义：移动到原下标 2 的条目之前
        self.assertEqual(emitted, [[22, 11, 33]])

    def test_no_emit_while_suppressed(self) -> None:
        window = self._make_window()
        emitted: list[list[int]] = []
        window.tab_order_changed.connect(emitted.append)

        window._suppress_tab_reorder_emit = True
        window.tab_list.model().moveRow(QModelIndex(), 0, QModelIndex(), 2)
        self.assertEqual(emitted, [])


class ManualMoveTests(unittest.TestCase):
    @staticmethod
    def _make_widget() -> DragAutoScrollListWidget:
        app = QApplication.instance() or QApplication([])
        widget = DragAutoScrollListWidget()
        for index in range(6):
            widget.addItem(QListWidgetItem(f"项{index}"))
        return widget

    def test_move_row_never_loses_items(self) -> None:
        widget = self._make_widget()
        for from_row in range(widget.count()):
            for drop_row in range(widget.count() + 1):
                with self.subTest(from_row=from_row, drop_row=drop_row):
                    widget._move_row(from_row, drop_row)
                    self.assertEqual(widget.count(), 6)
        texts = {widget.item(row).text() for row in range(widget.count())}
        self.assertEqual(len(texts), 6)

    def test_adjacent_or_same_move_is_noop(self) -> None:
        widget = self._make_widget()
        before = [widget.item(row).text() for row in range(widget.count())]

        self.assertFalse(widget._move_row(1, 1))
        self.assertFalse(widget._move_row(1, 2))

        after = [widget.item(row).text() for row in range(widget.count())]
        self.assertEqual(after, before)

    def test_move_row_reorders_correctly(self) -> None:
        widget = self._make_widget()

        moved = widget._move_row(0, 3)

        self.assertTrue(moved)
        self.assertEqual(
            [widget.item(row).text() for row in range(3)],
            ["项1", "项2", "项0"],
        )


class TabOrderSaveTests(unittest.TestCase):
    @staticmethod
    def _make_controller():
        from clipboard_manager.controller import AppController
        from clipboard_manager.repository import ClipRepository

        tmp_dir = Path(tempfile.mkdtemp(prefix="clipnest-tabtest-"))
        repo = ClipRepository(tmp_dir / "test.db")
        window = mock.MagicMock()
        controller = AppController(
            repository=repo,
            window=window,
            clipboard_service=mock.MagicMock(),
            focus_service=mock.MagicMock(),
            hotkey_service=mock.MagicMock(),
            paste_service=mock.MagicMock(),
        )
        return controller, window, repo

    def test_success_persists_without_refreshing_ui(self) -> None:
        controller, window, repo = self._make_controller()
        original = [tab.id for tab in repo.list_tabs()]
        reordered = list(reversed(original))

        controller._on_tab_order_changed(reordered)

        window.set_tabs.assert_not_called()
        self.assertEqual([tab.id for tab in repo.list_tabs()], reordered)

    def test_failure_refreshes_ui_to_rollback(self) -> None:
        controller, window, repo = self._make_controller()

        controller._on_tab_order_changed([999999])

        window.set_tabs.assert_called_once()


if __name__ == "__main__":
    unittest.main()
