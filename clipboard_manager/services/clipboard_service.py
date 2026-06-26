from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QClipboard

from ..models import ParsedClipboardItem
from .clipboard_parser import ClipboardContentParser


class ClipboardService(QObject):
    # New typed signal used by controller.
    parsed_captured = Signal(object)
    # Legacy signal kept for compatibility paths.
    mime_captured = Signal(object, str)
    text_captured = Signal(str)
    image_captured = Signal(bytes, str, int, int)

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
        self.mime_captured.emit(parsed.raw_parts, parsed.display_text)

    # Backward-compatible helper kept for tests and legacy paths.
    def _extract_mime_snapshot(self, mime_data) -> tuple[list[dict], str]:
        parsed: ParsedClipboardItem | None = self._parser.parse(
            mime_data,
            clipboard_text=self._clipboard.text() or "",
        )
        if parsed is None:
            return [], ""
        return parsed.raw_parts, parsed.display_text
