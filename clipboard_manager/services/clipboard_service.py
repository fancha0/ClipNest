from __future__ import annotations

import time
import logging

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QClipboard

from .clipboard_parser import ClipboardContentParser

logger = logging.getLogger(__name__)


class ClipboardService(QObject):
    parsed_captured = Signal(object)
    SELF_WRITE_SUPPRESSION_SECONDS = 0.8
    DEFERRED_IMAGE_RETRY_MS = 150
    DEFERRED_IMAGE_MAX_RETRIES = 2

    def __init__(self, clipboard: QClipboard) -> None:
        super().__init__()
        self._clipboard = clipboard
        self._suppress_until = 0.0
        self._capture_debounce_ms = 100
        self._capture_generation = 0
        self._capture_timer = QTimer(self)
        self._capture_timer.setSingleShot(True)
        self._capture_timer.timeout.connect(self._capture_current_clipboard)
        self._parser = ClipboardContentParser()
        self._clipboard.dataChanged.connect(self._on_data_changed)

    def suspend_once_for_text(self, _text: str) -> None:
        self._suspend_self_writes()

    def suspend_once_for_image(self, _image_bytes: bytes) -> None:
        self._suspend_self_writes()

    def suspend_once_for_snapshot(self) -> None:
        self._suspend_self_writes()

    def _suspend_self_writes(self) -> None:
        """Ignore all notifications from our own multi-format clipboard write."""
        self._suppress_until = max(
            self._suppress_until,
            time.monotonic() + self.SELF_WRITE_SUPPRESSION_SECONDS,
        )

    def _on_data_changed(self) -> None:
        # 多个剪贴板软件可能在几十毫秒内连续重写同一份内容。
        # 等待最后一次变化后再读取，既不屏蔽其他软件，也避免重复记录。
        self._capture_generation += 1
        self._capture_timer.start(self._capture_debounce_ms)

    def _capture_current_clipboard(
        self,
        retry_count: int = 0,
        generation: int | None = None,
    ) -> None:
        if generation is not None and generation != self._capture_generation:
            return
        if time.monotonic() < self._suppress_until:
            return

        mime_data = self._clipboard.mimeData()
        if mime_data is None:
            return

        parsed = self._parser.parse(mime_data, clipboard_text=self._clipboard.text() or "")
        if parsed is None:
            return

        if self._is_deferred_image(parsed) and retry_count < self.DEFERRED_IMAGE_MAX_RETRIES:
            current_generation = self._capture_generation
            logger.info(
                "[Clipboard] deferred image detected, retry=%s",
                retry_count + 1,
            )
            QTimer.singleShot(
                self.DEFERRED_IMAGE_RETRY_MS,
                lambda: self._capture_current_clipboard(
                    retry_count + 1,
                    current_generation,
                ),
            )
            return

        self.parsed_captured.emit(parsed)

    @staticmethod
    def _is_deferred_image(parsed) -> bool:
        if parsed.item_type != "special":
            return False
        formats = [str(value).lower() for value in (parsed.mime_formats or [])]
        return any(
            value == "application/x-qt-image" or value.startswith("image/")
            for value in formats
        )
