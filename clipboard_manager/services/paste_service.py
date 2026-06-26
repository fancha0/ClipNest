from __future__ import annotations

import sys
from typing import Callable, Optional

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QTimer, Qt, QUrl
from PySide6.QtGui import QClipboard, QImage, QPainter
from PySide6.QtCore import QMimeData
from pynput.keyboard import Controller, Key

from .clipboard_service import ClipboardService
from .focus_service import FocusService, FocusTarget


class PasteService:
    def __init__(
        self,
        clipboard: QClipboard,
        clipboard_service: ClipboardService,
        focus_service: FocusService,
    ) -> None:
        self._clipboard = clipboard
        self._clipboard_service = clipboard_service
        self._focus_service = focus_service
        self._keyboard = Controller()

    def paste_text(
        self,
        text: str,
        target: Optional[FocusTarget],
        hide_window: Optional[Callable[[], None]] = None,
    ) -> bool:
        if text.strip() == "":
            return False

        self._clipboard_service.suspend_once_for_text(text)
        self._clipboard.setText(text)

        if hide_window:
            hide_window()

        if target:
            QTimer.singleShot(80, lambda: self._restore_and_paste(target))
        else:
            QTimer.singleShot(80, self._send_paste_shortcut)
        return True

    def paste_html(
        self,
        html_text: str,
        plain_text: str,
        target: Optional[FocusTarget],
        hide_window: Optional[Callable[[], None]] = None,
    ) -> bool:
        html_value = (html_text or "").strip()
        plain_value = (plain_text or "").strip()
        if not html_value and not plain_value:
            return False

        mime = QMimeData()
        if html_value:
            mime.setHtml(html_value)
        if plain_value:
            mime.setText(plain_value)
        elif html_value:
            # Basic fallback for targets that only use plain text.
            mime.setText(html_value)

        self._clipboard_service.suspend_once_for_snapshot()
        self._clipboard.setMimeData(mime)

        if hide_window:
            hide_window()

        if target:
            QTimer.singleShot(80, lambda: self._restore_and_paste(target))
        else:
            QTimer.singleShot(80, self._send_paste_shortcut)
        return True

    def paste_image(
        self,
        image_bytes: bytes,
        target: Optional[FocusTarget],
        hide_window: Optional[Callable[[], None]] = None,
    ) -> bool:
        if not image_bytes:
            return False
        image = QImage()
        if not image.loadFromData(image_bytes, "PNG"):
            return False

        self._clipboard_service.suspend_once_for_image(image_bytes)
        self._clipboard.setImage(image)

        if hide_window:
            hide_window()

        if target:
            QTimer.singleShot(80, lambda: self._restore_and_paste(target))
        else:
            QTimer.singleShot(80, self._send_paste_shortcut)
        return True

    def paste_files(
        self,
        file_paths: list[str],
        target: Optional[FocusTarget],
        hide_window: Optional[Callable[[], None]] = None,
    ) -> bool:
        clean_paths = [str(p).strip() for p in file_paths if str(p).strip()]
        if not clean_paths:
            return False

        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(path) for path in clean_paths])
        # Extra text fallback keeps compatibility in apps that ignore file object paste.
        mime.setText("\n".join(clean_paths))

        self._clipboard_service.suspend_once_for_snapshot()
        self._clipboard.setMimeData(mime)

        if hide_window:
            hide_window()

        if target:
            QTimer.singleShot(80, lambda: self._restore_and_paste(target))
        else:
            QTimer.singleShot(80, self._send_paste_shortcut)
        return True

    def paste_bundle(
        self,
        text: str,
        image_bytes_list: list[bytes],
        target: Optional[FocusTarget],
        hide_window: Optional[Callable[[], None]] = None,
    ) -> bool:
        clean_text = (text or "").strip()
        if len(image_bytes_list) == 0 and clean_text == "":
            return False
        if len(image_bytes_list) == 0:
            return self.paste_text(clean_text, target, hide_window)

        composed = self._compose_images_vertically(image_bytes_list)
        if composed is None:
            return False
        _composed_image, png_bytes = composed

        # Compatibility-first path: text paste first, then image paste.
        if clean_text == "":
            return self.paste_image(png_bytes, target, hide_window=hide_window)

        text_payload = clean_text if clean_text.endswith("\n") else f"{clean_text}\n"
        self._clipboard_service.suspend_once_for_text(text_payload)
        self._clipboard.setText(text_payload)

        if hide_window:
            hide_window()

        def paste_image_stage() -> None:
            image = QImage()
            if not image.loadFromData(png_bytes, "PNG"):
                return
            self._clipboard_service.suspend_once_for_image(png_bytes)
            self._clipboard.setImage(image)
            self._send_paste_shortcut()

        if target:
            def flow() -> None:
                restored = self._focus_service.restore_target(target)
                first_delay = 150 if restored else 20
                QTimer.singleShot(first_delay, self._send_paste_shortcut)
                QTimer.singleShot(first_delay + 180, paste_image_stage)

            QTimer.singleShot(80, flow)
        else:
            QTimer.singleShot(80, self._send_paste_shortcut)
            QTimer.singleShot(260, paste_image_stage)
        return True

    def paste_raw_snapshot(
        self,
        mime_parts: list,
        target: Optional[FocusTarget],
        hide_window: Optional[Callable[[], None]] = None,
    ) -> bool:
        if not mime_parts:
            return False

        mime = QMimeData()
        for part in mime_parts:
            mime_type = str(getattr(part, "mime_type", "") or part.get("mime_type", ""))
            payload = getattr(part, "payload_blob", None)
            if payload is None:
                payload = part.get("payload_blob", b"")
            payload_bytes = bytes(payload)
            if not mime_type:
                continue
            mime.setData(mime_type, QByteArray(payload_bytes))

        if not mime.formats():
            return False

        self._clipboard_service.suspend_once_for_snapshot()
        self._clipboard.setMimeData(mime)

        if hide_window:
            hide_window()

        if target:
            QTimer.singleShot(80, lambda: self._restore_and_paste(target))
        else:
            QTimer.singleShot(80, self._send_paste_shortcut)
        return True

    def _restore_and_paste(self, target: FocusTarget) -> None:
        restored = self._focus_service.restore_target(target)
        delay = 150 if restored else 20
        QTimer.singleShot(delay, self._send_paste_shortcut)

    def _send_paste_shortcut(self) -> None:
        modifier = Key.cmd if sys.platform == "darwin" else Key.ctrl
        try:
            with self._keyboard.pressed(modifier):
                self._keyboard.press("v")
                self._keyboard.release("v")
        except Exception:
            # Swallow errors to avoid breaking UI flow when OS-level permissions are missing.
            return

    @staticmethod
    def _compose_images_vertically(image_bytes_list: list[bytes]) -> tuple[QImage, bytes] | None:
        images: list[QImage] = []
        for payload in image_bytes_list:
            image = QImage()
            if not image.loadFromData(payload):
                continue
            images.append(image)
        if len(images) == 0:
            return None

        spacing = 8
        canvas_width = max(img.width() for img in images)
        canvas_height = sum(img.height() for img in images) + spacing * (len(images) - 1)
        canvas = QImage(canvas_width, canvas_height, QImage.Format.Format_ARGB32)
        canvas.fill(Qt.GlobalColor.white)

        painter = QPainter(canvas)
        y = 0
        for img in images:
            painter.drawImage(0, y, img)
            y += img.height() + spacing
        painter.end()

        data = QByteArray()
        buf = QBuffer(data)
        if not buf.open(QIODevice.OpenModeFlag.WriteOnly):
            return None
        ok = canvas.save(buf, "PNG")
        buf.close()
        if not ok:
            return None
        return canvas, bytes(data)
