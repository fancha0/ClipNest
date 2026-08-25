from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QClipboard

from .clipboard_parser import ClipboardContentParser


class ClipboardService(QObject):
    parsed_captured = Signal(object)

    def __init__(self, clipboard: QClipboard) -> None:
        super().__init__()
        self._clipboard = clipboard
        self._suppressed_changes_remaining = 0
        self._parser = ClipboardContentParser()
        self._clipboard.dataChanged.connect(self._on_data_changed)

    def suspend_once_for_text(self, _text: str) -> None:
        self._suppressed_changes_remaining += 1

    def suspend_once_for_image(self, _image_bytes: bytes) -> None:
        self._suppressed_changes_remaining += 1

    def suspend_once_for_snapshot(self) -> None:
        self._suppressed_changes_remaining += 1

    def _on_data_changed(self) -> None:
        if self._suppressed_changes_remaining > 0:
            self._suppressed_changes_remaining -= 1
            return

        mime_data = self._clipboard.mimeData()
        if mime_data is None:
            return

        parsed = self._parser.parse(mime_data, clipboard_text=self._clipboard.text() or "")
        if parsed is None:
            return

        self.parsed_captured.emit(parsed)
