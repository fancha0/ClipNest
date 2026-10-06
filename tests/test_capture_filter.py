from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from clipboard_manager.controller import AppController
from clipboard_manager.models import ParsedClipboardItem
from clipboard_manager.repository import ClipRepository


def _parsed(item_type: str, payloads: list[bytes]) -> ParsedClipboardItem:
    return ParsedClipboardItem(
        item_type=item_type,
        display_text="x",
        plain_text="",
        html_text="",
        image_blob=None,
        thumb_blob=None,
        width=None,
        height=None,
        file_paths=[],
        mime_formats=[f"application/x-{i}" for i in range(len(payloads))],
        raw_parts=[
            {"mime_type": f"application/x-{i}", "payload_blob": payload}
            for i, payload in enumerate(payloads)
        ],
    )


class RedundantCaptureFilterTests(unittest.TestCase):
    @staticmethod
    def _make_controller() -> AppController:
        tmp_dir = Path(tempfile.mkdtemp(prefix="clipnest-capturetest-"))
        repo = ClipRepository(tmp_dir / "test.db")
        return AppController(
            repository=repo,
            window=mock.MagicMock(),
            clipboard_service=mock.MagicMock(),
            focus_service=mock.MagicMock(),
            hotkey_service=mock.MagicMock(),
            paste_service=mock.MagicMock(),
        )

    def test_subset_special_capture_is_skipped(self) -> None:
        controller = self._make_controller()
        self.assertFalse(
            controller._is_redundant_clipboard_capture(
                _parsed("image", [b"img-payload", b"meta"])
            )
        )
        self.assertTrue(
            controller._is_redundant_clipboard_capture(_parsed("special", [b"meta"]))
        )

    def test_text_type_subset_is_never_filtered(self) -> None:
        controller = self._make_controller()
        controller._is_redundant_clipboard_capture(
            _parsed("image", [b"img-payload", b"meta"])
        )
        self.assertFalse(
            controller._is_redundant_clipboard_capture(_parsed("text", [b"meta"]))
        )

    def test_special_with_new_content_is_not_filtered(self) -> None:
        controller = self._make_controller()
        controller._is_redundant_clipboard_capture(_parsed("image", [b"img-payload"]))
        self.assertFalse(
            controller._is_redundant_clipboard_capture(
                _parsed("special", [b"img-payload", b"extra"])
            )
        )

    def test_subset_outside_time_window_is_not_filtered(self) -> None:
        controller = self._make_controller()
        base = time.monotonic()
        with mock.patch(
            "clipboard_manager.controller.time.monotonic", side_effect=[base]
        ):
            controller._is_redundant_clipboard_capture(
                _parsed("image", [b"img-payload", b"meta"])
            )
        with mock.patch(
            "clipboard_manager.controller.time.monotonic", side_effect=[base + 4.0]
        ):
            self.assertFalse(
                controller._is_redundant_clipboard_capture(
                    _parsed("special", [b"meta"])
                )
            )


if __name__ == "__main__":
    unittest.main()
