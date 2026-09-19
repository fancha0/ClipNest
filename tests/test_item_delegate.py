from __future__ import annotations

import dataclasses
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QImage, QPainter, QPixmap, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QApplication, QStyleOptionViewItem

from clipboard_manager.ui.item_delegate import ClipItemDelegate
from clipboard_manager.ui.theme import default_light_business_theme

_NOTE_ROLE = int(Qt.ItemDataRole.UserRole)
_CONTENT_ROLE = _NOTE_ROLE + 2
_HAS_NOTE_ROLE = _NOTE_ROLE + 1
_SECONDARY_ROLE = _NOTE_ROLE + 3
_TYPE_LABEL_ROLE = _NOTE_ROLE + 4
_PINNED_ROLE = _NOTE_ROLE + 5
_TYPE_ROLE = _NOTE_ROLE + 6


def _make_delegate(tokens=None, show_number_hints: bool = True) -> ClipItemDelegate:
    return ClipItemDelegate(
        note_role=_NOTE_ROLE,
        content_role=_CONTENT_ROLE,
        has_note_role=_HAS_NOTE_ROLE,
        secondary_role=_SECONDARY_ROLE,
        type_label_role=_TYPE_LABEL_ROLE,
        pinned_role=_PINNED_ROLE,
        pinned_color="#1fb8cb",
        note_color="#1f2937",
        note_font_size=13,
        tokens=tokens,
        type_role=_TYPE_ROLE,
        show_number_hints=show_number_hints,
    )


def _make_model(type_label: str = "", content_type: str = "", row_count: int = 1) -> QStandardItemModel:
    model = QStandardItemModel()
    for row in range(row_count):
        item = QStandardItem(f"剪贴板内容 {row}")
        item.setData("备注", _NOTE_ROLE)
        item.setData(True, _HAS_NOTE_ROLE)
        item.setData("次要信息", _SECONDARY_ROLE)
        item.setData(type_label, _TYPE_LABEL_ROLE)
        item.setData(False, _PINNED_ROLE)
        item.setData(content_type, _TYPE_ROLE)
        model.appendRow(item)
    return model


def _render_row(delegate: ClipItemDelegate, model: QStandardItemModel, row: int = 0) -> QImage:
    app = QApplication.instance() or QApplication([])
    index = model.index(row, 0)
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 420, 96)
    option.font = app.font()
    option.decorationSize = QSize(18, 18)
    pixmap = QPixmap(option.rect.size())
    pixmap.fill(Qt.GlobalColor.white)
    painter = QPainter(pixmap)
    delegate.paint(painter, option, index)
    painter.end()
    return pixmap.toImage()


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


class TypeAccentTests(unittest.TestCase):
    def test_all_known_types_map_to_colors(self) -> None:
        delegate = _make_delegate()
        for content_type in (
            "text", "url", "image", "files", "html",
            "rich", "bundle", "raw_snapshot", "special",
        ):
            with self.subTest(content_type=content_type):
                self.assertIsNotNone(delegate._type_accent(content_type))

    def test_unknown_type_falls_back_to_neutral_pill(self) -> None:
        delegate = _make_delegate()
        self.assertIsNone(delegate._type_accent(""))
        self.assertIsNone(delegate._type_accent("weird_type"))

    def test_dark_mode_uses_dark_color_variant(self) -> None:
        delegate = _make_delegate()
        light = delegate._type_accent("url")
        dark_tokens = dataclasses.replace(default_light_business_theme(), is_dark=True)
        delegate.set_theme_tokens(dark_tokens)
        dark = delegate._type_accent("url")
        self.assertEqual(light.name().lower(), "#2f6fd6")
        self.assertEqual(dark.name().lower(), "#6da3f0")
        self.assertNotEqual(light, dark)


class RowNumberHintTests(unittest.TestCase):
    def test_hint_drawn_for_first_nine_rows_only(self) -> None:
        model = _make_model(row_count=11)
        delegate = _make_delegate(show_number_hints=True)
        plain = _make_delegate(show_number_hints=False)
        for row in range(9):
            with self.subTest(row=row):
                self.assertNotEqual(
                    _render_row(delegate, model, row),
                    _render_row(plain, model, row),
                )
        for row in (9, 10):
            with self.subTest(row=row):
                self.assertEqual(
                    _render_row(delegate, model, row),
                    _render_row(plain, model, row),
                )


class ColoredTypePillTests(unittest.TestCase):
    def test_accented_pill_differs_from_neutral_pill(self) -> None:
        model = _make_model(type_label="链接", content_type="url")
        neutral_model = _make_model(type_label="链接", content_type="")
        delegate = _make_delegate()
        self.assertNotEqual(
            _render_row(delegate, model),
            _render_row(delegate, neutral_model),
        )

    def test_render_does_not_crash_for_every_type(self) -> None:
        for content_type, label in (
            ("text", "文本"), ("url", "链接"), ("image", "图片"),
            ("files", "文件"), ("html", "富文本"), ("rich", "图文"),
            ("bundle", "复合"), ("raw_snapshot", "原格式"), ("special", "特殊"),
        ):
            with self.subTest(content_type=content_type):
                model = _make_model(type_label=label, content_type=content_type, row_count=10)
                delegate = _make_delegate()
                for row in range(10):
                    _render_row(delegate, model, row)
