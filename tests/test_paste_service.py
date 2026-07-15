from __future__ import annotations

import unittest
from base64 import b64encode

from PySide6.QtCore import QByteArray, QBuffer, QIODevice
from PySide6.QtGui import QImage

from clipboard_manager.services.paste_service import PasteService


class _Clipboard:
    def setMimeData(self, mime) -> None:
        self.mime = mime


class _ClipboardService:
    def suspend_once_for_snapshot(self) -> None:
        pass


class _FocusService:
    pass


class PasteServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = PasteService(_Clipboard(), _ClipboardService(), _FocusService())

    @staticmethod
    def _png_bytes() -> bytes:
        image = QImage(3, 2, QImage.Format.Format_ARGB32)
        image.fill(0xFF1E90FF)
        data = QByteArray()
        buffer = QBuffer(data)
        assert buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        assert image.save(buffer, "PNG")
        buffer.close()
        return bytes(data)

    def test_mixed_payload_embeds_image_and_preserves_order(self) -> None:
        image_bytes = self._png_bytes()

        payload = self.service._build_mixed_rich_payload(
            [
                {"type": "text", "content": "图片前"},
                {"type": "image", "image_blob": image_bytes},
                {"type": "text", "content": "图片后"},
            ]
        )

        self.assertIsNotNone(payload)
        assert payload is not None
        html_text, plain_text = payload
        self.assertEqual(plain_text, "图片前图片后")
        self.assertIn("data:image/png;base64,", html_text)
        self.assertNotIn("file://", html_text)
        self.assertLess(html_text.index("图片前"), html_text.index("<img"))
        self.assertLess(html_text.index("<img"), html_text.index("图片后"))

    def test_mixed_payload_caches_image_data_uri(self) -> None:
        image_bytes = self._png_bytes()

        first = self.service._image_data_uri(image_bytes)
        second = self.service._image_data_uri(image_bytes)

        self.assertIsNotNone(first)
        self.assertEqual(first, second)
        self.assertEqual(len(self.service._rich_image_data_uri_cache), 1)

    def test_mixed_payload_preserves_original_image_mime_and_bytes(self) -> None:
        image_bytes = b"original-jpeg-bytes"

        payload = self.service._build_mixed_rich_payload(
            [{"type": "image", "image_blob": image_bytes, "mime_type": "image/jpeg"}]
        )

        self.assertIsNotNone(payload)
        assert payload is not None
        html_text, _plain_text = payload
        self.assertIn(
            f"data:image/jpeg;base64,{b64encode(image_bytes).decode('ascii')}",
            html_text,
        )

    def test_rich_paste_does_not_add_image_only_mime_format(self) -> None:
        image_bytes = self._png_bytes()

        self.assertTrue(
            self.service._paste_mixed_as_rich_html(
                [
                    {"type": "text", "content": "文字"},
                    {"type": "image", "image_blob": image_bytes, "mime_type": "image/png"},
                ],
                target=None,
            )
        )

        formats = self.service._clipboard.mime.formats()
        self.assertIn("text/html", formats)
        self.assertIn("text/plain", formats)
        self.assertNotIn("application/x-qt-image", formats)


if __name__ == "__main__":
    unittest.main()
