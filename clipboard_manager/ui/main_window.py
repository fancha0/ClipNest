from __future__ import annotations

import hashlib
import logging
import re
import sys
import time
from typing import Any, Optional

from PySide6.QtCore import (
    QByteArray,
    QBuffer,
    QEvent,
    QFileInfo,
    QIODevice,
    QObject,
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
    QDrag,
    QIcon,
    QImage,
    QKeySequence,
    QPainter,
    QPixmap,
    QShortcut,
    QTextDocument,
    QTextImageFormat,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QSpinBox,
    QStyle,
    QSystemTrayIcon,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QFileIconProvider,
)

from ..models import ClipItem, Tab
from ..config import APP_NAME
from ..icon_utils import resolve_app_icon
from .item_presenter import present_item
from .item_delegate import ClipItemDelegate
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
    _AUTO_SCROLL_EDGE_PX = 56
    _AUTO_SCROLL_BASE_PX = 10
    _AUTO_SCROLL_MAX_PX = 28

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._auto_scroll_direction = 0
        self._auto_scroll_pixels = 0
        self._auto_scroll_timer = QTimer(self)
        self._auto_scroll_timer.setInterval(16)
        self._auto_scroll_timer.timeout.connect(self._perform_drag_auto_scroll)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

    def startDrag(self, supported_actions: Qt.DropAction) -> None:
        try:
            super().startDrag(supported_actions)
        finally:
            self._stop_drag_auto_scroll()

    def dragMoveEvent(self, event) -> None:
        if event.source() is self:
            self._update_drag_auto_scroll(event.position().toPoint().y())
        else:
            self._stop_drag_auto_scroll()
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event) -> None:
        self._stop_drag_auto_scroll()
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        self._stop_drag_auto_scroll()
        super().dropEvent(event)

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
        self._reorder_enabled = True
        self._drag_source_row: Optional[int] = None
        self.set_reorder_enabled(True)

    def set_reorder_enabled(self, enabled: bool) -> None:
        self._reorder_enabled = bool(enabled)
        self.setDragEnabled(self._reorder_enabled)
        self.setAcceptDrops(self._reorder_enabled)
        self.setDropIndicatorShown(self._reorder_enabled)
        self.setDragDropOverwriteMode(False)
        self.setDragDropMode(
            QAbstractItemView.DragDropMode.InternalMove
            if self._reorder_enabled
            else QAbstractItemView.DragDropMode.NoDragDrop
        )
        if self._reorder_enabled:
            self.setDefaultDropAction(Qt.DropAction.MoveAction)
        if not self._reorder_enabled:
            self._stop_drag_auto_scroll()

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

        self._drag_source_row = source_row
        drag = QDrag(self)
        drag.setMimeData(mime_data)
        rect = self.visualRect(indexes[0])
        if rect.isValid():
            drag.setPixmap(self.viewport().grab(rect))
        try:
            drag.exec(Qt.DropAction.MoveAction)
        finally:
            self._stop_drag_auto_scroll()
            self._drag_source_row = None

    def dragMoveEvent(self, event) -> None:
        if self._reorder_enabled and event.source() is self:
            self._update_drag_auto_scroll(event.position().toPoint().y())
            event.acceptProposedAction()
        else:
            self._stop_drag_auto_scroll()
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event) -> None:
        self._stop_drag_auto_scroll()
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        self._stop_drag_auto_scroll()
        if not self._reorder_enabled or event.source() is not self:
            return super().dropEvent(event)

        from_row = self._drag_source_row if self._drag_source_row is not None else self.currentRow()
        if from_row < 0 or from_row >= self.count():
            event.ignore()
            return

        drop_row = self._resolve_drop_row(event)
        if drop_row < 0:
            drop_row = 0
        if drop_row > self.count():
            drop_row = self.count()

        if drop_row == from_row or drop_row == from_row + 1:
            self._drag_source_row = None
            event.acceptProposedAction()
            return

        moved_item = self.takeItem(from_row)
        if moved_item is None:
            self._drag_source_row = None
            event.ignore()
            return

        if drop_row > from_row:
            drop_row -= 1
        drop_row = max(0, min(drop_row, self.count()))
        self.insertItem(drop_row, moved_item)
        self.setCurrentItem(moved_item)
        self.items_reordered.emit()
        self._drag_source_row = None
        event.acceptProposedAction()

    def _resolve_drop_row(self, event) -> int:
        if self.count() == 0:
            return 0
        point = event.position().toPoint()
        target_item = self.itemAt(point)
        indicator = self.dropIndicatorPosition()

        if target_item is None:
            return self.count()

        target_row = self.row(target_item)
        if indicator == QAbstractItemView.DropIndicatorPosition.AboveItem:
            return target_row
        if indicator == QAbstractItemView.DropIndicatorPosition.BelowItem:
            return target_row + 1
        if indicator == QAbstractItemView.DropIndicatorPosition.OnViewport:
            return self.count()

        rect = self.visualItemRect(target_item)
        return target_row + 1 if point.y() >= rect.center().y() else target_row


class BundleImageInputList(QListWidget):
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
        paste_action = menu.addAction("粘贴图片")
        selected = menu.exec(self.mapToGlobal(pos))
        if selected == paste_action:
            self.paste_images_from_clipboard()

    def paste_images_from_clipboard(self) -> bool:
        if self._emit_images_from_mime_data(QApplication.clipboard().mimeData()):
            return True
        QMessageBox.warning(self, "提示", "剪贴板中没有可用图片。")
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

    @staticmethod
    def _mime_may_contain_images(mime_data) -> bool:
        if mime_data is None:
            return False
        if mime_data.hasImage():
            return True
        if not mime_data.hasUrls():
            return False
        for url in mime_data.urls():
            if not url.isLocalFile():
                continue
            local_path = url.toLocalFile()
            if local_path and not QImage(local_path).isNull():
                return True
        return False

    @staticmethod
    def _image_from_mime_data(mime_data) -> Optional[QImage]:
        if mime_data is None or not mime_data.hasImage():
            return None
        data = mime_data.imageData()
        image = QImage()
        if isinstance(data, QImage):
            image = data
        elif isinstance(data, QPixmap):
            image = data.toImage()
        elif data is not None:
            try:
                image = QImage(data)
            except Exception:
                image = QImage()
        return image if not image.isNull() else None

    @staticmethod
    def _image_fingerprint(image: QImage) -> str:
        import hashlib
        ptr = image.bits()
        if ptr is not None:
            data = bytes(image.sizeInBytes())
            return hashlib.md5(data).hexdigest() + f":{image.width()}x{image.height()}"
        return f"{image.cacheKey()}:{image.width()}x{image.height()}"

    @staticmethod
    def _image_to_payload(image: QImage) -> Optional[dict[str, Any]]:
        return _encode_qimage_to_payload(image, "image/png")


def _encode_qimage_to_payload(image: QImage, mime_type: str = "image/png") -> Optional[dict[str, Any]]:
    if image.isNull():
        return None
    data = QByteArray()
    buf = QBuffer(data)
    if not buf.open(QIODevice.OpenModeFlag.WriteOnly):
        return None
    ok = image.save(buf, "PNG")
    buf.close()
    if not ok:
        return None
    return {
        "image_blob": bytes(data),
        "mime_type": str(mime_type or "image/png"),
        "width": image.width(),
        "height": image.height(),
    }


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


class MixedContentEdit(QTextEdit):
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

    @staticmethod
    def _mime_may_contain_images(mime_data) -> bool:
        if mime_data is None:
            return False
        if mime_data.hasImage():
            return True
        if not mime_data.hasUrls():
            return False
        for url in mime_data.urls():
            if not url.isLocalFile():
                continue
            local_path = url.toLocalFile()
            if local_path and not QImage(local_path).isNull():
                return True
        return False

    @staticmethod
    def _image_from_mime_data(mime_data) -> Optional[QImage]:
        if mime_data is None or not mime_data.hasImage():
            return None
        data = mime_data.imageData()
        image = QImage()
        if isinstance(data, QImage):
            image = data
        elif isinstance(data, QPixmap):
            image = data.toImage()
        elif data is not None:
            try:
                image = QImage(data)
            except Exception:
                image = QImage()
        return image if not image.isNull() else None

    @staticmethod
    def _image_fingerprint(image: QImage) -> str:
        import hashlib
        ptr = image.bits()
        if ptr is not None:
            data = bytes(image.sizeInBytes())
            return hashlib.md5(data).hexdigest() + f":{image.width()}x{image.height()}"
        return f"{image.cacheKey()}:{image.width()}x{image.height()}"

    @staticmethod
    def _image_to_payload(image: QImage) -> Optional[dict[str, Any]]:
        return _encode_qimage_to_payload(image, "image/png")


class BundleItemDialog(QDialog):
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
        self.setModal(True)
        self._images: list[dict[str, Any]] = list(initial_images or [])
        self._require_image = bool(require_image)
        self._note = (initial_note or "").strip()
        self._result_text = (initial_text or "").strip()
        self._result_images: list[dict[str, Any]] = list(initial_images or [])
        self._result_segments: list[dict[str, Any]] = []
        self._build_ui(initial_text)
        self._refresh_image_list()

    def _build_ui(self, initial_text: str) -> None:
        layout = QVBoxLayout(self)
        self.content_edit = MixedContentEdit(self)
        self.content_edit.setMinimumHeight(360)
        self.content_edit.set_initial_content(initial_text, self._images)
        layout.addWidget(self.content_edit)

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

    def _refresh_image_list(self) -> None:
        # Reserved for compatibility; content now renders directly inside mixed editor.
        return

    def _on_accept(self) -> None:
        self._result_segments = self.content_edit.segments()
        self._result_text, self._result_images = self.content_edit.content_parts()
        text = self._result_text
        has_images = len(self._result_images) > 0
        if not has_images and text == "":
            QMessageBox.warning(self, "提示", "请至少输入文字或添加一张图片。")
            return
        if self._require_image and not has_images:
            QMessageBox.warning(self, "提示", "该条目至少保留一张图片。")
            return
        self.accept()

    def result_text(self) -> str:
        return self._result_text

    def result_images(self) -> list[dict[str, Any]]:
        return list(self._result_images)

    def result_segments(self) -> list[dict[str, Any]]:
        return list(self._result_segments)

    def result_note(self) -> str:
        return self._note


class EditItemDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        item_type: str,
        initial_text: str = "",
        initial_note: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("编辑条目")
        self.setModal(True)
        self._item_type = item_type
        self._result_type = item_type
        self._image_bytes: bytes | None = None
        self._image_width = 0
        self._image_height = 0
        self._build_ui(initial_text, initial_note)

    def _build_ui(self, initial_text: str, initial_note: str) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("内容："))

        self.text_edit = QTextEdit(self)
        self.text_edit.setPlainText(initial_text)
        layout.addWidget(self.text_edit)

        self.image_info_label = QLabel("当前为文本模式。", self)
        self.image_info_label.setStyleSheet("color: #555;")
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
        # Local import to keep startup path unchanged.
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice
        from PySide6.QtWidgets import QApplication

        image = QApplication.clipboard().image()
        if image.isNull():
            QMessageBox.warning(self, "提示", "剪贴板中没有图片。")
            return
        data = QByteArray()
        buf = QBuffer(data)
        if not buf.open(QIODevice.OpenModeFlag.WriteOnly):
            QMessageBox.warning(self, "提示", "读取剪贴板图片失败。")
            return
        saved = image.save(buf, "PNG")
        buf.close()
        if not saved:
            QMessageBox.warning(self, "提示", "转换剪贴板图片失败。")
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
                QMessageBox.warning(self, "提示", "请先从剪贴板载入图片。")
                return
            self.accept()
            return
        if self.text_edit.toPlainText().strip() == "":
            QMessageBox.warning(self, "提示", "文本内容不能为空。")
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


class MultiSelectDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        title: str,
        prompt: str,
        options: list[tuple[str, str]],
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self._bulk_check_update = False
        layout = QVBoxLayout(self)
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
        layout.addWidget(self.option_list)
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
            QMessageBox.warning(self, "提示", "请至少选择一项。")
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


class AppearanceDialog(QDialog):
    _PRESET_COLORS: dict[str, tuple[str, str, str]] = {
        "简约浅灰": ("#F6F7FA", "#FFFFFF", "#CFE0F6"),
        "商务蓝灰": ("#EEF2F7", "#F9FBFF", "#B9D1F0"),
        "高对比": ("#FFFFFF", "#F4F7FC", "#A9CCFF"),
    }

    def __init__(
        self,
        parent: QWidget,
        current: AppearanceSettings,
        defaults: AppearanceSettings,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("外观设置")
        self.setModal(True)
        self._defaults = defaults
        self._window_bg = current.window_bg
        self._item_bg = current.item_bg
        self._item_selected_bg = current.item_selected_bg
        self._preview_cards: dict[str, QFrame] = {}
        self._preview_titles: dict[str, QLabel] = {}
        self._preview_samples: dict[str, QLabel] = {}
        self._build_ui(current)

    def _build_ui(self, current: AppearanceSettings) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        preview_container = QFrame(self)
        preview_container.setObjectName("appearancePreviewContainer")
        preview_container.setFrameShape(QFrame.Shape.StyledPanel)
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(10, 10, 10, 10)
        preview_layout.setSpacing(8)
        preview_layout.addWidget(QLabel("颜色预览", preview_container))

        preview_grid = QGridLayout()
        preview_grid.setHorizontalSpacing(8)
        preview_grid.setVerticalSpacing(8)
        preview_grid.addWidget(self._create_preview_card("window", "窗口背景", "主区域"), 0, 0)
        preview_grid.addWidget(self._create_preview_card("item", "正常条目", "未选中条目"), 0, 1)
        preview_grid.addWidget(self._create_preview_card("selected", "选中条目", "当前选中条目"), 1, 0)
        preview_grid.addWidget(self._create_preview_card("chrome", "菜单/标签/工具栏", "导航与菜单"), 1, 1)
        preview_layout.addLayout(preview_grid)
        layout.addWidget(preview_container)

        preset_row = QHBoxLayout()
        preset_row.setSpacing(6)
        preset_row.addWidget(QLabel("一键配色：", self))
        for preset_name in ("简约浅灰", "商务蓝灰", "高对比"):
            btn = QPushButton(preset_name, self)
            btn.clicked.connect(lambda _=False, name=preset_name: self._apply_preset(name))
            preset_row.addWidget(btn)
        preset_row.addStretch(1)
        layout.addLayout(preset_row)

        form = QFormLayout()
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.window_bg_btn = QPushButton(self)
        self.window_bg_btn.clicked.connect(lambda: self._pick_color("window_bg"))
        self._apply_color_preview(self.window_bg_btn, self._window_bg)
        form.addRow("背景颜色：", self.window_bg_btn)

        self.font_size_spin = QSpinBox(self)
        self.font_size_spin.setRange(10, 28)
        self.font_size_spin.setValue(int(current.font_size))
        form.addRow("全局字体大小：", self.font_size_spin)

        self.item_bg_btn = QPushButton(self)
        self.item_bg_btn.clicked.connect(lambda: self._pick_color("item_bg"))
        self._apply_color_preview(self.item_bg_btn, self._item_bg)
        form.addRow("正常条目背景：", self.item_bg_btn)

        self.item_selected_bg_btn = QPushButton(self)
        self.item_selected_bg_btn.clicked.connect(lambda: self._pick_color("item_selected_bg"))
        self._apply_color_preview(self.item_selected_bg_btn, self._item_selected_bg)
        form.addRow("选中条目背景：", self.item_selected_bg_btn)

        layout.addLayout(form)

        self.show_scrollbar_chk = QCheckBox("显示滚动条", self)
        self.show_scrollbar_chk.setChecked(bool(current.show_scrollbar))
        layout.addWidget(self.show_scrollbar_chk)

        self.antialias_chk = QCheckBox("条目抗锯齿", self)
        self.antialias_chk.setChecked(bool(current.item_antialias))
        layout.addWidget(self.antialias_chk)

        buttons_row = QHBoxLayout()
        buttons_row.addStretch(1)
        self.reset_btn = QPushButton("重置默认", self)
        self.reset_btn.clicked.connect(self._reset_defaults)
        buttons_row.addWidget(self.reset_btn)
        layout.addLayout(buttons_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        apply_btn = buttons.button(QDialogButtonBox.StandardButton.Apply)
        if apply_btn is not None:
            apply_btn.setText("应用")
            apply_btn.clicked.connect(self.accept)
            apply_btn.setDefault(True)
        cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_btn is not None:
            cancel_btn.setText("取消")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._refresh_preview_cards()

    def _create_preview_card(self, key: str, title: str, sample: str) -> QFrame:
        card = QFrame(self)
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(8, 8, 8, 8)
        card_layout.setSpacing(4)

        title_label = QLabel(title, card)
        sample_label = QLabel(sample, card)
        card_layout.addWidget(title_label)
        card_layout.addWidget(sample_label)

        self._preview_cards[key] = card
        self._preview_titles[key] = title_label
        self._preview_samples[key] = sample_label
        return card

    def _pick_color(self, key: str) -> None:
        current_value = self._window_bg if key == "window_bg" else (
            self._item_bg if key == "item_bg" else self._item_selected_bg
        )
        color = QColorDialog.getColor(QColor(current_value), self, "选择颜色")
        if not color.isValid():
            return
        value = color.name()
        if key == "window_bg":
            self._window_bg = value
            self._apply_color_preview(self.window_bg_btn, value)
        elif key == "item_bg":
            self._item_bg = value
            self._apply_color_preview(self.item_bg_btn, value)
        else:
            self._item_selected_bg = value
            self._apply_color_preview(self.item_selected_bg_btn, value)
        self._refresh_preview_cards()

    def _reset_defaults(self) -> None:
        self._window_bg = self._defaults.window_bg
        self._item_bg = self._defaults.item_bg
        self._item_selected_bg = self._defaults.item_selected_bg
        self.font_size_spin.setValue(int(self._defaults.font_size))
        self.show_scrollbar_chk.setChecked(bool(self._defaults.show_scrollbar))
        self.antialias_chk.setChecked(bool(self._defaults.item_antialias))
        self._apply_color_preview(self.window_bg_btn, self._window_bg)
        self._apply_color_preview(self.item_bg_btn, self._item_bg)
        self._apply_color_preview(self.item_selected_bg_btn, self._item_selected_bg)
        self._refresh_preview_cards()

    def _apply_preset(self, preset_name: str) -> None:
        colors = self._PRESET_COLORS.get(preset_name)
        if colors is None:
            return
        self._window_bg, self._item_bg, self._item_selected_bg = colors
        self._apply_color_preview(self.window_bg_btn, self._window_bg)
        self._apply_color_preview(self.item_bg_btn, self._item_bg)
        self._apply_color_preview(self.item_selected_bg_btn, self._item_selected_bg)
        self._refresh_preview_cards()

    def _refresh_preview_cards(self) -> None:
        chrome_bg = self._mix_colors(self._window_bg, self._item_selected_bg, 0.35)
        self._apply_preview_card("window", self._window_bg)
        self._apply_preview_card("item", self._item_bg)
        self._apply_preview_card("selected", self._item_selected_bg)
        self._apply_preview_card("chrome", chrome_bg)

    def _apply_preview_card(self, key: str, color_hex: str) -> None:
        card = self._preview_cards.get(key)
        title = self._preview_titles.get(key)
        sample = self._preview_samples.get(key)
        if card is None or title is None or sample is None:
            return
        text_color = self._best_text_color(color_hex)
        border_color = self._border_color(color_hex)
        card.setStyleSheet(
            "QFrame {"
            f"background: {color_hex};"
            f"border: 1px solid {border_color};"
            "border-radius: 6px;"
            "}"
        )
        title.setStyleSheet(f"border: none; color: {text_color}; font-weight: 600; background: transparent;")
        sample.setStyleSheet(f"border: none; color: {text_color}; background: transparent;")

    @staticmethod
    def _apply_color_preview(button: QPushButton, color_hex: str) -> None:
        text_color = AppearanceDialog._best_text_color(color_hex)
        border_color = AppearanceDialog._border_color(color_hex)
        button.setText(color_hex.upper())
        button.setStyleSheet(
            "text-align: left; padding-left: 10px; border-radius: 6px;"
            f"background: {color_hex};"
            f"border: 1px solid {border_color};"
            f"color: {text_color};"
        )

    @staticmethod
    def _best_text_color(color_hex: str) -> str:
        color = QColor(color_hex)
        if not color.isValid():
            return "#1f2937"
        luminance = (0.299 * color.redF()) + (0.587 * color.greenF()) + (0.114 * color.blueF())
        return "#111827" if luminance >= 0.62 else "#F9FAFB"

    @staticmethod
    def _border_color(color_hex: str) -> str:
        color = QColor(color_hex)
        if not color.isValid():
            return "#B7C3D4"
        return color.darker(120).name()

    @staticmethod
    def _mix_colors(left_hex: str, right_hex: str, ratio: float) -> str:
        left = QColor(left_hex)
        right = QColor(right_hex)
        if not left.isValid():
            left = QColor("#F6F7FA")
        if not right.isValid():
            right = QColor("#CFE0F6")
        clamped = max(0.0, min(1.0, float(ratio)))
        red = int(left.red() * (1.0 - clamped) + right.red() * clamped)
        green = int(left.green() * (1.0 - clamped) + right.green() * clamped)
        blue = int(left.blue() * (1.0 - clamped) + right.blue() * clamped)
        return QColor(red, green, blue).name()

    def result_appearance(self) -> AppearanceSettings:
        return AppearanceSettings(
            window_bg=self._window_bg,
            font_size=int(self.font_size_spin.value()),
            item_bg=self._item_bg,
            item_selected_bg=self._item_selected_bg,
            show_scrollbar=bool(self.show_scrollbar_chk.isChecked()),
            item_antialias=bool(self.antialias_chk.isChecked()),
        )


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
    hotkey_change_requested = Signal(str)
    hotkey_reset_requested = Signal()
    capture_tab_change_requested = Signal(int)
    note_color_change_requested = Signal(str)
    note_font_size_change_requested = Signal(int)
    export_requested = Signal()
    import_requested = Signal()
    search_text_changed = Signal(str)
    splitter_sizes_changed = Signal(str)
    appearance_change_requested = Signal(object)
    item_order_changed = Signal(list, int)
    move_items_requested = Signal(list, int)
    start_inline_edit_requested = Signal(int)
    save_inline_edit_requested = Signal(int, object)
    autostart_change_requested = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(980, 620)
        self._apply_app_icon()
        self._hotkey_text = ""
        self._capture_tab_text = "未设置"
        self._capture_tab_id: Optional[int] = None
        self._note_text_color = "#1f2937"
        self._note_font_size = 13
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
        self._item_render_generation = 0
        self._pending_render_items: list[ClipItem] = []
        self._pending_render_index = 0
        self._pending_render_search_mode = False
        self._pending_render_tab_name_map: dict[int, str] = {}
        self._pending_render_restore_id: Optional[int] = None
        self._pending_render_drag_enabled = True
        self._pending_render_file_icon_provider: Optional[QFileIconProvider] = None
        self._pending_render_started_at = 0.0
        self._pending_render_first_batch_logged = False
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
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._main_splitter.setChildrenCollapsible(True)
        self._main_splitter.setHandleWidth(8)
        self._main_splitter.splitterMoved.connect(self._on_main_splitter_moved)
        outer.addWidget(self._main_splitter)

        left = QWidget()
        left.setObjectName("leftPanel")
        left.setMinimumWidth(0)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(18, 18, 14, 14)
        left_layout.setSpacing(12)

        brand = QHBoxLayout()
        brand.setSpacing(10)
        app_icon = QLabel()
        app_icon.setObjectName("appIconBadge")
        app_icon.setFixedSize(QSize(36, 36))
        app_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_pixmap = self.windowIcon().pixmap(QSize(26, 26))
        if not icon_pixmap.isNull():
            app_icon.setPixmap(icon_pixmap)
        else:
            app_icon.setText("C")
        brand_text = QVBoxLayout()
        brand_text.setSpacing(1)
        app_name = QLabel("ClipNest")
        app_name.setObjectName("appNameLabel")
        app_subtitle = QLabel("本地剪贴板")
        app_subtitle.setObjectName("appSubtitleLabel")
        brand_text.addWidget(app_name)
        brand_text.addWidget(app_subtitle)
        brand_text.addStretch(1)
        brand.addWidget(app_icon)
        brand.addLayout(brand_text, 1)
        left_layout.addLayout(brand)

        section_label = QLabel("标签页")
        section_label.setObjectName("sidebarSectionLabel")
        left_layout.addWidget(section_label)

        self.tab_list = DragAutoScrollListWidget()
        self.tab_list.setObjectName("tabList")
        self.tab_list.setMinimumWidth(0)
        self.tab_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tab_list.setDragEnabled(True)
        self.tab_list.setAcceptDrops(True)
        self.tab_list.setDropIndicatorShown(True)
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
        right_layout.setContentsMargins(20, 18, 20, 18)
        right_layout.setSpacing(12)

        tools = QHBoxLayout()
        tools.setSpacing(6)
        self.add_item_btn = QPushButton("新建条目")
        self.add_item_btn.setObjectName("primaryButton")
        self.search_input = QLineEdit(self)
        self.search_input.setObjectName("globalSearchInput")
        self.search_input.setPlaceholderText("搜索全部条目...")
        self.search_input.setClearButtonEnabled(False)
        self.search_input.setMinimumWidth(280)
        self.clear_search_btn = QPushButton("清空", self)
        self.clear_search_btn.setObjectName("secondaryButton")
        self.clear_search_btn.setVisible(False)
        self.settings_button = QToolButton()
        self.settings_button.setObjectName("settingsButton")
        self.settings_button.setText("⚙")
        self.settings_button.setToolTip("设置")
        self.settings_button.setFixedSize(QSize(38, 32))
        tools.addWidget(self.add_item_btn)
        tools.addWidget(self.search_input, 1)
        tools.addWidget(self.clear_search_btn)
        tools.addStretch(1)
        tools.addWidget(self.settings_button)
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
            note_color=self._note_text_color,
            note_font_size=self._note_font_size,
            tokens=self._theme_tokens,
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
        self.tab_list.customContextMenuRequested.connect(self._open_tab_context_menu)
        self.add_item_btn.clicked.connect(self._prompt_add_item)
        self.search_input.textChanged.connect(self._on_search_input_changed)
        self.clear_search_btn.clicked.connect(self._clear_search)
        self.item_list.itemClicked.connect(self._on_item_clicked)
        self.item_list.currentItemChanged.connect(self._on_item_current_changed)
        self.item_list.customContextMenuRequested.connect(self._open_item_context_menu)
        self.item_list.items_reordered.connect(self._on_item_rows_moved)
        self.inline_save_btn.clicked.connect(self._on_inline_edit_save_clicked)
        self.inline_cancel_btn.clicked.connect(self.hide_inline_editor)
        self._build_settings_menu()
        self._apply_theme()

    def _build_settings_menu(self) -> None:
        self.settings_menu = QMenu(self)
        self.settings_menu.setObjectName("glassMenu")
        self.action_current_hotkey = QAction("当前快捷键：未设置", self)
        self.action_current_hotkey.setEnabled(False)
        self.action_capture_tab = QAction(f"监听存储标签：{self._capture_tab_text}", self)
        self.action_capture_tab.setEnabled(False)
        self.action_note_style = QAction("备注样式：#1f2937 / 13px", self)
        self.action_note_style.setEnabled(False)
        self.action_set_hotkey = QAction("设置全局快捷键...", self)
        self.action_set_capture_tab = QAction("设置监听存储标签...", self)
        self.action_set_note_color = QAction("设置备注文字颜色...", self)
        self.action_set_note_font_size = QAction("设置备注文字大小...", self)
        self.action_export_data = QAction("导出标签页与条目...", self)
        self.action_import_data = QAction("导入标签页与条目...", self)
        self.action_reset_hotkey = QAction("恢复默认快捷键", self)
        self.action_autostart = QAction("开机自启动", self)
        self.action_autostart.setCheckable(True)
        self.action_autostart.setChecked(False)

        self.settings_menu.addAction(self.action_current_hotkey)
        self.settings_menu.addAction(self.action_capture_tab)
        self.settings_menu.addAction(self.action_note_style)
        self.settings_menu.addSeparator()
        self.settings_menu.addAction(self.action_set_hotkey)
        self.settings_menu.addAction(self.action_set_capture_tab)
        self.settings_menu.addAction(self.action_set_note_color)
        self.settings_menu.addAction(self.action_set_note_font_size)
        self.settings_menu.addSeparator()
        self.settings_menu.addAction(self.action_export_data)
        self.settings_menu.addAction(self.action_import_data)
        self.settings_menu.addSeparator()
        self.settings_menu.addAction(self.action_autostart)
        self.settings_menu.addSeparator()
        self.settings_menu.addAction(self.action_reset_hotkey)
        self.settings_menu.setStyleSheet(self._menu_stylesheet())
        self.settings_button.clicked.connect(self._show_settings_menu)

        self.action_set_hotkey.triggered.connect(self._prompt_hotkey_dialog)
        self.action_set_capture_tab.triggered.connect(self._prompt_capture_tab_dialog)
        self.action_set_note_color.triggered.connect(self._prompt_note_color_dialog)
        self.action_set_note_font_size.triggered.connect(self._prompt_note_font_size_dialog)
        self.action_export_data.triggered.connect(self.export_requested.emit)
        self.action_import_data.triggered.connect(self.import_requested.emit)
        self.action_reset_hotkey.triggered.connect(self.hotkey_reset_requested.emit)
        self.action_autostart.triggered.connect(self._on_autostart_toggled)

    def set_autostart_state(self, enabled: bool) -> None:
        self.action_autostart.setChecked(enabled)

    def _on_autostart_toggled(self, checked: bool) -> None:
        self.autostart_change_requested.emit(checked)

    def _show_settings_menu(self) -> None:
        button_pos = self.settings_button.mapToGlobal(self.settings_button.rect().bottomLeft())
        with self._with_auto_hide_suspended():
            self.settings_menu.exec(button_pos)

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
        self.item_list.set_reorder_enabled(False if len(items) > 50 else drag_enabled)
        self._suppress_item_reorder_emit = True
        self.item_list.clear()
        self._pending_render_items = list(items)
        self._pending_render_index = 0
        self._pending_render_search_mode = bool(search_mode)
        self._pending_render_tab_name_map = dict(tab_name_map or {})
        self._pending_render_restore_id = self._last_selected_item_id
        self._pending_render_drag_enabled = drag_enabled
        self._pending_render_file_icon_provider = QFileIconProvider()
        self._pending_render_started_at = time.perf_counter()
        self._pending_render_first_batch_logged = False
        try:
            self._append_item_batch(50)
        finally:
            if self._pending_render_index >= len(self._pending_render_items):
                self._finish_item_render()
            else:
                self._item_render_timer.start(1)

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
            logger.info(
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
        logger.info(
            "[Perf] item_list render_done total=%s search_mode=%s ms=%.1f",
            total,
            self._pending_render_search_mode,
            elapsed_ms,
        )

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
            pixmap = QPixmap()
            if pixmap.loadFromData(item.thumb_blob, "PNG"):
                icon = QIcon(pixmap)
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
        lw_item.setData(
            ITEM_TYPE_LABEL_ROLE,
            f"置顶 · {row.type_label}" if item.pinned else row.type_label,
        )
        lw_item.setData(ITEM_PINNED_ROLE, bool(item.pinned))
        return lw_item

    def prepend_item(self, item: ClipItem) -> None:
        if self._item_list_search_mode:
            return
        lw_item = self._create_list_item(item, search_mode=False)
        self.item_list.insertItem(0, lw_item)

    def _on_search_input_changed(self, _text: str) -> None:
        has_text = self.search_input.text().strip() != ""
        self.clear_search_btn.setVisible(has_text)
        self._search_debounce_timer.start()

    def _emit_search_text_changed(self) -> None:
        self.search_text_changed.emit(self.search_input.text().strip())

    def _clear_search(self) -> None:
        self.search_input.clear()

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
        self.action_current_hotkey.setText(f"当前快捷键：{hotkey_text}")

    def set_capture_tab(self, capture_tab_id: Optional[int], capture_tab_text: str) -> None:
        self._capture_tab_id = capture_tab_id
        self._capture_tab_text = capture_tab_text
        self.action_capture_tab.setText(f"监听存储标签：{capture_tab_text}")

    def current_appearance(self) -> AppearanceSettings:
        return self._appearance

    def set_appearance(self, appearance: AppearanceSettings) -> None:
        self._appearance = appearance
        self._theme_tokens = build_theme_tokens_from_appearance(appearance)
        if self._item_delegate is not None:
            self._item_delegate.set_theme_tokens(self._theme_tokens)
            self._item_delegate.set_antialias_enabled(appearance.item_antialias)
        self._apply_theme()
        self.item_list.viewport().update()

    def set_note_style(self, color_hex: str, font_size: int) -> None:
        self._note_text_color = color_hex
        self._note_font_size = font_size
        self.action_note_style.setText(f"备注样式：{color_hex} / {font_size}px")
        if self._item_delegate is not None:
            self._item_delegate.set_note_style(color_hex, font_size)
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
        self._suspend_auto_hide_for(1500)
        self.show()
        self.setWindowState(
            (self.windowState() & ~Qt.WindowState.WindowMinimized) | Qt.WindowState.WindowActive
        )
        self.raise_()
        self.activateWindow()
        logger.info(
            "[UI] show_for_quick_paste post-show visible=%s active=%s minimized=%s",
            self.isVisible(),
            self.isActiveWindow(),
            bool(self.windowState() & Qt.WindowState.WindowMinimized),
        )
        if sys.platform == "win32":
            self._force_foreground_windows()
            # Retry sequence to improve reliability when foreground lock blocks first attempt.
            QTimer.singleShot(60, self._force_foreground_windows)
            QTimer.singleShot(180, self._force_foreground_windows)
        if self.item_list.count() > 0:
            self.item_list.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
        QTimer.singleShot(260, self._ensure_hotkey_window_visible)

    def _release_auto_hide_suspend(self) -> None:
        self._auto_hide_suspend_count = max(0, self._auto_hide_suspend_count - 1)

    def _suspend_auto_hide_for(self, milliseconds: int) -> None:
        self._auto_hide_suspend_count += 1
        QTimer.singleShot(max(10, int(milliseconds)), self._release_auto_hide_suspend)

    def _ensure_hotkey_window_visible(self) -> None:
        logger.info(
            "[UI] ensure_hotkey_window_visible visible=%s active=%s",
            self.isVisible(),
            self.isActiveWindow(),
        )
        if not self.isVisible():
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
        if not self.isVisible() or self.isActiveWindow():
            return
        if self._tray_icon is None or not self._tray_icon.isVisible():
            return
        self._tray_icon.showMessage(
            APP_NAME,
            f"热键已触发，但系统拦截了前台切换。请点击任务栏中的 {APP_NAME}。",
            QSystemTrayIcon.MessageIcon.Information,
            2500,
        )

    def _force_foreground_windows(self) -> None:
        if sys.platform != "win32":
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
        return self.isVisible() and not bool(self.windowState() & Qt.WindowState.WindowMinimized)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._allow_close or self._tray_icon is None or not self._tray_icon.isVisible():
            event.accept()
            return
        event.ignore()
        self.hide()
        self._show_tray_hint_once()

    def confirm(self, title: str, message: str) -> bool:
        answer = QMessageBox.question(self, title, message)
        return answer == QMessageBox.StandardButton.Yes

    def show_error(self, message: str) -> None:
        QMessageBox.warning(self, "提示", message)

    def show_info(self, message: str) -> None:
        QMessageBox.information(self, "提示", message)

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.WindowDeactivate:
            QTimer.singleShot(0, self._hide_on_deactivate)
        return super().event(event)

    def eventFilter(self, watched, event: QEvent) -> bool:
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
        return super().eventFilter(watched, event)

    def _on_item_list_enter_pressed(self) -> None:
        focus_widget = QApplication.focusWidget()
        if focus_widget not in (self.item_list, self.item_list.viewport()):
            return
        self._activate_current_item()

    def _hide_on_deactivate(self) -> None:
        if self._auto_hide_suspend_count > 0:
            return
        if self._allow_close:
            return
        if self._tray_icon is None or not self._tray_icon.isVisible():
            return
        if not self.isVisible():
            return
        if bool(self.windowState() & Qt.WindowState.WindowMinimized):
            return
        if self.isActiveWindow():
            return
        if QApplication.activeModalWidget() is not None:
            return
        self.hide()

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
        show_action = self._tray_menu.addAction("显示主界面")
        exit_action = self._tray_menu.addAction("退出程序")
        show_action.triggered.connect(self.show_for_quick_paste)
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
        add_action = menu.addAction("新增标签页")
        rename_action = menu.addAction("重命名标签页")
        delete_action = menu.addAction("删除标签页")

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

    def _prompt_add_tab(self) -> None:
        with self._with_auto_hide_suspended():
            text, ok = QInputDialog.getText(self, "新增标签页", "标签页名称：")
        if ok and text.strip():
            self.create_tab_requested.emit(text)

    def _prompt_rename_tab(self) -> None:
        tab_id = self.current_tab_id()
        if tab_id is None:
            return
        current = self.tab_list.currentItem()
        current_name = current.text() if current else ""
        with self._with_auto_hide_suspended():
            text, ok = QInputDialog.getText(self, "重命名标签页", "新名称：", text=current_name)
        if ok and text.strip():
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

    def _prompt_capture_tab_dialog(self) -> None:
        if not self._tabs_snapshot:
            self.show_error("当前没有可用标签页。")
            return
        tab_names = [tab.name for tab in self._tabs_snapshot]
        current_idx = 0
        for idx, tab in enumerate(self._tabs_snapshot):
            if tab.id == self._capture_tab_id:
                current_idx = idx
                break
        with self._with_auto_hide_suspended():
            selected_name, ok = QInputDialog.getItem(
                self,
                "设置监听存储标签",
                "自动监听内容将保存到：",
                tab_names,
                current_idx,
                False,
            )
        if not ok:
            return
        for tab in self._tabs_snapshot:
            if tab.name == selected_name:
                self.capture_tab_change_requested.emit(tab.id)
                return

    def _prompt_note_color_dialog(self) -> None:
        with self._with_auto_hide_suspended():
            color = QColorDialog.getColor(
                QColor(self._note_text_color),
                self,
                "设置备注文字颜色",
            )
        if not color.isValid():
            return
        self.note_color_change_requested.emit(color.name())

    def _prompt_note_font_size_dialog(self) -> None:
        with self._with_auto_hide_suspended():
            value, ok = QInputDialog.getInt(
                self,
                "设置备注文字大小",
                "字号（px）：",
                self._note_font_size,
                10,
                28,
                1,
            )
        if not ok:
            return
        self.note_font_size_change_requested.emit(value)

    def _prompt_appearance_dialog(self) -> None:
        dialog = AppearanceDialog(
            self,
            current=self._appearance,
            defaults=default_appearance_settings(),
        )
        if self._exec_modal_dialog(dialog) != QDialog.DialogCode.Accepted:
            return
        self.appearance_change_requested.emit(dialog.result_appearance())

    def _prompt_hotkey_dialog(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("设置全局快捷键")
        dialog.setModal(True)
        dialog_layout = QVBoxLayout(dialog)

        tip = QLabel("请按下新的全局快捷键组合（例如 Ctrl+Shift+V）：")
        tip.setWordWrap(True)
        dialog_layout.addWidget(tip)

        key_edit = QKeySequenceEdit(dialog)
        key_edit.setMaximumSequenceLength(1)
        if self._hotkey_text:
            key_edit.setKeySequence(QKeySequence(self._hotkey_text))
        dialog_layout.addWidget(key_edit)

        hint = QLabel("要求：至少一个修饰键 + 一个主键。")
        hint.setStyleSheet("color: #555;")
        dialog_layout.addWidget(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setText("确定")
        cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_btn is not None:
            cancel_btn.setText("取消")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        dialog_layout.addWidget(buttons)

        if self._exec_modal_dialog(dialog) != QDialog.DialogCode.Accepted:
            return
        seq = key_edit.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
        self.hotkey_change_requested.emit(seq)

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

    def _activate_item(self, item: Optional[QListWidgetItem]) -> bool:
        if item is None:
            return False
        item_id = item.data(ITEM_ID_ROLE)
        if item_id is None:
            return False
        self._last_selected_item_id = int(item_id)
        self.item_activated.emit(int(item_id))
        return True

    def _activate_current_item(self) -> bool:
        return self._activate_item(self.item_list.currentItem())

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        self._activate_item(item)

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
            pin_action = menu.addAction("取消置顶" if is_pinned else "置顶条目")
            edit_action = menu.addAction("编辑条目")
            edit_note_action = menu.addAction("编辑备注")
            move_menu = menu.addMenu("移动到")
            move_menu.setObjectName("glassMenu")
            move_menu.setStyleSheet(self._menu_stylesheet())
            move_actions: dict[QAction, int] = {}
            for tab in self._tabs_snapshot:
                tab_action = move_menu.addAction(tab.name)
                move_actions[tab_action] = int(tab.id)
            delete_action = menu.addAction("删除条目")
            menu.addSeparator()
            clear_action = menu.addAction("清空列表")
            with self._with_auto_hide_suspended():
                selected = menu.exec(self.item_list.mapToGlobal(pos))
            if selected == pin_action:
                self.item_pin_change_requested.emit(item_id, not is_pinned)
            elif selected == edit_action:
                self.start_inline_edit_requested.emit(item_id)
            elif edit_note_action is not None and selected == edit_note_action:
                current_note = str(item.data(ITEM_NOTE_ROLE) or "")
                with self._with_auto_hide_suspended():
                    note, ok = QInputDialog.getMultiLineText(
                        self,
                        "编辑备注",
                        "",
                        current_note,
                    )
                if ok:
                    self.edit_note_requested.emit(item_id, note.strip())
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
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(app_stylesheet)
        else:
            self.setStyleSheet(app_stylesheet)
        self.settings_menu.setStyleSheet(self._menu_stylesheet())
        if self._tray_menu is not None:
            self._tray_menu.setStyleSheet(self._menu_stylesheet())

    def _apply_light_theme(self) -> None:
        # Backward-compatible alias.
        self._apply_theme()

    def _menu_stylesheet(self) -> str:
        return build_menu_stylesheet(self._theme_tokens)


