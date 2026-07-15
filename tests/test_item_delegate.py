from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QApplication, QStyleOptionViewItem

from clipboard_manager.ui.item_delegate import ClipItemDelegate


class ItemDelegateTests(unittest.TestCase):
    def test_large_note_font_increases_card_height(self) -> None:
        app = QApplication.instance() or QApplication([])
        model = QStandardItemModel()
        item = QStandardItem("剪贴板内容")
        item.setData("备注", int(Qt.ItemDataRole.UserRole))
        item.setData(True, int(Qt.ItemDataRole.UserRole) + 1)
        model.appendRow(item)

        delegate = ClipItemDelegate(
            note_role=int(Qt.ItemDataRole.UserRole),
            content_role=int(Qt.ItemDataRole.UserRole) + 2,
            has_note_role=int(Qt.ItemDataRole.UserRole) + 1,
            secondary_role=int(Qt.ItemDataRole.UserRole) + 3,
            type_label_role=int(Qt.ItemDataRole.UserRole) + 4,
            pinned_role=int(Qt.ItemDataRole.UserRole) + 5,
            pinned_color="#1fb8cb",
            note_color="#1f2937",
            note_font_size=28,
        )
        option = QStyleOptionViewItem()
        option.font = app.font()

        self.assertGreaterEqual(delegate.sizeHint(option, model.index(0, 0)).height(), 93)
