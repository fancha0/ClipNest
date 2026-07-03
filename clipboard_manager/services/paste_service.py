from __future__ import annotations

import html as html_lib
import hashlib
import tempfile
import sys
import uuid
from pathlib import Path
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
        self._temp_image_cache: dict[str, Path] = {}

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

        if clean_text == "":
            return self.paste_image(png_bytes, target, hide_window=hide_window)

        rich_segments: list[dict] = [{"type": "text", "content": text}]
        for image_bytes in image_bytes_list:
            rich_segments.append({"type": "image", "image_blob": image_bytes})
        if self.paste_mixed_segments(rich_segments, target, hide_window=hide_window):
            return True

        # Compatibility fallback: text paste first, then image paste.
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
            QTimer.singleShot(120, self._send_paste_shortcut)

        if target:
            def flow() -> None:
                restored = self._focus_service.restore_target(target)
                first_delay = 150 if restored else 20
                QTimer.singleShot(first_delay, self._send_paste_shortcut)
                QTimer.singleShot(first_delay + 220, paste_image_stage)

            QTimer.singleShot(80, flow)
        else:
            QTimer.singleShot(80, self._send_paste_shortcut)
            QTimer.singleShot(300, paste_image_stage)
        return True

    def paste_mixed_segments(
        self,
        segments: list[dict],
        target: Optional[FocusTarget],
        hide_window: Optional[Callable[[], None]] = None,
    ) -> bool:
        if hide_window:
            hide_window()
        QTimer.singleShot(30, lambda: self._paste_mixed_segments_after_hide(segments, target))
        return True

    def prepare_mixed_segments(self, segments: list[dict]) -> None:
        self._build_mixed_rich_payload(segments)

    def _paste_mixed_segments_after_hide(
        self,
        segments: list[dict],
        target: Optional[FocusTarget],
    ) -> None:
        stages = self._build_mixed_paste_stages(segments)
        if len(stages) == 0:
            return

        if len(stages) == 1:
            stage_type, payload = stages[0]
            if stage_type == "text":
                self.paste_text(str(payload), target)
                return
            self.paste_image(bytes(payload), target)
            return

        if self._paste_mixed_as_rich_html(segments, target):
            return

        if target:
            def flow() -> None:
                restored = self._focus_service.restore_target(target)
                delay = 150 if restored else 20
                QTimer.singleShot(delay, lambda: self._run_next_mixed_stage(stages, 0))

            QTimer.singleShot(80, flow)
        else:
            QTimer.singleShot(80, lambda: self._run_next_mixed_stage(stages, 0))

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

    def _paste_mixed_as_rich_html(
        self,
        segments: list[dict],
        target: Optional[FocusTarget],
        hide_window: Optional[Callable[[], None]] = None,
    ) -> bool:
        rich = self._build_mixed_rich_payload(segments)
        if rich is None:
            return False
        html_text, plain_text = rich

        mime = QMimeData()
        mime.setHtml(html_text)
        if plain_text.strip():
            mime.setText(plain_text)

        self._clipboard_service.suspend_once_for_snapshot()
        self._clipboard.setMimeData(mime)

        if hide_window:
            hide_window()

        if target:
            QTimer.singleShot(80, lambda: self._restore_and_paste(target))
        else:
            QTimer.singleShot(80, self._send_paste_shortcut)
        return True

    def _build_mixed_rich_payload(self, segments: list[dict]) -> tuple[str, str] | None:
        html_parts: list[str] = []
        plain_parts: list[str] = []
        has_image = False
        has_text = False

        for segment in segments or []:
            if not isinstance(segment, dict):
                continue
            seg_type = str(segment.get("type") or "").strip().lower()
            if seg_type == "text":
                text = str(segment.get("content") or "")
                if text == "":
                    continue
                has_text = True
                plain_parts.append(text)
                html_parts.append(html_lib.escape(text).replace("\n", "<br/>"))
                continue
            if seg_type == "image":
                blob = segment.get("image_blob")
                if not isinstance(blob, (bytes, bytearray)) or len(blob) == 0:
                    continue
                image_path = self._write_temp_image(bytes(blob))
                if image_path is None:
                    continue
                image_url = QUrl.fromLocalFile(str(image_path)).toString()
                escaped_url = html_lib.escape(image_url, quote=True)
                has_image = True
                html_parts.append(
                    f'<img src="{escaped_url}" style="max-width:100%;height:auto;"/>'
                )

        if not has_image:
            return None
        if not has_text and not html_parts:
            return None
        body = "".join(html_parts)
        return f"<html><body>{body}</body></html>", "".join(plain_parts)

    def _write_temp_image(self, image_bytes: bytes) -> Path | None:
        image_hash = hashlib.sha256(image_bytes).hexdigest()
        cached_path = self._temp_image_cache.get(image_hash)
        if cached_path is not None and cached_path.exists():
            return cached_path

        image = QImage()
        if not image.loadFromData(image_bytes):
            return None
        temp_dir = Path(tempfile.gettempdir()) / "ClipNestTemp"
        try:
            temp_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            return None
        image_path = temp_dir / f"clipnest_{uuid.uuid4().hex}.png"
        try:
            if image.save(str(image_path), "PNG"):
                self._temp_image_cache[image_hash] = image_path
                return image_path
        except Exception:
            return None
        return None

    def _run_next_mixed_stage(self, stages: list[tuple[str, object]], index: int) -> None:
        if index >= len(stages):
            return
        stage_type, payload = stages[index]
        self._paste_mixed_stage(
            stage_type,
            payload,
            after_paste=lambda: self._run_next_mixed_stage(stages, index + 1),
        )

    def _paste_mixed_stage(
        self,
        stage_type: str,
        payload: object,
        after_paste: Optional[Callable[[], None]] = None,
    ) -> None:
        if stage_type == "text":
            text = str(payload)
            if text == "":
                if after_paste:
                    QTimer.singleShot(0, after_paste)
                return
            self._clipboard_service.suspend_once_for_text(text)
            self._clipboard.setText(text)
            QTimer.singleShot(60, self._send_paste_shortcut)
            if after_paste:
                QTimer.singleShot(60 + 220, after_paste)
            return

        image_bytes = bytes(payload)
        if not image_bytes:
            if after_paste:
                QTimer.singleShot(0, after_paste)
            return
        image = QImage()
        if not image.loadFromData(image_bytes, "PNG"):
            if after_paste:
                QTimer.singleShot(0, after_paste)
            return
        self._clipboard_service.suspend_once_for_image(image_bytes)
        self._clipboard.setImage(image)
        QTimer.singleShot(120, self._send_paste_shortcut)
        if after_paste:
            QTimer.singleShot(120 + 280, after_paste)

    def _build_mixed_paste_stages(self, segments: list[dict]) -> list[tuple[str, object]]:
        stages: list[tuple[str, object]] = []
        image_group: list[bytes] = []

        def flush_images() -> None:
            if not image_group:
                return
            composed = self._compose_images_vertically(image_group)
            if composed is not None:
                _image, png_bytes = composed
                stages.append(("image", png_bytes))
            image_group.clear()

        for segment in segments or []:
            if not isinstance(segment, dict):
                continue
            seg_type = str(segment.get("type") or "").strip().lower()
            if seg_type == "text":
                flush_images()
                text = str(segment.get("content") or "")
                if text:
                    if stages and stages[-1][0] == "text":
                        stages[-1] = ("text", str(stages[-1][1]) + text)
                    else:
                        stages.append(("text", text))
                continue
            if seg_type == "image":
                blob = segment.get("image_blob")
                if isinstance(blob, (bytes, bytearray)) and len(blob) > 0:
                    image_group.append(bytes(blob))

        flush_images()
        return stages

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
