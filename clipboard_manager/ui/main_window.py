from __future__ import annotations

import hashlib
import logging
import os
import re
import sys
import time
from dataclasses import replace
from typing import Any, Optional

from PySide6.QtCore import (
    QByteArray,
    QBuffer,
    QEvent,
    QFileInfo,
    QIODevice,
    QObject,
    QPoint,
    QRunnable,
    QSize,
    QThreadPool,
    QTimer,
    Qt,
    Signal,
    QUrl,
)
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QColor,
    QCursor,
    QDrag,
    QFont,
    QIcon,
    QImage,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
    QShowEvent,
    QShortcut,
    QTextDocument,
    QTextImageFormat,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QPushButton,
    QSplitter,
    QStyle,
    QSystemTrayIcon,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QFileIconProvider,
)

from ..models import ClipItem, Tab
from ..config import APP_NAME, MAX_ITEMS_PER_TAB
from ..icon_utils import resolve_app_icon
from ..services.update_service import is_frozen
from .settings_dialog import SettingsDialog
from .update_dialog import UpdateDialog
from .dialog_base import ResizableDialog, set_dialog_titlebar_theme
from .image_mixin import ImageMimeMixin
from .image_codec import encode_qimage_to_payload
from .titlebar_theme import apply_titlebar_theme, set_round_corners
from .item_presenter import present_item
from .item_delegate import ClipItemDelegate
from .frosted_overlay import FrostedOverlay
from .window_effects import apply_acrylic, argb_tint, disable_backdrop
from .title_bar import TitleBar
from .feedback import (
    ExportProgressDialog,
    MessageDialog,
    NoteEditDialog,
    ProgressDialog,
    TextInputDialog,
    show_confirm,
    show_toast,
)
from .icons import line_icon, menu_icon, resolved_line_icon
from .theme import (
    AppearanceSettings,
    ThemeTokens,
    build_app_stylesheet,
    build_menu_stylesheet,
    build_theme_tokens_from_appearance,
    default_appearance_settings,
)

ITEM_ID_ROLE = int(Qt.ItemDataRole.UserRole)
ITEM_TYPE_ROLE = ITEM_ID_ROLE + 1
ITEM_TEXT_ROLE = ITEM_ID_ROLE + 2
ITEM_NOTE_ROLE = ITEM_ID_ROLE + 3
ITEM_HAS_NOTE_ROLE = ITEM_ID_ROLE + 4
ITEM_NOTE_TEXT_ROLE = ITEM_ID_ROLE + 5
ITEM_CONTENT_TEXT_ROLE = ITEM_ID_ROLE + 6
ITEM_TAB_ID_ROLE = ITEM_ID_ROLE + 7
ITEM_SECONDARY_TEXT_ROLE = ITEM_ID_ROLE + 8
ITEM_TYPE_LABEL_ROLE = ITEM_ID_ROLE + 9
ITEM_PINNED_ROLE = ITEM_ID_ROLE + 10

logger = logging.getLogger(__name__)


class DragAutoScrollListWidget(QListWidget):
    """列表基类：手动实现内部拖拽排序。

    QListWidget 自带的拖放实现在"拖到相邻项上"等场景会弄丢条目，
    因此统一改用显式 takeItem/insertItem，绕开默认实现。
    """

    _AUTO_SCROLL_EDGE_PX = 56
    _AUTO_SCROLL_BASE_PX = 10
    _AUTO_SCROLL_MAX_PX = 28

    rows_manually_reordered = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._auto_scroll_direction = 0
        self._auto_scroll_pixels = 0
        self._auto_scroll_timer = QTimer(self)
        self._auto_scroll_timer.setInterval(16)
        self._auto_scroll_timer.timeout.connect(self._perform_drag_auto_scroll)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._reorder_enabled = True
        self._drag_source_id: Optional[int] = None
        self._drop_insert_row: Optional[int] = None
        self._last_drag_point: Optional[QPoint] = None
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(False)
        self.setDragDropOverwriteMode(False)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)

    def set_reorder_enabled(self, enabled: bool) -> None:
        self._reorder_enabled = bool(enabled)
        self.setDragEnabled(self._reorder_enabled)
        self.setAcceptDrops(self._reorder_enabled)
        self.setDropIndicatorShown(False)
        if not self._reorder_enabled:
            self._stop_drag_auto_scroll()
            self._clear_drop_indicator()

    def startDrag(self, supported_actions: Qt.DropAction) -> None:
        if not self._reorder_enabled:
            return
        source_row = self.currentRow()
        if source_row < 0 or source_row >= self.count():
            return
        indexes = self.selectedIndexes()
        if not indexes:
            return
        mime_data = self.model().mimeData(indexes)
        if mime_data is None:
            return
        self._drag_source_id = self.item(source_row).data(ITEM_ID_ROLE)
        # 不使用 QListWidget.startDrag：它在 MoveAction 拖拽结束后会按
        # 自身语义删除源行。这里完全自管，仅提供 CopyAction。
        drag = QDrag(self)
        drag.setMimeData(mime_data)
        rect = self.visualRect(indexes[0])
        if rect.isValid():
            drag.setPixmap(self.viewport().grab(rect))
        try:
            drag.exec(Qt.DropAction.CopyAction, Qt.DropAction.CopyAction)
        finally:
            self._stop_drag_auto_scroll()
            self._drag_source_id = None
            self._clear_drop_indicator()

    def dragEnterEvent(self, event) -> None:
        super().dragEnterEvent(event)
        # 基类对仅提供 CopyAction 的自拖拽会拒绝，这里统一放行。
        if event.source() is self and self._reorder_enabled:
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        # 先让基类计算落点指示器位置，再统一接受；
        # 顺序反过来会被基类按“条目不可放置”规则忽略掉。
        super().dragMoveEvent(event)
        if self._reorder_enabled and event.source() is self:
            self._update_drag_auto_scroll(event.position().toPoint().y())
            self._last_drag_point = event.position().toPoint()
            self._drop_insert_row = self._resolve_drop_row(event)
            self.viewport().update()
            event.acceptProposedAction()
        else:
            self._stop_drag_auto_scroll()
            self._clear_drop_indicator()

    def dragLeaveEvent(self, event) -> None:
        self._stop_drag_auto_scroll()
        self._clear_drop_indicator()
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        self._stop_drag_auto_scroll()
        if not self._reorder_enabled or event.source() is not self:
            self._clear_drop_indicator()
            return super().dropEvent(event)

        from_row = self._resolve_drag_source_row()
        drop_row = self._resolve_drop_row(event)
        self._clear_drop_indicator()
        if 0 <= from_row < self.count():
            if self._move_row(from_row, drop_row):
                self.rows_manually_reordered.emit()
        # 声明为 CopyAction 并自行完成移动：切断 Qt 对 MoveAction 的
        # “源端删除”语义，避免条目在拖拽收尾时被默认逻辑移除。
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()

    def _move_row(self, from_row: int, drop_row: int) -> bool:
        """手动完成移动；相邻或原地返回 False。模型操作显式可控，不会丢项。"""
        if not 0 <= from_row < self.count():
            return False
        drop_row = self._constrain_drop_row(from_row, drop_row)
        if drop_row < 0:
            drop_row = 0
        if drop_row > self.count():
            drop_row = self.count()
        if drop_row == from_row or drop_row == from_row + 1:
            return False
        moved_item = self.takeItem(from_row)
        if moved_item is None:
            return False
        if drop_row > from_row:
            drop_row -= 1
        drop_row = max(0, min(drop_row, self.count()))
        self.insertItem(drop_row, moved_item)
        self.setCurrentItem(moved_item)
        return True

    def _resolve_drop_row(self, event) -> int:
        return self._drop_row_for_point(event.position().toPoint())

    def _drop_row_for_point(self, point: QPoint) -> int:
        row = self._unconstrained_drop_row_for_point(point)
        return self._constrain_drop_row(self._resolve_drag_source_row(), row)

    def _resolve_drag_source_row(self) -> int:
        if self._drag_source_id is not None:
            for row in range(self.count()):
                if self.item(row).data(ITEM_ID_ROLE) == self._drag_source_id:
                    return row
            # The source may have been removed by capacity trimming during drag.
            return -1
        return self.currentRow()

    def _constrain_drop_row(self, from_row: int, drop_row: int) -> int:
        return drop_row

    def _unconstrained_drop_row_for_point(self, point: QPoint) -> int:
        if self.count() == 0:
            return 0
        target_item = self.itemAt(point)
        if target_item is not None:
            target_row = self.row(target_item)
            rect = self.visualItemRect(target_item)
            return target_row + 1 if point.y() >= rect.center().y() else target_row

        # In row spacing, use the next row's upper edge. Blank space after the
        # final row appends; blank space before the first row prepends.
        for row in range(self.count()):
            rect = self.visualItemRect(self.item(row))
            if rect.isValid() and point.y() < rect.center().y():
                return row
        return self.count()

    def _clear_drop_indicator(self) -> None:
        if self._drop_insert_row is None:
            return
        self._drop_insert_row = None
        self._last_drag_point = None
        self.viewport().update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        row = self._drop_insert_row
        if row is None or self.count() == 0:
            return

        if row >= self.count():
            item = self.item(self.count() - 1)
            rect = self.visualItemRect(item)
            y = rect.bottom()
        else:
            item = self.item(max(0, row))
            rect = self.visualItemRect(item)
            y = rect.top()
        if not rect.isValid() or y < 0 or y >= self.viewport().height():
            return

        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        left = max(4, rect.left() + 8)
        right = min(self.viewport().width() - 4, rect.right() - 8)
        if right > left:
            # 白色描边让黑色插入线在深色卡片上也保持清晰。
            outline = QPen(QColor(255, 255, 255, 220), 6)
            outline.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(outline)
            painter.drawLine(QPoint(left, y), QPoint(right, y))
            pen = QPen(QColor(16, 18, 22), 3)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(QPoint(left, y), QPoint(right, y))
        painter.end()

    def _update_drag_auto_scroll(self, y: int) -> None:
        viewport_h = max(1, self.viewport().height())
        edge = min(self._AUTO_SCROLL_EDGE_PX, max(1, viewport_h // 3))
        direction = 0
        distance = 0
        if y < edge:
            direction = -1
            distance = edge - max(0, y)
        elif y > viewport_h - edge:
            direction = 1
            distance = min(edge, y - (viewport_h - edge))

        if direction == 0:
            self._stop_drag_auto_scroll()
            return

        ratio = max(0.0, min(1.0, distance / float(edge)))
        pixels = round(
            self._AUTO_SCROLL_BASE_PX
            + (self._AUTO_SCROLL_MAX_PX - self._AUTO_SCROLL_BASE_PX) * ratio
        )
        self._auto_scroll_direction = direction
        self._auto_scroll_pixels = max(1, min(self._AUTO_SCROLL_MAX_PX, int(pixels)))
        if not self._auto_scroll_timer.isActive():
            self._auto_scroll_timer.start()

    def _perform_drag_auto_scroll(self) -> None:
        if self._auto_scroll_direction == 0:
            self._stop_drag_auto_scroll()
            return
        scrollbar = self.verticalScrollBar()
        if scrollbar is None:
            self._stop_drag_auto_scroll()
            return
        current = scrollbar.value()
        target = current + self._auto_scroll_direction * self._auto_scroll_pixels
        target = max(scrollbar.minimum(), min(scrollbar.maximum(), target))
        if target == current:
            self._stop_drag_auto_scroll()
            return
        scrollbar.setValue(target)
        if self._last_drag_point is not None:
            self._drop_insert_row = self._drop_row_for_point(self._last_drag_point)
        self.viewport().update()

    def _stop_drag_auto_scroll(self) -> None:
        self._auto_scroll_direction = 0
        self._auto_scroll_pixels = 0
        if self._auto_scroll_timer.isActive():
            self._auto_scroll_timer.stop()


class ReorderableItemListWidget(DragAutoScrollListWidget):
    items_reordered = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._empty_hint = ""
        self.rows_manually_reordered.connect(self.items_reordered.emit)

    def _constrain_drop_row(self, from_row: int, drop_row: int) -> int:
        if not 0 <= from_row < self.count():
            return drop_row
        pinned_count = 0
        while pinned_count < self.count() and self.item(pinned_count).data(ITEM_PINNED_ROLE):
            pinned_count += 1
        if self.item(from_row).data(ITEM_PINNED_ROLE):
            return max(0, min(drop_row, pinned_count))
        return max(pinned_count, min(drop_row, self.count()))

    def set_empty_hint(self, text: str) -> None:
        self._empty_hint = (text or "").strip()
        self.viewport().update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self.count() > 0 or not self._empty_hint:
            return
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        color = self.palette().color(self.foregroundRole())
        color.setAlpha(145)
        painter.setPen(color)
        text_rect = self.viewport().rect().adjusted(12, 12, -12, -12)
        painter.drawText(
            text_rect,
            int(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap),
            self._empty_hint,
        )
        painter.end()


class BundleImageInputList(ImageMimeMixin, QListWidget):
    images_received = Signal(object)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._empty_hint = "点击此区域后可粘贴图片（Ctrl+V / Cmd+V）\n也可拖拽本地图片文件到这里。"
        self.setAcceptDrops(True)
        self.setDragEnabled(False)
        self.setDropIndicatorShown(False)
        self.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setIconSize(QSize(132, 86))
        self.setSpacing(4)
        self.customContextMenuRequested.connect(self._open_context_menu)

    def set_empty_hint(self, text: str) -> None:
        self._empty_hint = (text or "").strip() or self._empty_hint
        self.viewport().update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self.count() > 0:
            return
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        color = self.palette().color(self.foregroundRole())
        color.setAlpha(145)
        painter.setPen(color)
        text_rect = self.viewport().rect().adjusted(10, 10, -10, -10)
        painter.drawText(
            text_rect,
            int(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap),
            self._empty_hint,
        )
        painter.end()

    def mousePressEvent(self, event) -> None:
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        key = event.key()
        modifiers = event.modifiers()
        is_shift_insert = (
            key == Qt.Key.Key_Insert
            and bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        )
        if event.matches(QKeySequence.StandardKey.Paste) or is_shift_insert:
            if self.paste_images_from_clipboard():
                event.accept()
                return
            logger.debug("[Hotkey] ignored paste event in image list (no panel action)")
        super().keyPressEvent(event)

    def dragEnterEvent(self, event) -> None:
        if self._mime_may_contain_images(event.mimeData()):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event) -> None:
        if self._mime_may_contain_images(event.mimeData()):
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event) -> None:
        if self._emit_images_from_mime_data(event.mimeData()):
            event.acceptProposedAction()
            return
        event.ignore()

    def _open_context_menu(self, pos) -> None:
        menu = QMenu(self)
        menu.setObjectName("glassMenu")
        paste_action = menu.addAction(line_icon("copy", "#4a5866"), "粘贴图片")
        selected = menu.exec(self.mapToGlobal(pos))
        if selected == paste_action:
            self.paste_images_from_clipboard()

    def paste_images_from_clipboard(self) -> bool:
        if self._emit_images_from_mime_data(QApplication.clipboard().mimeData()):
            return True
        MessageDialog(self, "提示", "剪贴板中没有可用图片。", kind="warning").exec()
        return False

    def _emit_images_from_mime_data(self, mime_data) -> bool:
        images = self._extract_images_from_mime_data(mime_data)
        if not images:
            return False
        self.images_received.emit(images)
        return True

    def _extract_images_from_mime_data(self, mime_data) -> list[dict[str, Any]]:
        if mime_data is None:
            return []
        images: list[dict[str, Any]] = []
        seen_hashes: set[str] = set()

        image = self._image_from_mime_data(mime_data)
        if image is not None:
            payload = self._image_to_payload(image)
            if payload is not None:
                digest = hashlib.sha256(payload["image_blob"]).hexdigest()
                seen_hashes.add(digest)
                images.append(payload)

        if not images and mime_data.hasUrls():
            for url in mime_data.urls():
                if not url.isLocalFile():
                    continue
                local_path = url.toLocalFile()
                if not local_path:
                    continue
                candidate = QImage(local_path)
                if candidate.isNull():
                    continue
                payload = self._image_to_payload(candidate)
                if payload is None:
                    continue
                digest = hashlib.sha256(payload["image_blob"]).hexdigest()
                if digest in seen_hashes:
                    continue
                seen_hashes.add(digest)
                images.append(payload)

        return images


def _create_search_icon() -> QIcon:
    pixmap = QPixmap(18, 18)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(QColor("#7A8699"))
    pen.setWidthF(1.6)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(4, 4, 8, 8)
    painter.drawLine(11.5, 11.5, 15.0, 15.0)
    painter.end()
    return QIcon(pixmap)


def _create_add_icon(color_hex: str = "#FFFFFF") -> QIcon:
    pixmap = QPixmap(18, 18)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(QColor(color_hex))
    pen.setWidthF(2.1)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.drawLine(9.0, 3.5, 9.0, 14.5)
    painter.drawLine(3.5, 9.0, 14.5, 9.0)
    painter.end()
    return QIcon(pixmap)


def _encode_qimage_to_payload(image: QImage, mime_type: str = "image/png") -> Optional[dict[str, Any]]:
    return encode_qimage_to_payload(image, mime_type)


class _ImageEncodeSignals(QObject):
    finished = Signal(str, object)


class _ImageEncodeTask(QRunnable):
    def __init__(
        self,
        image_name: str,
        image: QImage,
        mime_type: str,
        signals: _ImageEncodeSignals,
    ) -> None:
        super().__init__()
        self._image_name = image_name
        self._image = image.copy()
        self._mime_type = str(mime_type or "image/png")
        self._signals = signals

    def run(self) -> None:
        payload = _encode_qimage_to_payload(self._image, self._mime_type)
        self._signals.finished.emit(self._image_name, payload)


class MixedContentEdit(ImageMimeMixin, QTextEdit):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAcceptRichText(True)
        self.setAcceptDrops(True)
        self._image_counter = 0
        self._image_payloads: dict[str, dict[str, Any]] = {}
        self._thread_pool = QThreadPool.globalInstance()
        self._encode_signals = _ImageEncodeSignals(self)
        self._encode_signals.finished.connect(self._on_image_encoded)

    def set_initial_content(self, text: str, images: list[dict[str, Any]]) -> None:
        self.clear()
        self._image_counter = 0
        self._image_payloads.clear()
        cursor = self.textCursor()
        if (text or "").strip():
            cursor.insertText(text.strip())
        for idx, payload in enumerate(images or []):
            if idx == 0 and self.toPlainText().strip():
                cursor.insertBlock()
            elif idx > 0:
                cursor.insertBlock()
            self._insert_image_payload(payload, cursor=cursor, async_encode=False)
        self.setTextCursor(cursor)

    def set_segments(self, segments: list[dict[str, Any]]) -> None:
        self.clear()
        self._image_counter = 0
        self._image_payloads.clear()
        if not isinstance(segments, list):
            return
        cursor = self.textCursor()
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            seg_type = str(segment.get("type") or "").strip().lower()
            if seg_type == "text":
                text_value = str(segment.get("content") or "")
                if text_value:
                    cursor.insertText(text_value)
                continue
            if seg_type == "image":
                self._insert_image_payload(segment, cursor=cursor, async_encode=False)
        self.setTextCursor(cursor)

    def segments(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        doc = self.document()
        block = doc.begin()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                fragment = it.fragment()
                if fragment.isValid():
                    fmt = fragment.charFormat()
                    if fmt.isImageFormat():
                        image_fmt = fmt.toImageFormat()
                        image_name = image_fmt.name()
                        payload = self._image_payloads.get(image_name)
                        if payload is not None and self._ensure_payload_ready(image_name, payload):
                            result.append(
                                {
                                    "type": "image",
                                    "image_blob": bytes(payload.get("image_blob") or b""),
                                    "mime_type": str(payload.get("mime_type") or "image/png"),
                                    "width": int(payload.get("width") or 0),
                                    "height": int(payload.get("height") or 0),
                                }
                            )
                    else:
                        text_value = fragment.text()
                        if text_value:
                            result.append({"type": "text", "content": text_value})
                it += 1
            block = block.next()
            if block.isValid():
                result.append({"type": "text", "content": "\n"})

        merged: list[dict[str, Any]] = []
        for seg in result:
            if (
                merged
                and seg.get("type") == "text"
                and merged[-1].get("type") == "text"
            ):
                merged[-1]["content"] = str(merged[-1].get("content") or "") + str(seg.get("content") or "")
            else:
                merged.append(seg)

        cleaned: list[dict[str, Any]] = []
        for seg in merged:
            if seg.get("type") == "text":
                text_value = str(seg.get("content") or "")
                if text_value == "":
                    continue
                cleaned.append({"type": "text", "content": text_value})
                continue
            cleaned.append(seg)
        return cleaned

    def content_parts(self) -> tuple[str, list[dict[str, Any]]]:
        segs = self.segments()
        text = "".join(
            str(seg.get("content") or "")
            for seg in segs
            if seg.get("type") == "text"
        ).strip()
        images: list[dict[str, Any]] = []
        for seg in segs:
            if seg.get("type") != "image":
                continue
            images.append(
                {
                    "image_blob": bytes(seg.get("image_blob") or b""),
                    "mime_type": str(seg.get("mime_type") or "image/png"),
                    "width": int(seg.get("width") or 0),
                    "height": int(seg.get("height") or 0),
                }
            )
        return text, images

    def insertFromMimeData(self, source) -> None:
        logger.debug("[Hotkey] ignored paste event (content editor handles paste only)")
        images = self._extract_images_from_mime_data(source)
        text_value = str(source.text() or "")
        inserted = False
        cursor = self.textCursor()
        cursor.beginEditBlock()
        try:
            if text_value.strip() and self._should_insert_text(text_value, bool(images)):
                cursor.insertText(text_value)
                inserted = True

            if images:
                if inserted:
                    cursor.insertBlock()
                for idx, payload in enumerate(images):
                    if idx > 0:
                        cursor.insertBlock()
                    if self._insert_image_payload(payload, cursor=cursor, async_encode=True):
                        inserted = True
        finally:
            cursor.endEditBlock()
        self.setTextCursor(cursor)

        if inserted:
            return
        super().insertFromMimeData(source)

    def dragEnterEvent(self, event) -> None:
        if self._mime_may_contain_images(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if self._mime_may_contain_images(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        if self._mime_may_contain_images(event.mimeData()):
            self.insertFromMimeData(event.mimeData())
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    @staticmethod
    def _should_insert_text(text_value: str, has_images: bool) -> bool:
        if not has_images:
            return True
        lines = [line.strip() for line in text_value.splitlines() if line.strip()]
        if not lines:
            return False
        path_like = True
        for line in lines:
            lower = line.lower()
            if lower.startswith("file:///"):
                continue
            if re.match(r"^[a-zA-Z]:[\\/]", line):
                continue
            path_like = False
            break
        return not path_like

    def _insert_image_payload(
        self,
        payload: dict[str, Any],
        cursor=None,
        async_encode: bool = False,
    ) -> bool:
        image: Optional[QImage] = None
        image_blob: bytes = b""
        blob = payload.get("image_blob")
        if isinstance(blob, (bytes, bytearray)) and len(blob) > 0:
            image_blob = bytes(blob)
            loaded = QImage()
            if loaded.loadFromData(image_blob):
                image = loaded

        qimage = payload.get("qimage")
        if image is None and isinstance(qimage, QImage) and not qimage.isNull():
            image = qimage.copy()
        if image is None or image.isNull():
            return False

        self._image_counter += 1
        name = f"flux-image://{self._image_counter}"
        self.document().addResource(QTextDocument.ResourceType.ImageResource, QUrl(name), image)

        max_width = max(120, self.viewport().width() - 24)
        draw_w = max(1, image.width())
        draw_h = max(1, image.height())
        if draw_w > max_width:
            ratio = max_width / float(draw_w)
            draw_w = max(1, int(round(draw_w * ratio)))
            draw_h = max(1, int(round(draw_h * ratio)))

        fmt = QTextImageFormat()
        fmt.setName(name)
        fmt.setWidth(draw_w)
        fmt.setHeight(draw_h)
        active_cursor = cursor if cursor is not None else self.textCursor()
        active_cursor.insertImage(fmt)

        mime_type = str(payload.get("mime_type") or "image/png")
        width = int(payload.get("width") or image.width())
        height = int(payload.get("height") or image.height())
        if image_blob:
            status = "ready"
        else:
            status = "pending" if async_encode else "failed"

        self._image_payloads[name] = {
            "status": status,
            "qimage": image.copy(),
            "image_blob": image_blob,
            "mime_type": mime_type,
            "width": width,
            "height": height,
        }
        if async_encode and not image_blob:
            self._start_async_encode(name, image, mime_type)
        return True

    def _start_async_encode(self, image_name: str, image: QImage, mime_type: str) -> None:
        task = _ImageEncodeTask(image_name, image, mime_type, self._encode_signals)
        self._thread_pool.start(task)

    def _on_image_encoded(self, image_name: str, encoded_payload: object) -> None:
        payload = self._image_payloads.get(image_name)
        if payload is None:
            return
        if not isinstance(encoded_payload, dict):
            payload["status"] = "failed"
            return
        blob = encoded_payload.get("image_blob")
        if not isinstance(blob, (bytes, bytearray)) or len(blob) == 0:
            payload["status"] = "failed"
            return
        payload["status"] = "ready"
        payload["image_blob"] = bytes(blob)
        payload["mime_type"] = str(encoded_payload.get("mime_type") or payload.get("mime_type") or "image/png")
        payload["width"] = int(encoded_payload.get("width") or payload.get("width") or 0)
        payload["height"] = int(encoded_payload.get("height") or payload.get("height") or 0)

    def _ensure_payload_ready(self, image_name: str, payload: dict[str, Any]) -> bool:
        image_blob = payload.get("image_blob")
        if (
            payload.get("status") == "ready"
            and isinstance(image_blob, (bytes, bytearray))
            and len(image_blob) > 0
        ):
            return True
        qimage = payload.get("qimage")
        if isinstance(qimage, QImage) and not qimage.isNull():
            encoded = _encode_qimage_to_payload(qimage, str(payload.get("mime_type") or "image/png"))
            if encoded is not None:
                payload["status"] = "ready"
                payload["image_blob"] = bytes(encoded.get("image_blob") or b"")
                payload["mime_type"] = str(encoded.get("mime_type") or payload.get("mime_type") or "image/png")
                payload["width"] = int(encoded.get("width") or payload.get("width") or 0)
                payload["height"] = int(encoded.get("height") or payload.get("height") or 0)
                return True
        payload["status"] = "failed"
        logger.warning("MixedContentEdit image payload encode failed for %s", image_name)
        return False

    def _extract_images_from_mime_data(self, mime_data) -> list[dict[str, Any]]:
        if mime_data is None:
            return []
        images: list[dict[str, Any]] = []
        seen_fingerprints: set[str] = set()

        image = self._image_from_mime_data(mime_data)
        if image is not None:
            finger = self._image_fingerprint(image)
            if finger not in seen_fingerprints:
                seen_fingerprints.add(finger)
                images.append({"qimage": image, "mime_type": "image/png"})

        if not images and mime_data.hasUrls():
            for url in mime_data.urls():
                if not url.isLocalFile():
                    continue
                local_path = url.toLocalFile()
                if not local_path:
                    continue
                candidate = QImage(local_path)
                if candidate.isNull():
                    continue
                finger = self._image_fingerprint(candidate)
                if finger in seen_fingerprints:
                    continue
                seen_fingerprints.add(finger)
                images.append({"qimage": candidate, "mime_type": "image/png"})
        return images


class BundleItemDialog(ResizableDialog):
    _size_key = "bundle_item"
    _default_size = (760, 620)
    _min_size = (520, 460)

    def __init__(
        self,
        parent: QWidget,
        title: str,
        initial_text: str = "",
        initial_images: Optional[list[dict[str, Any]]] = None,
        initial_note: str = "",
        require_image: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self._images: list[dict[str, Any]] = list(initial_images or [])
        self._require_image = bool(require_image)
        self._note = (initial_note or "").strip()
        self._result_text = (initial_text or "").strip()
        self._result_images: list[dict[str, Any]] = list(initial_images or [])
        self._result_segments: list[dict[str, Any]] = []
        self._build_ui(initial_text)
        self._refresh_image_list()

    def _build_ui(self, initial_text: str) -> None:
        layout = self.content_layout
        layout.setContentsMargins(18, 14, 18, 16)
        layout.setSpacing(10)

        header = QLabel("输入文字、粘贴图片，或直接把图片拖到编辑区", self)
        header.setObjectName("settingRowDescription")
        layout.addWidget(header)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        paste_btn = QPushButton("粘贴内容", self)
        paste_btn.setToolTip("从系统剪贴板插入文字或图片（Ctrl+V）")
        paste_btn.clicked.connect(self.content_edit_paste)
        undo_btn = QPushButton("撤销", self)
        redo_btn = QPushButton("重做", self)
        undo_btn.clicked.connect(lambda: self.content_edit.undo())
        redo_btn.clicked.connect(lambda: self.content_edit.redo())
        toolbar.addWidget(paste_btn)
        toolbar.addWidget(undo_btn)
        toolbar.addWidget(redo_btn)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        self.content_edit = MixedContentEdit(self)
        self.content_edit.setMinimumHeight(280)
        self.content_edit.set_initial_content(initial_text, self._images)
        self.content_edit.textChanged.connect(self._update_content_stats)
        layout.addWidget(self.content_edit, 1)

        self.content_stats_label = QLabel("0 个字符 · 0 张图片", self)
        self.content_stats_label.setObjectName("settingRowDescription")
        layout.addWidget(self.content_stats_label)
        self.validation_label = QLabel("", self)
        self.validation_label.setObjectName("dialogErrorLabel")
        layout.addWidget(self.validation_label)
        self._update_content_stats()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setText("确定")
        cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_btn is not None:
            cancel_btn.setText("取消")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def content_edit_paste(self) -> None:
        self.content_edit.paste()

    def _update_content_stats(self) -> None:
        if not hasattr(self, "content_edit"):
            return
        text = self.content_edit.toPlainText()
        image_count = sum(1 for segment in self.content_edit.segments() if segment.get("type") == "image")
        self.content_stats_label.setText(f"{len(text)} 个字符 · {image_count} 张图片")

    def _refresh_image_list(self) -> None:
        # Reserved for compatibility; content now renders directly inside mixed editor.
        return

    def _on_accept(self) -> None:
        self._result_segments = self.content_edit.segments()
        self._result_text, self._result_images = self.content_edit.content_parts()
        text = self._result_text
        has_images = len(self._result_images) > 0
        if not has_images and text == "":
            self.validation_label.setText("请至少输入文字或添加一张图片。")
            return
        if self._require_image and not has_images:
            self.validation_label.setText("该条目至少保留一张图片。")
            return
        self.validation_label.clear()
        self.accept()

    def result_text(self) -> str:
        return self._result_text

    def result_images(self) -> list[dict[str, Any]]:
        return list(self._result_images)

    def result_segments(self) -> list[dict[str, Any]]:
        return list(self._result_segments)

    def result_note(self) -> str:
        return self._note


class EditItemDialog(ResizableDialog):
    _size_key = "edit_item"
    _default_size = (560, 480)
    _min_size = (420, 380)

    def __init__(
        self,
        parent: QWidget,
        item_type: str,
        initial_text: str = "",
        initial_note: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("编辑条目")
        self._item_type = item_type
        self._result_type = item_type
        self._image_bytes: bytes | None = None
        self._image_width = 0
        self._image_height = 0
        self._build_ui(initial_text, initial_note)

    def _build_ui(self, initial_text: str, initial_note: str) -> None:
        layout = self.content_layout
        layout.setContentsMargins(18, 14, 18, 16)
        layout.setSpacing(10)
        layout.addWidget(QLabel("内容："))

        self.text_edit = QTextEdit(self)
        self.text_edit.setPlainText(initial_text)
        layout.addWidget(self.text_edit, 1)

        self.image_info_label = QLabel("当前为文本模式。", self)
        self.image_info_label.setObjectName("subtleHint")
        layout.addWidget(self.image_info_label)

        layout.addWidget(QLabel("备注："))
        self.note_edit = QTextEdit(self)
        self.note_edit.setPlainText(initial_note)
        self.note_edit.setPlaceholderText("可选。仅用于展示，不会随点击粘贴输出。")
        self.note_edit.setFixedHeight(70)
        layout.addWidget(self.note_edit)

        actions = QHBoxLayout()
        self.use_image_btn = QPushButton("使用剪贴板图片", self)
        self.use_text_btn = QPushButton("切回文本", self)
        actions.addWidget(self.use_image_btn)
        actions.addWidget(self.use_text_btn)
        layout.addLayout(actions)

        self.use_image_btn.clicked.connect(self._load_image_from_clipboard)
        self.use_text_btn.clicked.connect(self._switch_to_text)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setText("确定")
        cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_btn is not None:
            cancel_btn.setText("取消")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if self._item_type == "image":
            self._result_type = "image"
            self.text_edit.setVisible(False)
            self.image_info_label.setText("当前为图片条目，可用剪贴板中的图片替换。")
            self.use_text_btn.setVisible(False)
        else:
            self._result_type = "text"

    def _load_image_from_clipboard(self) -> None:
        image = QApplication.clipboard().image()
        if image.isNull():
            MessageDialog(self, "提示", "剪贴板中没有图片。", kind="warning").exec()
            return
        data = QByteArray()
        buf = QBuffer(data)
        if not buf.open(QIODevice.OpenModeFlag.WriteOnly):
            MessageDialog(self, "提示", "读取剪贴板图片失败。", kind="warning").exec()
            return
        saved = image.save(buf, "PNG")
        buf.close()
        if not saved:
            MessageDialog(self, "提示", "转换剪贴板图片失败。", kind="warning").exec()
            return
        self._image_bytes = bytes(data)
        self._image_width = image.width()
        self._image_height = image.height()
        self._result_type = "image"
        self.text_edit.setVisible(False)
        self.image_info_label.setText(
            f"已载入剪贴板图片：{self._image_width}x{self._image_height}（PNG）"
        )
        self.use_text_btn.setVisible(self._item_type == "text")

    def _switch_to_text(self) -> None:
        if self._item_type != "text":
            return
        self._result_type = "text"
        self._image_bytes = None
        self._image_width = 0
        self._image_height = 0
        self.text_edit.setVisible(True)
        self.image_info_label.setText("当前为文本模式。")

    def _on_accept(self) -> None:
        if self._result_type == "image":
            if not self._image_bytes:
                MessageDialog(self, "提示", "请先从剪贴板载入图片。", kind="warning").exec()
                return
            self.accept()
            return
        if self.text_edit.toPlainText().strip() == "":
            MessageDialog(self, "提示", "文本内容不能为空。", kind="warning").exec()
            return
        self.accept()

    def result_type(self) -> str:
        return self._result_type

    def result_text(self) -> str:
        return self.text_edit.toPlainText()

    def result_image(self) -> tuple[bytes | None, int, int]:
        return self._image_bytes, self._image_width, self._image_height

    def result_note(self) -> str:
        return self.note_edit.toPlainText().strip()


class MultiSelectDialog(ResizableDialog):
    _size_key = "multi_select"
    _default_size = (460, 420)
    _min_size = (360, 300)

    def __init__(
        self,
        parent: QWidget,
        title: str,
        prompt: str,
        options: list[tuple[str, str]],
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self._bulk_check_update = False
        layout = self.content_layout
        layout.setContentsMargins(18, 14, 18, 16)
        layout.setSpacing(10)
        desc = QLabel(prompt, self)
        desc.setWordWrap(True)
        layout.addWidget(desc)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.select_all_btn = QPushButton("全选", self)
        self.select_all_btn.clicked.connect(self._toggle_select_all)
        actions.addWidget(self.select_all_btn)
        layout.addLayout(actions)

        self.option_list = QListWidget(self)
        self.option_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        for key, label in options:
            item = QListWidgetItem(label)
            item.setData(ITEM_ID_ROLE, key)
            item.setFlags(
                item.flags()
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            item.setCheckState(Qt.CheckState.Checked)
            self.option_list.addItem(item)
        self.option_list.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.option_list, 1)
        self._refresh_select_all_button_text()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setText("确定")
        cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_btn is not None:
            cancel_btn.setText("取消")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self) -> None:
        if not self.selected_keys():
            MessageDialog(self, "提示", "请至少选择一项。", kind="warning").exec()
            return
        self.accept()

    def _toggle_select_all(self) -> None:
        self._set_all_checked(not self._all_checked())

    def _set_all_checked(self, checked: bool) -> None:
        self._bulk_check_update = True
        try:
            check_state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
            for idx in range(self.option_list.count()):
                item = self.option_list.item(idx)
                if item is not None:
                    item.setCheckState(check_state)
        finally:
            self._bulk_check_update = False
        self._refresh_select_all_button_text()

    def _all_checked(self) -> bool:
        if self.option_list.count() == 0:
            return False
        for idx in range(self.option_list.count()):
            item = self.option_list.item(idx)
            if item is None or item.checkState() != Qt.CheckState.Checked:
                return False
        return True

    def _refresh_select_all_button_text(self) -> None:
        self.select_all_btn.setText("取消全选" if self._all_checked() else "全选")

    def _on_item_changed(self, _item: QListWidgetItem) -> None:
        if self._bulk_check_update:
            return
        self._refresh_select_all_button_text()

    def selected_keys(self) -> list[str]:
        result: list[str] = []
        for idx in range(self.option_list.count()):
            item = self.option_list.item(idx)
            if item.checkState() == Qt.CheckState.Checked:
                result.append(str(item.data(ITEM_ID_ROLE)))
        return result



class MainWindow(QMainWindow):
    tab_selected = Signal(int)
    tab_order_changed = Signal(list)
    create_tab_requested = Signal(str)
    rename_tab_requested = Signal(int, str)
    delete_tab_requested = Signal(int)
    add_item_requested = Signal(str)
    add_bundle_item_requested = Signal(str, object, str)
    add_mixed_item_requested = Signal(object, str)
    edit_item_requested = Signal(int, str, str)
    edit_item_image_requested = Signal(int, object, str, int, int, str)
    edit_bundle_requested = Signal(int)
    edit_note_requested = Signal(int, str)
    item_pin_change_requested = Signal(int, bool)
    delete_item_requested = Signal(int)
    clear_items_requested = Signal(int)
    item_activated = Signal(int)
    item_paste_text_requested = Signal(int)
    export_requested = Signal()
    import_requested = Signal()
    search_text_changed = Signal(str)
    splitter_sizes_changed = Signal(str)
    item_order_changed = Signal(list, int)
    move_items_requested = Signal(list, int)
    start_inline_edit_requested = Signal(int)
    save_inline_edit_requested = Signal(int, object)
    autostart_change_requested = Signal(bool)
    capture_enabled_changed = Signal(bool)
    clear_all_data_requested = Signal()
    vacuum_database_requested = Signal()
    window_shown = Signal()
    settings_save_requested = Signal(object)
    check_update_requested = Signal()
    update_download_requested = Signal(str, str, int, str)
    update_install_requested = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        # Tool window: no taskbar button, so the panel is accessed via the tray
        # icon or the global hotkey (matches a clipboard popup's role).
        self.setWindowFlag(Qt.WindowType.Tool, True)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.resize(980, 620)
        self._backdrop_blur_enabled = True
        self._last_backdrop_state: Optional[tuple] = None
        self._resize_cursor_shape = None
        self._last_app_stylesheet: Optional[str] = None
        self._last_app_font_point: Optional[int] = None
        self._backdrop_suspended = False
        self._drag_poll_timer = QTimer(self)
        self._drag_poll_timer.setInterval(100)
        self._drag_poll_timer.timeout.connect(self._poll_drag_end)
        self._resize_cursor_timer = QTimer(self)
        self._resize_cursor_timer.setInterval(80)
        self._resize_cursor_timer.timeout.connect(self._update_resize_cursor)
        self._apply_app_icon()
        self._panel_visible = False
        self._foreground_generation = 0
        self._panel_had_focus = False
        self._panel_watch_timer = QTimer(self)
        self._panel_watch_timer.setInterval(250)
        self._panel_watch_timer.timeout.connect(self._check_panel_foreground)
        self._hotkey_text = ""
        self._active_settings_dialog: Optional[SettingsDialog] = None
        self._update_dialog: Optional[UpdateDialog] = None
        self._update_dialog_version = ""
        self._latest_update_info: Optional[dict] = None
        self._update_state = "hidden"
        self._update_received = 0
        self._update_total = 0
        self._update_zip_path = ""
        self._update_error = ""
        self._update_checking = False
        self._auto_check_update = True
        self._diagnostic_logging = True
        self._capture_tab_text = "未设置"
        self._capture_tab_id: Optional[int] = None
        self._capture_tab_max: int = MAX_ITEMS_PER_TAB
        self._autostart_enabled = False
        self._capture_enabled = True
        self._capture_hotkey_hint = "Ctrl+Shift+P"
        self._capture_toggle_action: Optional[QAction] = None
        self._data_stats_provider = None
        self._vacuum_progress_dialog: Optional[ProgressDialog] = None
        self._note_text_color = "#1f2937"
        self._note_font_size = 13
        self._pinned_accent_color = "#1fb8cb"
        self._appearance: AppearanceSettings = default_appearance_settings()
        self._theme_tokens: ThemeTokens = build_theme_tokens_from_appearance(self._appearance)
        self._tabs_snapshot: list[Tab] = []
        self._allow_close = False
        self._tray_message_shown = False
        self._auto_hide_suspend_count = 0
        self._tray_icon: Optional[QSystemTrayIcon] = None
        self._tray_menu: Optional[QMenu] = None
        self._item_delegate: Optional[ClipItemDelegate] = None
        self._suppress_tab_reorder_emit = False
        self._suppress_item_reorder_emit = False
        self._item_list_search_mode = False
        self._last_selected_item_id: Optional[int] = None
        self._reorder_highlight_item_id: Optional[int] = None
        self._reorder_highlight_timer = QTimer(self)
        self._reorder_highlight_timer.setSingleShot(True)
        self._reorder_highlight_timer.setInterval(850)
        self._reorder_highlight_timer.timeout.connect(self._clear_item_reorder_highlight)
        self._item_render_generation = 0
        self._pending_render_items: list[ClipItem] = []
        self._pending_render_index = 0
        self._pending_render_search_mode = False
        self._pending_render_tab_name_map: dict[int, str] = {}
        self._pending_render_restore_id: Optional[int] = None
        self._pending_render_drag_enabled = True
        self._pending_render_file_icon_provider: Optional[QFileIconProvider] = None
        self._file_icon_provider = QFileIconProvider()
        self._pending_render_started_at = 0.0
        self._pending_render_first_batch_logged = False
        self._thumb_icon_cache: dict[str, QIcon] = {}
        self._item_render_timer = QTimer(self)
        self._item_render_timer.setSingleShot(True)
        self._item_render_timer.timeout.connect(self._render_next_item_batch)
        self._search_debounce_timer = QTimer(self)
        self._search_debounce_timer.setSingleShot(True)
        self._search_debounce_timer.setInterval(200)
        self._search_debounce_timer.timeout.connect(self._emit_search_text_changed)
        self._splitter_save_timer = QTimer(self)
        self._splitter_save_timer.setSingleShot(True)
        self._splitter_save_timer.setInterval(120)
        self._splitter_save_timer.timeout.connect(self._emit_splitter_sizes_changed)
        self._last_splitter_sizes_text: str = ""
        self._main_splitter: Optional[QSplitter] = None
        self._inline_edit_item_id: Optional[int] = None
        self._build_ui()
        self.statusBar().setVisible(False)
        self._setup_tray()

    def _apply_app_icon(self) -> None:
        app = QApplication.instance()
        icon = QIcon()
        if app is not None:
            icon = app.windowIcon()
        if icon.isNull():
            icon = resolve_app_icon(app)
        if icon.isNull():
            return
        self.setWindowIcon(icon)
        if app is not None:
            app.setWindowIcon(icon)

    def _build_ui(self) -> None:
        root = QWidget(self)
        root.setObjectName("rootGlass")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(0)

        icon_pixmap = self.windowIcon().pixmap(18, 18)
        self._title_bar = TitleBar(APP_NAME, icon_pixmap, root)
        self._title_bar.collapse_requested.connect(self._on_titlebar_collapse)
        self._title_bar.quit_requested.connect(self._quit_application)
        outer.addWidget(self._title_bar)

        self._main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._main_splitter.setChildrenCollapsible(True)
        self._main_splitter.setHandleWidth(2)
        self._main_splitter.splitterMoved.connect(self._on_main_splitter_moved)
        outer.addWidget(self._main_splitter)

        left = QWidget()
        left.setObjectName("leftPanel")
        left.setMinimumWidth(0)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(18, 14, 6, 14)
        left_layout.setSpacing(10)

        section_label = QLabel("标签页")
        section_label.setObjectName("sidebarSectionLabel")
        left_layout.addWidget(section_label)

        self.tab_list = DragAutoScrollListWidget()
        self.tab_list.setObjectName("tabList")
        self.tab_list.setMinimumWidth(0)
        self.tab_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tab_list.setDragEnabled(True)
        self.tab_list.setAcceptDrops(True)
        self.tab_list.setDropIndicatorShown(False)
        self.tab_list.setDragDropOverwriteMode(False)
        self.tab_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.tab_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.tab_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tab_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tab_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        left_layout.addWidget(self.tab_list, 1)
        self._main_splitter.addWidget(left)

        right = QWidget()
        right.setObjectName("rightPanel")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(6, 18, 20, 18)
        right_layout.setSpacing(12)

        tools = QHBoxLayout()
        tools.setSpacing(6)
        self.search_input = QLineEdit(self)
        self.search_input.setObjectName("globalSearchInput")
        self.search_input.setPlaceholderText("搜索全部条目...（Ctrl+F）")
        self.search_input.setClearButtonEnabled(True)
        search_icon_action = QAction(self)
        search_icon_action.setIcon(_create_search_icon())
        search_icon_action.setToolTip("搜索全部条目（Ctrl+F）")
        self.search_input.addAction(search_icon_action, QLineEdit.ActionPosition.LeadingPosition)
        self.search_input.setMinimumWidth(220)
        self.search_input.setMaximumWidth(360)
        self.update_button = QPushButton("更新")
        self.update_button.setObjectName("updateButton")
        self.update_button.setAccessibleName("软件更新")
        self.update_button.setFixedHeight(36)
        self.update_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_button.setToolTip("发现新版本时显示")
        self.update_button.clicked.connect(self._on_update_button_clicked)
        self.update_button.setVisible(False)

        self.toolbar_button_group = QWidget(self)
        self.toolbar_button_group.setObjectName("toolbarButtonGroup")
        self.toolbar_button_group.setFixedHeight(36)
        group_layout = QHBoxLayout(self.toolbar_button_group)
        group_layout.setContentsMargins(1, 1, 1, 1)
        group_layout.setSpacing(0)

        self.capture_toggle_btn = QToolButton(self.toolbar_button_group)
        self.capture_toggle_btn.setObjectName("captureToggleButton")
        self.capture_toggle_btn.setCheckable(True)
        self.capture_toggle_btn.setChecked(True)
        self.capture_toggle_btn.setFixedSize(QSize(34, 34))
        self.capture_toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.capture_toggle_btn.setAccessibleName("暂停剪贴板监听")

        self.capture_status_dot = QLabel(self.capture_toggle_btn)
        self.capture_status_dot.setObjectName("captureStatusDot")
        self.capture_status_dot.setFixedSize(6, 6)
        self.capture_status_dot.move(27, 3)
        self.capture_status_dot.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )

        self.add_item_btn = QToolButton(self.toolbar_button_group)
        self.add_item_btn.setObjectName("addItemButton")
        self.add_item_btn.setIcon(_create_add_icon())
        self.add_item_btn.setIconSize(QSize(18, 18))
        self.add_item_btn.setToolTip("新建条目（Ctrl+N）")
        self.add_item_btn.setFixedSize(QSize(34, 34))

        self.settings_button = QToolButton(self.toolbar_button_group)
        self.settings_button.setObjectName("settingsButton")
        self.settings_button.setIcon(resolved_line_icon("gear", False, 18))
        self.settings_button.setIconSize(QSize(18, 18))
        self.settings_button.setToolTip("设置")
        self.settings_button.setFixedSize(QSize(34, 34))

        group_layout.addWidget(self.capture_toggle_btn)
        separator_one = QFrame(self.toolbar_button_group)
        separator_one.setObjectName("toolbarButtonSeparator")
        separator_one.setFixedSize(1, 18)
        group_layout.addWidget(separator_one, 0, Qt.AlignmentFlag.AlignVCenter)
        group_layout.addWidget(self.add_item_btn)
        separator_two = QFrame(self.toolbar_button_group)
        separator_two.setObjectName("toolbarButtonSeparator")
        separator_two.setFixedSize(1, 18)
        group_layout.addWidget(separator_two, 0, Qt.AlignmentFlag.AlignVCenter)
        group_layout.addWidget(self.settings_button)

        tools.addWidget(self.search_input, 1)
        tools.addStretch(1)
        tools.addWidget(self.update_button)
        tools.addWidget(self.toolbar_button_group)
        right_layout.addLayout(tools)

        self.inline_editor_frame = QFrame(self)
        self.inline_editor_frame.setObjectName("inlineEditorFrame")
        inline_layout = QVBoxLayout(self.inline_editor_frame)
        inline_layout.setContentsMargins(6, 6, 6, 6)
        inline_layout.setSpacing(6)
        self.inline_editor = MixedContentEdit(self.inline_editor_frame)
        self.inline_editor.setMinimumHeight(210)
        inline_layout.addWidget(self.inline_editor)
        inline_actions = QHBoxLayout()
        inline_actions.addStretch(1)
        self.inline_save_btn = QPushButton("保存", self.inline_editor_frame)
        self.inline_cancel_btn = QPushButton("取消", self.inline_editor_frame)
        inline_actions.addWidget(self.inline_save_btn)
        inline_actions.addWidget(self.inline_cancel_btn)
        inline_layout.addLayout(inline_actions)
        self.inline_editor_frame.setVisible(False)
        right_layout.addWidget(self.inline_editor_frame)

        self.item_list = ReorderableItemListWidget()
        self.item_list.setObjectName("itemList")
        self.item_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.item_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.item_list.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.item_list.setStyleSheet(
            "QListWidget:focus { outline: none; }"
            "QListWidget::item:focus { outline: none; border: 1px solid transparent; }"
        )
        self.item_list.installEventFilter(self)
        self.item_list.viewport().installEventFilter(self)
        self._item_list_enter_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Return), self.item_list)
        self._item_list_enter_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._item_list_enter_shortcut.activated.connect(self._on_item_list_enter_pressed)
        self._item_list_numenter_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Enter), self.item_list)
        self._item_list_numenter_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._item_list_numenter_shortcut.activated.connect(self._on_item_list_enter_pressed)
        self.item_list.setIconSize(QSize(96, 64))
        self.item_list.setSpacing(4)
        self._item_delegate = ClipItemDelegate(
            note_role=ITEM_NOTE_TEXT_ROLE,
            content_role=ITEM_CONTENT_TEXT_ROLE,
            has_note_role=ITEM_HAS_NOTE_ROLE,
            secondary_role=ITEM_SECONDARY_TEXT_ROLE,
            type_label_role=ITEM_TYPE_LABEL_ROLE,
            pinned_role=ITEM_PINNED_ROLE,
            item_id_role=ITEM_ID_ROLE,
            pinned_color=self._pinned_accent_color,
            note_color=self._note_text_color,
            note_font_size=self._note_font_size,
            tokens=self._theme_tokens,
            type_role=ITEM_TYPE_ROLE,
            parent=self.item_list,
        )
        self._item_delegate.set_antialias_enabled(self._appearance.item_antialias)
        self.item_list.setItemDelegate(self._item_delegate)
        right_layout.addWidget(self.item_list, 1)

        self._main_splitter.addWidget(right)
        self._configure_main_splitter_collapsible()
        self._main_splitter.setSizes([240, 740])

        self.tab_list.currentItemChanged.connect(self._on_tab_changed)
        self.tab_list.model().rowsMoved.connect(self._on_tab_rows_moved)
        self.tab_list.rows_manually_reordered.connect(self._on_tab_rows_moved)
        self.tab_list.customContextMenuRequested.connect(self._open_tab_context_menu)
        self.add_item_btn.clicked.connect(self._prompt_add_item)
        self.capture_toggle_btn.toggled.connect(self._on_capture_toggle_button)
        self.search_input.textChanged.connect(self._on_search_input_changed)

        self._focus_search_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        self._focus_search_shortcut.activated.connect(self._focus_search_input)
        self._new_item_shortcut = QShortcut(QKeySequence("Ctrl+N"), self)
        self._new_item_shortcut.activated.connect(self._prompt_add_item)
        self.search_input.installEventFilter(self)
        self.item_list.itemClicked.connect(self._on_item_clicked)
        self.item_list.currentItemChanged.connect(self._on_item_current_changed)
        self.item_list.customContextMenuRequested.connect(self._open_item_context_menu)
        self.item_list.items_reordered.connect(self._on_item_rows_moved)
        self.inline_save_btn.clicked.connect(self._on_inline_edit_save_clicked)
        self.inline_cancel_btn.clicked.connect(self.hide_inline_editor)
        self._build_settings_menu()
        self._frosted_overlay = FrostedOverlay(root)
        self._frosted_overlay.setGeometry(root.rect())
        self._frosted_overlay.raise_()
        root.installEventFilter(self)
        self._apply_theme()

    def _build_settings_menu(self) -> None:
        self.settings_button.clicked.connect(self._open_settings_dialog)

    def set_autostart_state(self, enabled: bool) -> None:
        self._autostart_enabled = bool(enabled)

    def capture_enabled(self) -> bool:
        return bool(self._capture_enabled)

    def _capture_hotkey_text(self) -> str:
        return getattr(self, "_capture_hotkey_hint", "Ctrl+Shift+P")

    def set_capture_toggle_hotkey_text(self, hotkey_text: str) -> None:
        self._capture_hotkey_hint = str(hotkey_text or "Ctrl+Shift+P")
        self.set_capture_enabled(self._capture_enabled)

    def set_data_stats_provider(self, provider) -> None:
        self._data_stats_provider = provider

    def refresh_settings_data_stats(self) -> None:
        dialog = self._active_settings_dialog
        if dialog is None or self._data_stats_provider is None:
            return
        try:
            dialog.set_data_stats(self._data_stats_provider())
        except Exception:
            logger.debug("refresh settings data stats failed", exc_info=True)

    def set_capture_enabled(self, enabled: bool) -> None:
        self._capture_enabled = bool(enabled)
        self._refresh_capture_button()
        action = getattr(self, "_capture_toggle_action", None)
        if action is not None:
            action.blockSignals(True)
            action.setChecked(self._capture_enabled)
            action.blockSignals(False)
        tray = getattr(self, "_tray_icon", None)
        if tray is not None:
            tray.setToolTip(
                APP_NAME if self._capture_enabled else f"{APP_NAME}（剪贴板监听已暂停）"
            )

    def _refresh_capture_button(self) -> None:
        button = getattr(self, "capture_toggle_btn", None)
        if button is None:
            return
        enabled = bool(self._capture_enabled)
        dark = bool(getattr(self._theme_tokens, "is_dark", False))
        if enabled:
            color = "#cdd8e6" if dark else "#5a6a7e"
            icon = line_icon("capture_on", color, 18)
            accessible = "暂停剪贴板监听"
        else:
            color = "#e07a72" if dark else "#c2413d"
            icon = line_icon("capture_off", color, 18)
            accessible = "恢复剪贴板监听"
        button.blockSignals(True)
        button.setChecked(enabled)
        button.blockSignals(False)
        button.setIcon(icon)
        button.setIconSize(QSize(18, 18))
        button.setText("")
        button.setAccessibleName(accessible)
        dot = getattr(self, "capture_status_dot", None)
        if dot is not None:
            dot.setProperty("paused", not enabled)
            dot.style().unpolish(dot)
            dot.style().polish(dot)
        button.setToolTip(
            f"自动记录剪贴板：{'开（点击暂停）' if enabled else '关（点击开启）'}"
            f"　快捷键 {self._capture_hotkey_text()}"
        )
        button.setProperty("paused", not enabled)
        style = button.style()
        style.unpolish(button)
        style.polish(button)

    def _on_capture_toggle_button(self, checked: bool) -> None:
        self.set_capture_enabled(bool(checked))
        self.capture_enabled_changed.emit(bool(checked))

    def _on_capture_toggle_action(self, checked: bool) -> None:
        self.set_capture_enabled(bool(checked))
        self.capture_enabled_changed.emit(bool(checked))

    def _open_settings_dialog(self) -> None:
        dialog = SettingsDialog(
            self,
            hotkey=self._hotkey_text,
            capture_tab_id=self._capture_tab_id,
            capture_tab_max=self._capture_tab_max,
            autostart=self._autostart_enabled,
            appearance=self.user_appearance(),
            theme_mode=self.theme_mode(),
            note_color=self._note_text_color,
            note_font_size=self._note_font_size,
            pinned_color=self._pinned_accent_color,
            tabs=[(tab.id, tab.name) for tab in self._tabs_snapshot],
            auto_check_update=self._auto_check_update,
            diagnostic_logging=self._diagnostic_logging,
            capture_enabled=self._capture_enabled,
            capture_toggle_hotkey=self._capture_hotkey_text(),
            data_stats=(
                self._data_stats_provider() if self._data_stats_provider else None
            ),
        )
        self._active_settings_dialog = dialog
        dialog.set_update_checking(self._update_checking)
        dialog.apply_requested.connect(self._on_settings_apply_requested)
        dialog.check_update_requested.connect(self.check_update_requested.emit)
        dialog.clear_data_requested.connect(self.clear_all_data_requested.emit)
        dialog.vacuum_database_requested.connect(self.vacuum_database_requested.emit)
        try:
            accepted = self._exec_modal_dialog(dialog)
        finally:
            self._active_settings_dialog = None
        if accepted != QDialog.DialogCode.Accepted:
            return
        if dialog.export_requested():
            self.export_requested.emit()
            return
        if dialog.import_requested():
            self.import_requested.emit()
            return
        self.settings_save_requested.emit(dialog.result_payload())

    def _on_settings_apply_requested(self, payload) -> None:
        self.settings_save_requested.emit(replace(payload, apply_only=True))

    def show_settings_apply_result(self, messages: list[str]) -> None:
        dialog = self._active_settings_dialog
        if dialog is None:
            return
        text = "已应用" if not messages else "已应用：" + "；".join(messages)
        dialog.set_apply_feedback(text)

    def set_update_status(self, text: str) -> None:
        dialog = self._active_settings_dialog
        if dialog is not None:
            dialog.set_update_status(text)

    def set_update_checking(self, checking: bool) -> None:
        self._update_checking = bool(checking)
        dialog = self._active_settings_dialog
        if dialog is not None:
            dialog.set_update_checking(self._update_checking)
        self.update_button.setEnabled(not self._update_checking)

    def set_auto_check_update(self, enabled: bool) -> None:
        self._auto_check_update = bool(enabled)

    def notify_update_check_result(self, version: str, newer: bool) -> None:
        dialog = self._active_settings_dialog
        if dialog is not None:
            dialog.set_latest_version(version, newer)

    def show_update_available(self, info: dict) -> None:
        version = str(info.get("version") or "")
        previous_version = str((self._latest_update_info or {}).get("version") or "")
        changed = not previous_version or version != previous_version
        self._latest_update_info = dict(info)
        if changed:
            self._update_state = "available"
            self._update_received = 0
            self._update_total = 0
            self._update_zip_path = ""
            self._update_error = ""
            if self._update_dialog is not None:
                self._update_dialog.close()
                self._update_dialog.deleteLater()
                self._update_dialog = None
                self._update_dialog_version = ""
        elif self._update_state == "hidden":
            self._update_state = "available"
        self._refresh_update_button()
        if changed:
            self._show_update_notice(
                f"发现新版本 v{version}，可点击右上角更新按钮查看"
            )

    def _update_version(self) -> str:
        return str((self._latest_update_info or {}).get("version") or "")

    def _refresh_update_button(self) -> None:
        button = getattr(self, "update_button", None)
        if button is None:
            return
        state = self._update_state
        version = self._update_version()
        if state == "hidden":
            button.hide()
            return
        if state == "downloading":
            if self._update_total > 0:
                percent = min(
                    100, int(self._update_received * 100 / self._update_total)
                )
                text = f"{percent}%"
                tooltip = f"正在下载 v{version}：{percent}%"
            else:
                text = "下载"
                tooltip = f"正在下载 v{version}..."
        elif state == "ready":
            text = "安装"
            tooltip = f"v{version} 已下载，点击安装并重启"
        elif state == "error":
            text = "重试"
            tooltip = f"更新失败：{self._update_error or '未知错误'}\n点击重试"
        else:
            text = "更新"
            tooltip = f"发现新版本 v{version}，点击查看"
        button.setText(text)
        button.setToolTip(tooltip)
        button.setProperty("updateState", state)
        style = button.style()
        style.unpolish(button)
        style.polish(button)
        button.ensurePolished()
        metrics = button.fontMetrics()
        width = max(
            metrics.horizontalAdvance(label)
            for label in ("更新", "下载", "100%", "安装", "重试")
        )
        button.setFixedWidth(max(74, min(112, width + 28)))
        button.show()

    def _show_update_notice(self, message: str, kind: str = "info") -> None:
        if self.isVisible():
            show_toast(self, message, kind)
            return
        tray = getattr(self, "_tray_icon", None)
        if tray is not None and tray.isVisible():
            icon = (
                QSystemTrayIcon.MessageIcon.Warning
                if kind == "error"
                else QSystemTrayIcon.MessageIcon.Information
            )
            tray.showMessage(APP_NAME, message, icon, 3500)

    def _ensure_update_dialog(self) -> UpdateDialog:
        version = self._update_version()
        if (
            self._update_dialog is not None
            and self._update_dialog_version == version
        ):
            return self._update_dialog
        if self._update_dialog is not None:
            self._update_dialog.close()
            self._update_dialog.deleteLater()
        dialog = UpdateDialog(
            self, self._latest_update_info or {}, frozen=is_frozen()
        )
        dialog.download_requested.connect(self._on_update_download_started)
        dialog.install_requested.connect(self.update_install_requested.emit)
        self._update_dialog = dialog
        self._update_dialog_version = version
        return dialog

    def _sync_update_dialog_state(self, dialog: UpdateDialog) -> None:
        dialog.set_info(self._latest_update_info or {})
        if self._update_state == "downloading":
            dialog.set_downloading()
            if self._update_total > 0:
                dialog.set_progress(self._update_received, self._update_total)
        elif self._update_state == "ready":
            dialog.set_ready(self._update_zip_path, self._update_version())
        elif self._update_state == "error":
            dialog.set_failed(self._update_error)

    def _on_update_button_clicked(self) -> None:
        if self._latest_update_info is None:
            return
        dialog = self._ensure_update_dialog()
        self._sync_update_dialog_state(dialog)
        if dialog.isVisible():
            dialog.raise_()
            dialog.activateWindow()
            return
        dialog.open()

    def clear_update_available(self) -> None:
        self._latest_update_info = None
        self._update_state = "hidden"
        self._update_received = 0
        self._update_total = 0
        self._update_zip_path = ""
        self._update_error = ""
        if self._update_dialog is not None:
            self._update_dialog.close()
            self._update_dialog.deleteLater()
            self._update_dialog = None
            self._update_dialog_version = ""
        self._refresh_update_button()

    def _on_update_download_started(
        self, url: str, version: str, size: int, sha256: str
    ) -> None:
        self._update_state = "downloading"
        self._update_received = 0
        self._update_total = int(size or 0)
        self._update_error = ""
        self._refresh_update_button()
        self.update_download_requested.emit(url, version, size, sha256)

    def show_update_progress(self, received: int, total: int) -> None:
        self._update_state = "downloading"
        self._update_received = max(0, int(received))
        self._update_total = max(0, int(total))
        self._refresh_update_button()
        if self._update_dialog is not None:
            self._update_dialog.set_progress(self._update_received, self._update_total)

    def show_update_ready(self, zip_path: str, version: str) -> None:
        self._update_zip_path = zip_path
        self._update_state = "ready"
        self._update_error = ""
        self._refresh_update_button()
        if self._update_dialog is not None:
            self._update_dialog.set_ready(zip_path, version)
        if self._update_dialog is None or not self._update_dialog.isVisible():
            self._show_update_notice("更新包下载完成，点击右上角“安装”按钮")

    def show_update_error(self, message: str) -> None:
        self._update_state = "error"
        self._update_error = message
        self._refresh_update_button()
        if self._update_dialog is not None:
            self._update_dialog.set_failed(message)
            if self._update_dialog.isVisible():
                return
        self._show_update_notice("更新下载失败，点击右上角“重试”按钮", "error")

    def set_tabs(self, tabs: list[Tab], active_tab_id: Optional[int]) -> None:
        self._tabs_snapshot = list(tabs)
        if self._capture_tab_id not in {tab.id for tab in tabs}:
            self._capture_tab_id = None
        self._suppress_tab_reorder_emit = True
        self.tab_list.blockSignals(True)
        try:
            self.tab_list.clear()
            selected_row = 0
            for idx, tab in enumerate(tabs):
                item = QListWidgetItem(tab.name)
                item.setFlags(
                    item.flags()
                    | Qt.ItemFlag.ItemIsDragEnabled
                    | Qt.ItemFlag.ItemIsDropEnabled
                )
                item.setData(ITEM_ID_ROLE, tab.id)
                self.tab_list.addItem(item)
                if active_tab_id == tab.id:
                    selected_row = idx
            if self.tab_list.count() > 0:
                self.tab_list.setCurrentRow(selected_row)
        finally:
            self.tab_list.blockSignals(False)
            self._suppress_tab_reorder_emit = False
        current_id = self.current_tab_id()
        if current_id is not None:
            self.tab_selected.emit(current_id)

    def set_items(
        self,
        items: list[ClipItem],
        search_mode: bool = False,
        tab_name_map: Optional[dict[int, str]] = None,
    ) -> None:
        self._item_render_timer.stop()
        self._item_render_generation += 1
        self._item_list_search_mode = bool(search_mode)
        drag_enabled = not self._item_list_search_mode
        # 先暂停重绘，清空 + 首批 50 条画完再一次性上屏，避免闪烁
        self.item_list.setUpdatesEnabled(False)
        try:
            self.item_list.set_reorder_enabled(False if len(items) > 50 else drag_enabled)
            self._suppress_item_reorder_emit = True
            self.item_list.clear()
            query = self.search_input.text().strip()
            if search_mode and query:
                if items:
                    self.item_list.set_empty_hint("")
                    self.search_input.setPlaceholderText(f"搜索全部条目...（找到 {len(items)} 条，Ctrl+F 聚焦 / ESC 退出）")
                else:
                    self.item_list.set_empty_hint(f"没有找到匹配“{query}”的条目\n换个关键词试试")
                    self.search_input.setPlaceholderText("搜索全部条目...（无匹配结果，ESC 退出）")
            else:
                self.item_list.set_empty_hint("")
                self.search_input.setPlaceholderText("搜索全部条目...（Ctrl+F）")
            self._pending_render_items = list(items)
            self._pending_render_index = 0
            self._pending_render_search_mode = bool(search_mode)
            self._pending_render_tab_name_map = dict(tab_name_map or {})
            self._pending_render_restore_id = self._last_selected_item_id
            self._pending_render_drag_enabled = drag_enabled
            self._pending_render_file_icon_provider = self._file_icon_provider
            self._pending_render_started_at = time.perf_counter()
            self._pending_render_first_batch_logged = False
            try:
                self._append_item_batch(50)
            finally:
                if self._pending_render_index >= len(self._pending_render_items):
                    self._finish_item_render()
                else:
                    self._item_render_timer.start(1)
        finally:
            self.item_list.setUpdatesEnabled(True)

    def _render_next_item_batch(self) -> None:
        if not self._pending_render_items:
            self._finish_item_render()
            return
        self._append_item_batch(30)
        if self._pending_render_index >= len(self._pending_render_items):
            self._finish_item_render()
            return
        self._item_render_timer.start(1)

    def _append_item_batch(self, batch_size: int) -> None:
        end_index = min(
            len(self._pending_render_items),
            self._pending_render_index + max(1, int(batch_size)),
        )
        while self._pending_render_index < end_index:
            item = self._pending_render_items[self._pending_render_index]
            self._pending_render_index += 1
            lw_item = self._create_list_item(
                item,
                search_mode=self._pending_render_search_mode,
                tab_name_map=self._pending_render_tab_name_map,
                file_icon_provider=self._pending_render_file_icon_provider,
            )
            self.item_list.addItem(lw_item)
            if (
                self._pending_render_restore_id is not None
                and int(item.id) == int(self._pending_render_restore_id)
            ):
                self.item_list.setCurrentItem(lw_item)
                self.item_list.scrollToItem(
                    lw_item,
                    QAbstractItemView.ScrollHint.PositionAtCenter,
                )
        if not self._pending_render_first_batch_logged:
            elapsed_ms = (time.perf_counter() - self._pending_render_started_at) * 1000
            logger.debug(
                "[Perf] item_list first_batch rendered=%s total=%s search_mode=%s ms=%.1f",
                self._pending_render_index,
                len(self._pending_render_items),
                self._pending_render_search_mode,
                elapsed_ms,
            )
            self._pending_render_first_batch_logged = True

    def _finish_item_render(self) -> None:
        total = len(self._pending_render_items)
        elapsed_ms = (
            (time.perf_counter() - self._pending_render_started_at) * 1000
            if self._pending_render_started_at
            else 0.0
        )
        self._item_render_timer.stop()
        self._pending_render_items = []
        self._pending_render_index = 0
        self._pending_render_file_icon_provider = None
        self.item_list.set_reorder_enabled(self._pending_render_drag_enabled)
        self._suppress_item_reorder_emit = False
        logger.debug(
            "[Perf] item_list render_done total=%s search_mode=%s ms=%.1f",
            total,
            self._pending_render_search_mode,
            elapsed_ms,
        )

    @staticmethod
    def _thumb_cache_key(item_id: object, thumb_blob: bytes) -> str:
        # 用 id + 长度 + 头部字节做 key，比对整个 blob 算 sha256 便宜得多，
        # 且 item id 对应的缩略图被编辑更新时（长度/内容变了）仍然不会串
        return f"{item_id}:{len(thumb_blob)}:{thumb_blob[:12].hex()}"

    def _cached_thumb_icon(self, item: ClipItem) -> Optional[QIcon]:
        thumb_blob = item.thumb_blob
        if not thumb_blob:
            return None
        key = self._thumb_cache_key(item.id, thumb_blob)
        icon = self._thumb_icon_cache.get(key)
        if icon is not None:
            return icon
        pixmap = QPixmap()
        if not pixmap.loadFromData(thumb_blob, "PNG"):
            return None
        icon = QIcon(pixmap)
        if len(self._thumb_icon_cache) >= 512:
            # 只淘汰最旧的一批，避免整表清空导致下一轮全部重解码
            for stale_key in list(self._thumb_icon_cache)[:64]:
                self._thumb_icon_cache.pop(stale_key, None)
        self._thumb_icon_cache[key] = icon
        return icon

    def _create_list_item(
        self,
        item: ClipItem,
        search_mode: bool = False,
        tab_name_map: Optional[dict[int, str]] = None,
        file_icon_provider: Optional[QFileIconProvider] = None,
    ) -> QListWidgetItem:
        row = present_item(item)
        line_text = row.primary_text
        note_text = row.note_text
        content_text = row.content_text
        has_note = row.has_note
        if search_mode:
            tab_name = ((tab_name_map or {}).get(item.tab_id) or "").strip()
            prefix = f"【{tab_name}】" if tab_name else "【未知标签】"
            merged_text = f"{prefix}{line_text}" if line_text else prefix
            line_text = merged_text
            has_note = False
            note_text = ""
            content_text = merged_text

        lw_item = QListWidgetItem(line_text)
        if not search_mode:
            lw_item.setFlags(
                lw_item.flags()
                | Qt.ItemFlag.ItemIsDragEnabled
                | Qt.ItemFlag.ItemIsDropEnabled
            )
        lw_item.setToolTip(row.tooltip_text)
        row_height = 92 if (row.icon_kind == "image" and item.thumb_blob) else 76
        lw_item.setSizeHint(QSize(0, row_height))

        icon: QIcon | None = None
        if row.icon_kind == "image" and item.thumb_blob:
            icon = self._cached_thumb_icon(item)
        elif row.icon_kind == "file" and row.file_icon_path:
            provider = file_icon_provider or QFileIconProvider()
            file_icon = provider.icon(QFileInfo(row.file_icon_path))
            if not file_icon.isNull():
                icon = file_icon
        elif row.icon_kind == "special":
            icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning)
        elif row.icon_kind == "bundle":
            icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView)
        if icon is not None:
            lw_item.setIcon(icon)

        lw_item.setData(ITEM_ID_ROLE, item.id)
        lw_item.setData(ITEM_TYPE_ROLE, item.content_type)
        lw_item.setData(ITEM_TEXT_ROLE, item.plain_text or item.text)
        lw_item.setData(ITEM_NOTE_ROLE, item.note or "")
        lw_item.setData(ITEM_HAS_NOTE_ROLE, has_note)
        lw_item.setData(ITEM_NOTE_TEXT_ROLE, note_text)
        lw_item.setData(ITEM_CONTENT_TEXT_ROLE, content_text)
        lw_item.setData(ITEM_TAB_ID_ROLE, int(item.tab_id))
        lw_item.setData(ITEM_SECONDARY_TEXT_ROLE, row.secondary_text)
        lw_item.setData(ITEM_TYPE_LABEL_ROLE, row.type_label)
        lw_item.setData(ITEM_PINNED_ROLE, bool(item.pinned))
        return lw_item

    def prepend_item(self, item: ClipItem, deleted_ids: Optional[list[int]] = None) -> bool:
        """只往列表里插一条新条目，避免整表重建。

        返回 True 表示已增量更新，调用方可以跳过 set_items 全量刷新。
        返回 False 表示当前状态不适合增量（搜索模式/渲染中/列表与库不同步），
        调用方应回退到整表刷新。
        """
        if self._item_list_search_mode or self._pending_render_items:
            return False
        if deleted_ids:
            wanted = {int(x) for x in deleted_ids}
            for row in range(self.item_list.count() - 1, -1, -1):
                lw = self.item_list.item(row)
                if lw is None:
                    continue
                try:
                    row_id = int(lw.data(ITEM_ID_ROLE))
                except (TypeError, ValueError):
                    continue
                if row_id in wanted:
                    self.item_list.takeItem(row)
                    wanted.discard(row_id)
            if wanted:
                # 列表里找不到刚被容量裁掉的条目，说明已经不同步，退回整表刷新
                return False
        lw_item = self._create_list_item(item, search_mode=False)
        insert_at = 0
        row_count = self.item_list.count()
        # 排序规则是 pinned 降序在前，所以新条目要插到所有置顶条目之后
        while insert_at < row_count and bool(
            self.item_list.item(insert_at).data(ITEM_PINNED_ROLE)
        ):
            insert_at += 1
        self.item_list.setUpdatesEnabled(False)
        try:
            self.item_list.insertItem(insert_at, lw_item)
        finally:
            self.item_list.setUpdatesEnabled(True)
        return True

    def _focus_search_input(self) -> None:
        self.search_input.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search_input.selectAll()

    def _on_search_input_changed(self, _text: str) -> None:
        self._search_debounce_timer.start()

    def _emit_search_text_changed(self) -> None:
        self.search_text_changed.emit(self.search_input.text().strip())

    def _clear_search(self) -> None:
        self.search_input.clear()
        self.item_list.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def _on_main_splitter_moved(self, _pos: int, _index: int) -> None:
        self._splitter_save_timer.start()

    def _emit_splitter_sizes_changed(self) -> None:
        if self._main_splitter is None:
            return
        sizes = self._main_splitter.sizes()
        if len(sizes) < 2:
            return
        left_size = max(0, int(sizes[0]))
        right_size = max(0, int(sizes[1]))
        value = f"{left_size},{right_size}"
        if value == self._last_splitter_sizes_text:
            return
        self._last_splitter_sizes_text = value
        self.splitter_sizes_changed.emit(value)

    def set_main_splitter_sizes(self, left: int, right: int) -> None:
        if self._main_splitter is None:
            return
        left_size = max(0, int(left))
        right_size = max(0, int(right))
        if left_size == 0 and right_size == 0:
            return
        self._main_splitter.setSizes([left_size, right_size])
        self._last_splitter_sizes_text = f"{left_size},{right_size}"

    def current_tab_id(self) -> Optional[int]:
        current = self.tab_list.currentItem()
        if not current:
            return None
        return int(current.data(ITEM_ID_ROLE))

    def set_hotkey_text(self, hotkey_text: str) -> None:
        self._hotkey_text = hotkey_text

    def set_capture_tab(self, capture_tab_id: Optional[int], capture_tab_text: str) -> None:
        self._capture_tab_id = capture_tab_id
        self._capture_tab_text = capture_tab_text

    def set_capture_tab_max(self, max_items: int) -> None:
        self._capture_tab_max = int(max_items)

    def save_window_geometry(self) -> str:
        data = self.saveGeometry()
        return bytes(data).hex()

    def restore_window_geometry(self, hex_text: str) -> bool:
        clean = (hex_text or "").strip()
        if not clean:
            return False
        try:
            data = QByteArray.fromHex(clean.encode("ascii"))
        except Exception:
            return False
        if data.isEmpty():
            return False
        restored = self.restoreGeometry(data)
        self._ensure_within_screen()
        return restored

    def _ensure_within_screen(self) -> None:
        screen = self.screen()
        if screen is None:
            app = QApplication.instance()
            if app is None:
                return
            point = self.mapToGlobal(self.rect().center())
            screen = app.screenAt(point)
            if screen is None:
                screen = app.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        frame = self.frameGeometry()
        if frame.intersects(available):
            return
        x = max(available.left(), min(frame.x(), available.right() - frame.width()))
        y = max(available.top(), min(frame.y(), available.bottom() - frame.height()))
        width = min(frame.width(), available.width())
        height = min(frame.height(), available.height())
        self.move(x, y)
        self.resize(width, height)

    def current_appearance(self) -> AppearanceSettings:
        return self._appearance

    def set_user_appearance(self, appearance: AppearanceSettings) -> None:
        self._user_appearance = appearance

    def user_appearance(self) -> AppearanceSettings:
        return getattr(self, "_user_appearance", None) or self._appearance

    def set_theme_mode(self, mode: str) -> None:
        self._theme_mode = str(mode or "follow_system")

    def theme_mode(self) -> str:
        return getattr(self, "_theme_mode", "follow_system")

    def set_appearance(self, appearance: AppearanceSettings) -> None:
        self._appearance = appearance
        self._backdrop_blur_enabled = bool(
            getattr(appearance, "backdrop_blur", True)
        )
        self._theme_tokens = build_theme_tokens_from_appearance(appearance)
        if self._item_delegate is not None:
            self._item_delegate.set_theme_tokens(self._theme_tokens)
            self._item_delegate.set_antialias_enabled(appearance.item_antialias)
        self._apply_theme()
        self._apply_titlebar_theme()
        self._apply_window_backdrop()
        self.item_list.viewport().update()

    def _apply_window_backdrop(self) -> None:
        tokens = self._theme_tokens
        if tokens is None:
            return
        try:
            hwnd = int(self.winId())
        except Exception:
            return
        if not hwnd:
            return
        strength = tokens.glass_strength
        blur_active = bool(self._backdrop_blur_enabled) and strength == "transparent"
        state = (blur_active, tokens.main_window_bg)
        if state == self._last_backdrop_state:
            return
        self._last_backdrop_state = state
        if blur_active:
            apply_acrylic(hwnd, argb_tint(tokens.main_window_bg, 120))
        else:
            disable_backdrop(hwnd)
        self._repaint_surfaces()

    def _apply_titlebar_theme(self) -> None:
        """Match the OS-drawn caption to the current theme (see titlebar_theme)."""
        tokens = self._theme_tokens
        if tokens is None:
            return
        dark = bool(getattr(tokens, "is_dark", False))
        # Dialogs are created later, so publish the style for them too.
        set_dialog_titlebar_theme(dark, tokens.main_window_bg, tokens.text_primary)
        try:
            hwnd = int(self.winId())
        except Exception:
            return
        apply_titlebar_theme(
            hwnd,
            dark=dark,
            caption_hex=tokens.main_window_bg,
            text_hex=tokens.text_primary,
        )
        set_round_corners(hwnd, True)

    def set_note_style(self, color_hex: str, font_size: int) -> None:
        self._note_text_color = color_hex
        self._note_font_size = font_size
        if self._item_delegate is not None:
            self._item_delegate.set_note_style(color_hex, font_size)
        self.item_list.doItemsLayout()
        self.item_list.updateGeometry()
        self.item_list.viewport().update()

    def set_pinned_style(self, color_hex: str) -> None:
        color = QColor(str(color_hex or "").strip())
        if not color.isValid():
            color = QColor("#1fb8cb")
        self._pinned_accent_color = color.name()
        if self._item_delegate is not None:
            self._item_delegate.set_pinned_color(self._pinned_accent_color)
        self.item_list.viewport().update()
    def show_for_quick_paste(self) -> None:
        splitter_count = self._main_splitter.count() if self._main_splitter is not None else -1
        logger.info(
            "[UI] show_for_quick_paste enter visible_before=%s active_before=%s minimized_before=%s splitter_count=%s",
            self.isVisible(),
            self.isActiveWindow(),
            bool(self.windowState() & Qt.WindowState.WindowMinimized),
            splitter_count,
        )
        # Prevent immediate auto-hide when hotkey-triggered show races with focus events.
        self._suspend_auto_hide_for(300)
        self._panel_visible = True
        self._foreground_generation += 1
        generation = self._foreground_generation
        self.show()
        self.setWindowState(
            (self.windowState() & ~Qt.WindowState.WindowMinimized) | Qt.WindowState.WindowActive
        )
        self.raise_()
        self.activateWindow()
        self._panel_had_focus = self._panel_had_focus or self.isActiveWindow()
        logger.info(
            "[UI] show_for_quick_paste post-show visible=%s active=%s minimized=%s",
            self.isVisible(),
            self.isActiveWindow(),
            bool(self.windowState() & Qt.WindowState.WindowMinimized),
        )
        if sys.platform == "win32":
            self._force_foreground_windows(generation)
            # Retry sequence to improve reliability when foreground lock blocks first attempt.
            QTimer.singleShot(60, lambda: self._force_foreground_windows(generation))
            QTimer.singleShot(180, lambda: self._force_foreground_windows(generation))
        if self.item_list.count() > 0:
            self.item_list.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
        QTimer.singleShot(260, lambda: self._ensure_hotkey_window_visible(generation))

    def _release_auto_hide_suspend(self) -> None:
        self._auto_hide_suspend_count = max(0, self._auto_hide_suspend_count - 1)

    def _suspend_auto_hide_for(self, milliseconds: int) -> None:
        self._auto_hide_suspend_count += 1
        QTimer.singleShot(max(10, int(milliseconds)), self._release_auto_hide_suspend)

    def _ensure_hotkey_window_visible(self, generation: int | None = None) -> None:
        if generation is not None and generation != self._foreground_generation:
            return
        logger.info(
            "[UI] ensure_hotkey_window_visible visible=%s active=%s",
            self.isVisible(),
            self.isActiveWindow(),
        )
        if not self.should_hide_on_hotkey():
            return
        if self.isActiveWindow():
            return
        self.raise_()
        self.activateWindow()
        logger.info(
            "[UI] ensure_hotkey_window_visible post-raise visible=%s active=%s",
            self.isVisible(),
            self.isActiveWindow(),
        )
        if sys.platform == "win32":
            self._force_foreground_windows()
        QTimer.singleShot(260, self._notify_hotkey_foreground_limited)

    def _notify_hotkey_foreground_limited(self) -> None:
        if not self.should_hide_on_hotkey() or self.isActiveWindow():
            return
        if self._tray_icon is None or not self._tray_icon.isVisible():
            return
        self._tray_icon.showMessage(
            APP_NAME,
            f"热键已触发，但系统拦截了前台切换。请点击任务栏中的 {APP_NAME}。",
            QSystemTrayIcon.MessageIcon.Information,
            2500,
        )

    def _force_foreground_windows(self, generation: int | None = None) -> None:
        if sys.platform != "win32":
            return
        if generation is not None and generation != self._foreground_generation:
            logger.debug("[UI] force_foreground skipped; generation stale")
            return
        # Delayed retries scheduled by show_for_quick_paste may fire after the
        # window was hidden again (fast show -> Enter-to-paste flow). Raw Win32
        # calls would resurrect the hidden window as a blank shell, so bail out.
        if not self.should_hide_on_hotkey():
            logger.debug("[UI] force_foreground skipped; window not visible")
            return
        try:
            import ctypes

            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            hwnd = int(self.winId())
            if not hwnd:
                return

            sw_restore = 9
            hwnd_topmost = -1
            hwnd_notopmost = -2
            swp_nosize = 0x0001
            swp_nomove = 0x0002
            swp_showwindow = 0x0040
            flags = swp_nosize | swp_nomove | swp_showwindow

            fg_hwnd = user32.GetForegroundWindow()
            current_tid = kernel32.GetCurrentThreadId()
            target_tid = 0
            if fg_hwnd:
                fg_pid = ctypes.c_ulong(0)
                target_tid = user32.GetWindowThreadProcessId(fg_hwnd, ctypes.byref(fg_pid))

            attached = False
            if target_tid and target_tid != current_tid:
                attached = bool(user32.AttachThreadInput(target_tid, current_tid, True))

            try:
                user32.ShowWindow(hwnd, sw_restore)
                user32.SetWindowPos(hwnd, hwnd_topmost, 0, 0, 0, 0, flags)
                user32.SetWindowPos(hwnd, hwnd_notopmost, 0, 0, 0, 0, flags)
                user32.BringWindowToTop(hwnd)
                user32.SetForegroundWindow(hwnd)
                user32.SetFocus(hwnd)
            finally:
                if attached:
                    user32.AttachThreadInput(target_tid, current_tid, False)
        except Exception as exc:
            logger.debug("[UI] _force_foreground_windows failed: %s", exc)
            return

    def _configure_main_splitter_collapsible(self) -> None:
        if self._main_splitter is None:
            logger.warning("[UI] main splitter missing; skip setCollapsible.")
            return
        count = self._main_splitter.count()
        logger.info("[UI] main splitter count = %s", count)
        if count >= 1:
            self._main_splitter.setCollapsible(0, True)
        else:
            logger.warning("[UI] skip setCollapsible(0, ...): splitter count < 1")
        if count >= 2:
            self._main_splitter.setCollapsible(1, False)
        else:
            logger.warning("[UI] skip setCollapsible(1, ...): splitter count < 2")

    def should_hide_on_hotkey(self) -> bool:
        return bool(self._panel_visible) and not bool(
            self.windowState() & Qt.WindowState.WindowMinimized
        )

    def _hide_panel(self) -> None:
        self._panel_visible = False
        self._panel_had_focus = False
        self._panel_watch_timer.stop()
        self._resize_cursor_timer.stop()
        self._apply_resize_cursor(None)
        self._foreground_generation += 1
        self.hide()

    def hide_panel(self) -> None:
        self._hide_panel()

    def _on_titlebar_collapse(self) -> None:
        self._hide_panel()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._panel_visible = True
        if not self._panel_watch_timer.isActive():
            self._panel_watch_timer.start()
        elif self.isActiveWindow():
            self._panel_had_focus = True
        if not self._resize_cursor_timer.isActive():
            self._resize_cursor_timer.start()
        # The native handle only exists once shown; re-apply so a hidden-at-startup
        # window still gets the themed caption.
        self._apply_titlebar_theme()
        self._apply_window_backdrop()
        self.window_shown.emit()

    def hideEvent(self, event) -> None:
        self._panel_visible = False
        self._panel_had_focus = False
        self._panel_watch_timer.stop()
        self._resize_cursor_timer.stop()
        self._apply_resize_cursor(None)
        super().hideEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        overlay = getattr(self, "_frosted_overlay", None)
        root = self.centralWidget()
        if overlay is not None and root is not None:
            overlay.setGeometry(root.rect())
            overlay.raise_()

    def nativeEvent(self, event_type, message):
        if sys.platform == "win32" and event_type == b"windows_generic_MSG":
            try:
                import ctypes
                from ctypes import wintypes

                msg = wintypes.MSG.from_address(int(message))
                if msg.message == 0x0084 and not self.isMaximized():  # WM_NCHITTEST
                    x = ctypes.c_short(msg.lParam & 0xFFFF).value
                    y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
                    dpr = self.devicePixelRatioF() or 1.0
                    local = self.mapFromGlobal(QPoint(int(x / dpr), int(y / dpr)))
                    code = self._resize_hit_code(local)
                    if code:
                        return True, code
            except Exception:
                logger.debug("[UI] nativeEvent WM_NCHITTEST failed", exc_info=True)
        return super().nativeEvent(event_type, message)

    def _resize_hit_code(self, local: QPoint) -> int:
        border = 6
        width = self.width()
        height = self.height()
        x = local.x()
        y = local.y()
        left = x <= border
        right = x >= width - border
        top = y <= border
        bottom = y >= height - border
        if top and left:
            return 13  # HTTOPLEFT
        if top and right:
            return 14  # HTTOPRIGHT
        if bottom and left:
            return 16  # HTBOTTOMLEFT
        if bottom and right:
            return 17  # HTBOTTOMRIGHT
        if left:
            return 10  # HTLEFT
        if right:
            return 11  # HTRIGHT
        if top:
            return 12  # HTTOP
        if bottom:
            return 15  # HTBOTTOM
        return 0

    def _foreground_window_owner_is_self(self) -> Optional[bool]:
        """True if the current foreground window belongs to this process."""
        if sys.platform != "win32":
            return None
        try:
            import ctypes

            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return None
            pid = ctypes.c_ulong(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            return pid.value == os.getpid()
        except Exception:
            return None

    def _check_panel_foreground(self) -> None:
        """Safety net for auto-hide when WindowDeactivate is not delivered
        (some apps such as IM clients take foreground without a clean event)."""
        if not self._panel_visible:
            self._panel_watch_timer.stop()
            return
        if self._auto_hide_suspend_count > 0:
            return
        if self._allow_close:
            return
        if self._tray_icon is None or not self._tray_icon.isVisible():
            return
        if QApplication.activeModalWidget() is not None:
            return
        if bool(self.windowState() & Qt.WindowState.WindowMinimized):
            return
        owner = self._foreground_window_owner_is_self()
        if owner is None:
            return
        if owner:
            self._panel_had_focus = True
            return
        if not self._panel_had_focus:
            return
        self._hide_panel()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._allow_close or self._tray_icon is None or not self._tray_icon.isVisible():
            event.accept()
            return
        event.ignore()
        self._hide_panel()
        self._show_tray_hint_once()

    def confirm(
        self,
        title: str,
        message: str,
        confirm_text: str = "删除",
        destructive: bool = True,
    ) -> bool:
        return show_confirm(
            self,
            title,
            message,
            confirm_text=confirm_text,
            destructive=destructive,
        )

    def show_vacuum_progress(self) -> None:
        """打开一个不可关闭的进度框，用于长时间的数据库整理。"""
        if self._vacuum_progress_dialog is not None:
            return
        dialog = ProgressDialog(
            self,
            "压缩数据库",
            "正在整理数据库并释放空间，请稍候……\n\n期间请不要复制内容，完成后会自动关闭。",
            kind="info",
        )
        self._vacuum_progress_dialog = dialog
        dialog.show()  # 不用 exec()：让事件循环继续跑，后台线程才能回调

    def finish_vacuum_progress(self, before: int, after: int, error: str) -> None:
        dialog = self._vacuum_progress_dialog
        self._vacuum_progress_dialog = None
        if dialog is not None:
            dialog.finish()
            dialog.deleteLater()
        if error:
            self.show_error(f"压缩数据库失败：{error}")
            return
        freed = max(0, int(before) - int(after))
        self.show_info(f"数据库压缩完成，释放了 {freed // (1024 * 1024)} MB。")

    def show_error(self, message: str) -> None:
        MessageDialog(self, "出错了", message, kind="error").exec()

    def show_warning(self, message: str) -> None:
        MessageDialog(self, "提示", message, kind="warning").exec()

    def show_info(self, message: str) -> None:
        if self.isVisible():
            show_toast(self, message, "success")
        elif self._tray_icon is not None and self._tray_icon.isVisible():
            self._tray_icon.showMessage(
                APP_NAME,
                message,
                QSystemTrayIcon.MessageIcon.Information,
                3000,
            )

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.WindowDeactivate:
            # Cancel any pending forced-foreground so it cannot pull focus back.
            self._foreground_generation += 1
            QTimer.singleShot(0, self._hide_on_deactivate)
        elif event.type() == QEvent.Type.WindowActivate:
            self._panel_had_focus = True
        return super().event(event)

    def _edge_resize_edges(self, local: QPoint):
        border = 6
        edges = Qt.Edge(0)
        if local.x() <= border:
            edges |= Qt.Edge.LeftEdge
        if local.x() >= self.width() - border:
            edges |= Qt.Edge.RightEdge
        if local.y() <= border:
            edges |= Qt.Edge.TopEdge
        if local.y() >= self.height() - border:
            edges |= Qt.Edge.BottomEdge
        return edges

    def _cursor_for_edges(self, edges):
        if not edges:
            return None
        left = bool(edges & Qt.Edge.LeftEdge)
        right = bool(edges & Qt.Edge.RightEdge)
        top = bool(edges & Qt.Edge.TopEdge)
        bottom = bool(edges & Qt.Edge.BottomEdge)
        if (left and top) or (right and bottom):
            return Qt.CursorShape.SizeFDiagCursor
        if (right and top) or (left and bottom):
            return Qt.CursorShape.SizeBDiagCursor
        if left or right:
            return Qt.CursorShape.SizeHorCursor
        return Qt.CursorShape.SizeVerCursor

    def _apply_resize_cursor(self, shape) -> None:
        if shape == self._resize_cursor_shape:
            return
        if self._resize_cursor_shape is not None:
            QApplication.restoreOverrideCursor()
        if shape is not None:
            QApplication.setOverrideCursor(shape)
        self._resize_cursor_shape = shape

    def _update_resize_cursor(self) -> None:
        if (
            not self.isVisible()
            or self.isMaximized()
            or QApplication.activeModalWidget() is not None
        ):
            self._apply_resize_cursor(None)
            return
        local = self.mapFromGlobal(QCursor.pos())
        if not self.rect().contains(local):
            self._apply_resize_cursor(None)
            return
        self._apply_resize_cursor(self._cursor_for_edges(self._edge_resize_edges(local)))

    @staticmethod
    def _is_win10() -> bool:
        if sys.platform != "win32":
            return False
        try:
            return int(sys.getwindowsversion().build) < 22000
        except Exception:
            return False

    def begin_system_drag(self) -> None:
        """Called right before a native move/resize: pause cursor polling and,
        on Windows 10, suspend the acrylic backdrop (per-frame blur compositing
        makes dragging laggy there)."""
        self._resize_cursor_timer.stop()
        self._apply_resize_cursor(None)
        tokens = self._theme_tokens
        if (
            self._is_win10()
            and self._backdrop_blur_enabled
            and tokens is not None
            and tokens.glass_strength == "transparent"
        ):
            try:
                hwnd = int(self.winId())
                if hwnd and disable_backdrop(hwnd):
                    self._backdrop_suspended = True
            except Exception:
                logger.debug("[UI] suspend backdrop failed", exc_info=True)
        if not self._drag_poll_timer.isActive():
            self._drag_poll_timer.start()

    def _poll_drag_end(self) -> None:
        if QApplication.mouseButtons() & Qt.MouseButton.LeftButton:
            return
        self._drag_poll_timer.stop()
        if self._backdrop_suspended:
            self._backdrop_suspended = False
            self._last_backdrop_state = None
            self._apply_window_backdrop()
        if self._panel_visible and not self._resize_cursor_timer.isActive():
            self._resize_cursor_timer.start()

    def _try_edge_resize(self, watched, event: QEvent) -> bool:
        if sys.platform != "win32" or event.type() != QEvent.Type.MouseButtonPress:
            return False
        if watched is not self.centralWidget():
            return False
        if not self.isVisible() or self.isMaximized():
            return False
        button = getattr(event, "button", None)
        if button is not None and button() != Qt.MouseButton.LeftButton:
            return False
        try:
            global_pos = event.globalPosition().toPoint()
        except Exception:
            return False
        edges = self._edge_resize_edges(self.mapFromGlobal(global_pos))
        if not edges:
            return False
        handle = self.windowHandle()
        if handle is None:
            return False
        self.begin_system_drag()
        handle.startSystemResize(edges)
        return True

    def eventFilter(self, watched, event: QEvent) -> bool:
        if self._try_edge_resize(watched, event):
            return True
        if watched is self.search_input and event.type() == QEvent.Type.KeyPress:
            key = getattr(event, "key", None)
            key_value = key() if callable(key) else None
            if key_value == Qt.Key.Key_Escape:
                if self.search_input.text():
                    self.search_input.clear()
                self.item_list.setFocus(Qt.FocusReason.ShortcutFocusReason)
                return True
        if watched in (self.item_list, self.item_list.viewport()) and event.type() == QEvent.Type.KeyPress:
            key = getattr(event, "key", None)
            modifiers = getattr(event, "modifiers", None)
            key_value = key() if callable(key) else None
            mod_value = modifiers() if callable(modifiers) else Qt.KeyboardModifier.NoModifier
            if (
                key_value in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and mod_value in (
                    Qt.KeyboardModifier.NoModifier,
                    Qt.KeyboardModifier.KeypadModifier,
                )
            ):
                if self._activate_current_item():
                    return True
            if (
                mod_value in (
                    Qt.KeyboardModifier.NoModifier,
                    Qt.KeyboardModifier.KeypadModifier,
                )
                and key_value is not None
                and Qt.Key.Key_1 <= key_value <= Qt.Key.Key_9
            ):
                if self._activate_item_at_row(int(key_value) - int(Qt.Key.Key_1)):
                    return True
        return super().eventFilter(watched, event)

    def _activate_item_at_row(self, row: int) -> bool:
        if row < 0:
            return False
        return self._activate_item(self.item_list.item(row))

    def _on_item_list_enter_pressed(self) -> None:
        focus_widget = QApplication.focusWidget()
        if focus_widget not in (self.item_list, self.item_list.viewport()):
            return
        self._activate_current_item()

    def _hide_on_deactivate(self) -> None:
        if self._allow_close:
            return
        if self._tray_icon is None or not self._tray_icon.isVisible():
            return
        if not self._panel_visible:
            return
        if self._auto_hide_suspend_count > 0:
            # Focus is still settling right after a hotkey show; the foreground
            # watch timer will hide it once the suspend window expires.
            return
        if bool(self.windowState() & Qt.WindowState.WindowMinimized):
            return
        if self.isActiveWindow():
            return
        if QApplication.activeModalWidget() is not None:
            return
        self._hide_panel()

    def _exec_modal_dialog(self, dialog: QDialog) -> int:
        self._auto_hide_suspend_count += 1
        try:
            return dialog.exec()
        finally:
            self._auto_hide_suspend_count = max(0, self._auto_hide_suspend_count - 1)

    def _with_auto_hide_suspended(self):
        class _Guard:
            def __init__(self, win: MainWindow) -> None:
                self._win = win

            def __enter__(self):
                self._win._auto_hide_suspend_count += 1
                return self

            def __exit__(self, exc_type, exc, tb):
                self._win._auto_hide_suspend_count = max(0, self._win._auto_hide_suspend_count - 1)
                return False

        return _Guard(self)

    def _apply_note_style_for_item(self, item: QListWidgetItem) -> None:
        # Kept for backward compatibility; note rendering is now handled by delegate.
        _ = item

    def prompt_bundle_edit(
        self,
        text: str,
        images: list[dict[str, Any]],
        note: str,
    ) -> tuple[bool, str, list[dict[str, Any]], str]:
        dialog = BundleItemDialog(
            self,
            title="编辑复合条目",
            initial_text=text,
            initial_images=images,
            initial_note=note,
            require_image=True,
        )
        if self._exec_modal_dialog(dialog) != QDialog.DialogCode.Accepted:
            return False, text, images, note
        return True, dialog.result_text(), dialog.result_images(), dialog.result_note()

    def _setup_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        icon = self.windowIcon()
        if icon.isNull():
            app = QApplication.instance()
            if app is not None:
                icon = app.windowIcon()
        if icon.isNull():
            icon = resolve_app_icon(QApplication.instance())
        if icon.isNull():
            logger.warning("托盘图标加载失败，已回退为系统默认图标。")
            icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView)

        self._tray_icon = QSystemTrayIcon(icon, self)
        self._tray_icon.setToolTip(APP_NAME)

        self._tray_menu = QMenu(self)
        self._tray_menu.setObjectName("glassMenu")
        self._tray_menu.setStyleSheet(self._menu_stylesheet())
        dark = bool(self._theme_tokens.is_dark)
        show_action = self._tray_menu.addAction(menu_icon("show", dark), "显示主界面")
        self._capture_toggle_action = self._tray_menu.addAction(
            menu_icon("capture_on", dark), "自动记录剪贴板"
        )
        self._capture_toggle_action.setCheckable(True)
        self._capture_toggle_action.setChecked(bool(self._capture_enabled))
        exit_action = self._tray_menu.addAction(menu_icon("exit", dark), "退出程序")
        show_action.triggered.connect(self.show_for_quick_paste)
        self._capture_toggle_action.toggled.connect(self._on_capture_toggle_action)
        exit_action.triggered.connect(self._quit_application)
        self._tray_icon.setContextMenu(self._tray_menu)
        self._tray_icon.activated.connect(self._on_tray_activated)
        self._tray_icon.show()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_for_quick_paste()

    def _show_tray_hint_once(self) -> None:
        if self._tray_icon is None or self._tray_message_shown:
            return
        self._tray_icon.showMessage(
            APP_NAME,
            "程序已在后台运行，可通过托盘图标重新打开。",
            QSystemTrayIcon.MessageIcon.Information,
            3000,
        )
        self._tray_message_shown = True

    def _quit_application(self) -> None:
        self._allow_close = True
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _on_tab_changed(self, current: QListWidgetItem, _previous: QListWidgetItem) -> None:
        if current is None:
            return
        tab_id = int(current.data(ITEM_ID_ROLE))
        self.tab_selected.emit(tab_id)

    def _on_tab_rows_moved(self, *_args) -> None:
        if self._suppress_tab_reorder_emit:
            return
        tab_ids: list[int] = []
        for idx in range(self.tab_list.count()):
            item = self.tab_list.item(idx)
            if item is None:
                continue
            tab_id = item.data(ITEM_ID_ROLE)
            if tab_id is None:
                continue
            tab_ids.append(int(tab_id))
        if tab_ids:
            self.tab_order_changed.emit(tab_ids)

    def _open_tab_context_menu(self, position) -> None:
        target_item = self.tab_list.itemAt(position)
        if target_item is not None:
            self.tab_list.setCurrentItem(target_item)

        menu = QMenu(self)
        menu.setObjectName("glassMenu")
        menu.setStyleSheet(self._menu_stylesheet())
        dark = bool(self._theme_tokens.is_dark)
        add_action = menu.addAction(menu_icon("tab_add", dark), "新增标签页")
        rename_action = menu.addAction(menu_icon("tab_rename", dark), "重命名标签页")
        delete_action = menu.addAction(menu_icon("tab_delete", dark, danger=True), "删除标签页")

        has_tab = self.current_tab_id() is not None
        rename_action.setEnabled(has_tab)
        delete_action.setEnabled(has_tab)

        with self._with_auto_hide_suspended():
            chosen = menu.exec(self.tab_list.mapToGlobal(position))
        if chosen is add_action:
            self._prompt_add_tab()
        elif chosen is rename_action:
            self._prompt_rename_tab()
        elif chosen is delete_action:
            self._request_delete_tab()

    def _on_item_rows_moved(self, *_args) -> None:
        if self._suppress_item_reorder_emit or self._item_list_search_mode:
            return
        tab_id = self.current_tab_id()
        if tab_id is None:
            return
        item_ids: list[int] = []
        invalid_data = False
        for idx in range(self.item_list.count()):
            item = self.item_list.item(idx)
            if item is None:
                invalid_data = True
                break
            item_id = item.data(ITEM_ID_ROLE)
            if item_id is None:
                invalid_data = True
                break
            try:
                item_ids.append(int(item_id))
            except (TypeError, ValueError):
                invalid_data = True
                break
        if invalid_data or len(item_ids) != self.item_list.count() or len(set(item_ids)) != len(item_ids):
            self.show_info("检测到条目顺序异常，已自动刷新列表。")
            self.tab_selected.emit(int(tab_id))
            return
        if item_ids:
            self.item_order_changed.emit(item_ids, int(tab_id))

    def finish_item_reorder(self, item_ids: list[int]) -> None:
        """Keep the moved row visible after persistence without rebuilding the list."""
        moved_id = None
        current = self.item_list.currentItem()
        if current is not None:
            try:
                moved_id = int(current.data(ITEM_ID_ROLE))
            except (TypeError, ValueError):
                moved_id = None
        if moved_id is None and item_ids:
            try:
                moved_id = int(item_ids[0])
            except (TypeError, ValueError):
                return
        if moved_id is None:
            return

        for row in range(self.item_list.count()):
            item = self.item_list.item(row)
            if item is None:
                continue
            try:
                item_id = int(item.data(ITEM_ID_ROLE))
            except (TypeError, ValueError):
                continue
            if item_id == moved_id:
                self.item_list.setCurrentItem(item)
                self.item_list.scrollToItem(
                    item,
                    QAbstractItemView.ScrollHint.PositionAtCenter,
                )
                self._last_selected_item_id = moved_id
                self._reorder_highlight_item_id = moved_id
                if self._item_delegate is not None:
                    self._item_delegate.set_reorder_highlight_item(moved_id)
                self._reorder_highlight_timer.start()
                self.item_list.viewport().update()
                return

    def _clear_item_reorder_highlight(self) -> None:
        if self._reorder_highlight_item_id is None:
            return
        self._reorder_highlight_item_id = None
        if self._item_delegate is not None:
            self._item_delegate.set_reorder_highlight_item(None)
        self.item_list.viewport().update()

    def _prompt_add_tab(self) -> None:
        dialog = TextInputDialog(self, "新增标签页", "标签页名称：", placeholder="例如：常用语")
        with self._with_auto_hide_suspended():
            accepted = self._exec_modal_dialog(dialog) == QDialog.DialogCode.Accepted
        if accepted:
            text = dialog.value().strip()
            if text:
                self.create_tab_requested.emit(text)

    def _prompt_rename_tab(self) -> None:
        tab_id = self.current_tab_id()
        if tab_id is None:
            return
        current = self.tab_list.currentItem()
        current_name = current.text() if current else ""
        dialog = TextInputDialog(self, "重命名标签页", "新名称：", text=current_name)
        with self._with_auto_hide_suspended():
            accepted = self._exec_modal_dialog(dialog) == QDialog.DialogCode.Accepted
        if accepted:
            text = dialog.value().strip()
            if text:
                self.rename_tab_requested.emit(tab_id, text)

    def _request_delete_tab(self) -> None:
        tab_id = self.current_tab_id()
        if tab_id is not None:
            self.delete_tab_requested.emit(tab_id)

    def _prompt_add_item(self) -> None:
        dialog = BundleItemDialog(self, title="新建条目")
        if self._exec_modal_dialog(dialog) != QDialog.DialogCode.Accepted:
            return
        text = dialog.result_text()
        images = dialog.result_images()
        note = dialog.result_note()
        if images:
            self.add_mixed_item_requested.emit(dialog.result_segments(), note)
        elif text.strip():
            self.add_item_requested.emit(text)

    def prompt_select_local_tabs_for_export(
        self,
        tabs: list[Tab],
        item_counts: dict[int, int],
    ) -> list[int] | None:
        options: list[tuple[str, str]] = []
        for tab in tabs:
            count = int(item_counts.get(tab.id, 0))
            options.append((str(tab.id), f"{tab.name}（{count} 条）"))
        dialog = MultiSelectDialog(
            self,
            title="导出标签页与条目",
            prompt="请选择要导出的标签页：",
            options=options,
        )
        if self._exec_modal_dialog(dialog) != QDialog.DialogCode.Accepted:
            return None
        selected: list[int] = []
        for key in dialog.selected_keys():
            try:
                selected.append(int(key))
            except ValueError:
                continue
        return selected

    def show_export_progress(self, cancel_callback=None) -> None:
        self.close_export_progress()
        progress = ExportProgressDialog(self, "导出数据", "正在准备导出…")
        if cancel_callback is not None:
            progress.canceled.connect(cancel_callback)
        self._export_progress = progress
        progress.show()

    def update_export_progress(
        self, done: int, total: int, started_at: float | None = None
    ) -> None:
        progress = getattr(self, "_export_progress", None)
        if progress is None:
            return
        if total > 0:
            progress.setMaximum(total)
            progress.setValue(done)
            label = f"正在导出… {done}/{total} 条"
            if started_at is not None and done > 0 and total > done:
                elapsed = max(0.0, time.monotonic() - started_at)
                seconds_left = int(elapsed * (total - done) / done)
                label += f"，预计剩余 {seconds_left // 60} 分 {seconds_left % 60} 秒"
            progress.setLabelText(label)

    def set_export_cancel_callback(self, cancel_callback) -> None:
        progress = getattr(self, "_export_progress", None)
        if progress is not None:
            progress.canceled.connect(cancel_callback)

    def close_export_progress(self) -> None:
        progress = getattr(self, "_export_progress", None)
        self._export_progress = None
        if progress is not None:
            progress.close()
            progress.deleteLater()

    def prompt_export_file_path(self) -> str | None:
        with self._with_auto_hide_suspended():
            path, _ = QFileDialog.getSaveFileName(
                self,
                "保存导出文件",
                "clipnest_export.fluxpkg",
                "ClipNest 数据包 (*.fluxpkg);;所有文件 (*.*)",
            )
        clean = path.strip()
        if clean == "":
            return None
        return clean

    def prompt_import_file_path(self) -> str | None:
        with self._with_auto_hide_suspended():
            path, _ = QFileDialog.getOpenFileName(
                self,
                "选择导入文件",
                "",
                "ClipNest 数据包 (*.fluxpkg);;ZIP 文件 (*.zip);;所有文件 (*.*)",
            )
        clean = path.strip()
        if clean == "":
            return None
        return clean

    def prompt_select_package_tabs_for_import(
        self,
        tab_summaries: list[tuple[str, str, int]],
    ) -> list[str] | None:
        options: list[tuple[str, str]] = []
        for package_tab_id, name, item_count in tab_summaries:
            options.append((package_tab_id, f"{name}（{int(item_count)} 条）"))
        dialog = MultiSelectDialog(
            self,
            title="导入标签页与条目",
            prompt="请选择要导入的标签页：",
            options=options,
        )
        if self._exec_modal_dialog(dialog) != QDialog.DialogCode.Accepted:
            return None
        return dialog.selected_keys()

    def _on_item_current_changed(
        self,
        current: Optional[QListWidgetItem],
        _previous: Optional[QListWidgetItem],
    ) -> None:
        if current is None:
            return
        item_id = current.data(ITEM_ID_ROLE)
        if item_id is None:
            return
        self._last_selected_item_id = int(item_id)

    def _activate_item(
        self,
        item: Optional[QListWidgetItem],
        *,
        as_text: bool = False,
    ) -> bool:
        if item is None:
            return False
        item_id = item.data(ITEM_ID_ROLE)
        if item_id is None:
            return False
        self._last_selected_item_id = int(item_id)
        if as_text:
            self.item_paste_text_requested.emit(int(item_id))
        else:
            self.item_activated.emit(int(item_id))
        return True

    def _activate_current_item(self) -> bool:
        return self._activate_item(self.item_list.currentItem())

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        as_text = bool(
            QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier
        )
        self._activate_item(item, as_text=as_text)

    def _add_paste_mode_menu(
        self,
        menu: QMenu,
        item: QListWidgetItem,
        dark: bool,
    ) -> tuple[QAction, QAction]:
        paste_menu = menu.addMenu(menu_icon("copy", dark), "粘贴方式")
        paste_menu.setObjectName("glassMenu")
        paste_menu.setStyleSheet(self._menu_stylesheet())
        paste_default_action = paste_menu.addAction("保留原格式")
        paste_text_action = paste_menu.addAction("粘贴为纯文本")
        plain_text = str(item.data(ITEM_TEXT_ROLE) or "").strip()
        paste_text_action.setEnabled(bool(plain_text))
        if plain_text:
            paste_text_action.setToolTip("按住 Shift 单击条目也可快速纯文本粘贴")
        else:
            paste_text_action.setToolTip("该条目没有可粘贴的文本")
        return paste_default_action, paste_text_action

    def _open_item_context_menu(self, pos) -> None:
        current_tab_id = self.current_tab_id()
        if current_tab_id is None:
            return
        item = self.item_list.itemAt(pos)
        menu = QMenu(self)
        menu.setObjectName("glassMenu")
        menu.setStyleSheet(self._menu_stylesheet())

        if item is not None:
            selected_items = self.item_list.selectedItems()
            if not selected_items or item not in selected_items:
                self.item_list.setCurrentItem(item)
                selected_items = [item]
            item_ids: list[int] = []
            source_tab_ids: set[int] = set()
            for selected_item in selected_items:
                raw_item_id = selected_item.data(ITEM_ID_ROLE)
                if raw_item_id is None:
                    continue
                item_ids.append(int(raw_item_id))
                raw_tab_id = selected_item.data(ITEM_TAB_ID_ROLE)
                if raw_tab_id is not None:
                    source_tab_ids.add(int(raw_tab_id))
            if not item_ids:
                return

            item_id = int(item.data(ITEM_ID_ROLE))
            is_pinned = bool(item.data(ITEM_PINNED_ROLE))
            dark = bool(self._theme_tokens.is_dark)
            paste_default_action, paste_text_action = self._add_paste_mode_menu(
                menu, item, dark
            )
            menu.addSeparator()
            pin_action = menu.addAction(
                menu_icon("pin", dark),
                "取消置顶" if is_pinned else "置顶条目",
            )
            edit_action = menu.addAction(menu_icon("edit", dark), "编辑条目")
            edit_note_action = menu.addAction(menu_icon("note", dark), "编辑备注")
            move_menu = menu.addMenu(menu_icon("move", dark), "移动到")
            move_menu.setObjectName("glassMenu")
            move_menu.setStyleSheet(self._menu_stylesheet())
            move_actions: dict[QAction, int] = {}
            for tab in self._tabs_snapshot:
                tab_action = move_menu.addAction(tab.name)
                move_actions[tab_action] = int(tab.id)
            delete_action = menu.addAction(menu_icon("delete", dark, danger=True), "删除条目")
            menu.addSeparator()
            clear_action = menu.addAction(menu_icon("clear", dark, danger=True), "清空列表")
            with self._with_auto_hide_suspended():
                selected = menu.exec(self.item_list.mapToGlobal(pos))
            if selected == paste_default_action:
                self.item_activated.emit(item_id)
            elif selected == paste_text_action:
                self.item_paste_text_requested.emit(item_id)
            elif selected == pin_action:
                self.item_pin_change_requested.emit(item_id, not is_pinned)
            elif selected == edit_action:
                self.start_inline_edit_requested.emit(item_id)
            elif edit_note_action is not None and selected == edit_note_action:
                current_note = str(item.data(ITEM_NOTE_ROLE) or "")
                note_dialog = NoteEditDialog(self, current_note)
                with self._with_auto_hide_suspended():
                    accepted = (
                        self._exec_modal_dialog(note_dialog)
                        == QDialog.DialogCode.Accepted
                    )
                if accepted:
                    self.edit_note_requested.emit(item_id, note_dialog.value())
            elif selected in move_actions:
                target_tab_id = int(move_actions[selected])
                if len(source_tab_ids) == 1 and target_tab_id in source_tab_ids:
                    self.show_info("已在当前标签页")
                    return
                self.move_items_requested.emit(item_ids, target_tab_id)
            elif selected == delete_action:
                self.delete_item_requested.emit(item_id)
            elif selected == clear_action:
                self.clear_items_requested.emit(current_tab_id)
            return

    def show_inline_editor(self, item_id: int, segments: list[dict[str, Any]]) -> None:
        self._inline_edit_item_id = int(item_id)
        self.inline_editor.set_segments(segments or [])
        self.inline_editor_frame.setVisible(True)
        self.inline_editor.setFocus(Qt.FocusReason.OtherFocusReason)

    def hide_inline_editor(self) -> None:
        self._inline_edit_item_id = None
        self.inline_editor_frame.setVisible(False)
        self.inline_editor.clear()

    def _on_inline_edit_save_clicked(self) -> None:
        if self._inline_edit_item_id is None:
            return
        segments = self.inline_editor.segments()
        self.save_inline_edit_requested.emit(int(self._inline_edit_item_id), segments)

    def _apply_theme(self) -> None:
        app_stylesheet = build_app_stylesheet(self._theme_tokens)
        base_point = max(10, int(self._theme_tokens.base_font_size))
        if (
            app_stylesheet == self._last_app_stylesheet
            and base_point == self._last_app_font_point
        ):
            return
        self._last_app_stylesheet = app_stylesheet
        self._last_app_font_point = base_point
        app = QApplication.instance()
        base_font = QFont(self.font())
        base_font.setPointSize(base_point)
        self.setUpdatesEnabled(False)
        try:
            if app is not None:
                app.setFont(base_font)
                app.setStyleSheet(app_stylesheet)
            else:
                self.setFont(base_font)
                self.setStyleSheet(app_stylesheet)
            self._refresh_update_button()
            self.settings_button.setIcon(
                resolved_line_icon("gear", bool(self._theme_tokens.is_dark), 18)
            )
            self.add_item_btn.setIcon(
                _create_add_icon("#FFFFFF" if self._theme_tokens.is_dark else "#1f2937")
            )
            title_bar = getattr(self, "_title_bar", None)
            if title_bar is not None:
                title_bar.apply_theme(self._theme_tokens)
            self._refresh_capture_button()
            if self._tray_menu is not None:
                self._tray_menu.setStyleSheet(self._menu_stylesheet())
        finally:
            self.setUpdatesEnabled(True)
        self._repaint_surfaces()

    def _repaint_surfaces(self) -> None:
        overlay = getattr(self, "_frosted_overlay", None)
        if overlay is not None:
            overlay.update()
        central = self.centralWidget()
        if central is not None:
            central.update()
        self.update()


    def _apply_light_theme(self) -> None:
        # Backward-compatible alias.
        self._apply_theme()

    def _menu_stylesheet(self) -> str:
        return build_menu_stylesheet(self._theme_tokens)


