from __future__ import annotations

import shutil
import unittest
import uuid
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QImage

from clipboard_manager.services.clipboard_parser import ClipboardContentParser


class _FakeMimeData:
    def __init__(
        self,
        *,
        urls: list[QUrl] | None = None,
        parts: list[dict[str, bytes]] | None = None,
        text: str = "",
        html: str = "",
        image: QImage | None = None,
    ) -> None:
        self._urls = list(urls or [])
        self._parts = list(parts or [])
        self._text = text
        self._html = html
        self._image = image if image is not None else QImage()

    def hasUrls(self) -> bool:
        return bool(self._urls)

    def urls(self) -> list[QUrl]:
        return list(self._urls)

    def formats(self) -> list[str]:
        values = [str(p["mime_type"]) for p in self._parts]
        if self._html and "text/html" not in {v.lower() for v in values}:
            values.append("text/html")
        if self._text and "text/plain" not in {v.lower() for v in values}:
            values.append("text/plain")
        return values

    def data(self, mime_type: str) -> bytes:
        target = mime_type.lower()
        for part in self._parts:
            if str(part["mime_type"]).lower() == target:
                return bytes(part["payload_blob"])
        if target.startswith("text/html") and self._html:
            return self._html.encode("utf-8")
        if target.startswith("text/plain") and self._text:
            return self._text.encode("utf-8")
        return b""

    def hasText(self) -> bool:
        return bool(self._text)

    def text(self) -> str:
        return self._text

    def hasHtml(self) -> bool:
        return bool(self._html)

    def html(self) -> str:
        return self._html

    def hasImage(self) -> bool:
        return not self._image.isNull()

    def imageData(self):
        return self._image


class ClipboardParserTests(unittest.TestCase):
    def setUp(self) -> None:
        base = Path(__file__).resolve().parent / ".tmp"
        base.mkdir(parents=True, exist_ok=True)
        self._base_dir = base / f"clip_{uuid.uuid4().hex}"
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._parser = ClipboardContentParser()

    def tearDown(self) -> None:
        if self._base_dir.exists():
            shutil.rmtree(self._base_dir, ignore_errors=True)

    def _write_png(self, path: Path, width: int = 24, height: int = 12) -> None:
        image = QImage(width, height, QImage.Format.Format_ARGB32)
        image.fill(0xFF5A9DFF)
        self.assertTrue(image.save(str(path), "PNG"))

    def test_parse_real_image_prioritizes_image_type(self) -> None:
        image = QImage(320, 120, QImage.Format.Format_ARGB32)
        image.fill(0xFF1E90FF)
        mime = _FakeMimeData(
            image=image,
            parts=[
                {"mime_type": "application/x-qt-windows-mime;value=\"PixPinData\"", "payload_blob": b"\x00\x01"},
                {"mime_type": "application/x-qt-image", "payload_blob": b"\x00\x02"},
            ],
        )

        parsed = self._parser.parse(mime)

        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.item_type, "image")
        self.assertTrue(parsed.display_text.startswith("[图片]"))
        self.assertIsNotNone(parsed.thumb_blob)

    def test_parse_html_extracts_clean_plain_text(self) -> None:
        html_text = (
            "<html><style>.td1{font-size:12pt}</style><body>"
            "<div>超级幸运鹅</div><script>var x=1</script></body></html>"
        )
        mime = _FakeMimeData(
            html=html_text,
            parts=[{"mime_type": "text/html", "payload_blob": html_text.encode("utf-8")}],
        )

        parsed = self._parser.parse(mime)

        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.item_type, "html")
        self.assertIn("超级幸运鹅", parsed.display_text)
        self.assertNotIn("font-size", parsed.display_text.lower())
        self.assertNotIn("<style", parsed.display_text.lower())

    def test_parse_files_shows_filename_summary(self) -> None:
        first = self._base_dir / "a.png"
        second = self._base_dir / "b.txt"
        self._write_png(first)
        second.write_text("hello", encoding="utf-8")
        mime = _FakeMimeData(
            urls=[QUrl.fromLocalFile(str(first)), QUrl.fromLocalFile(str(second))],
            parts=[{"mime_type": "text/uri-list", "payload_blob": b""}],
        )

        parsed = self._parser.parse(mime)

        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.item_type, "files")
        self.assertIn("等 2 个文件", parsed.display_text)
        self.assertEqual(len(parsed.file_paths), 2)

    def test_parse_url_type(self) -> None:
        mime = _FakeMimeData(
            text="https://example.com/path?a=1",
            parts=[{"mime_type": "text/plain", "payload_blob": b"https://example.com/path?a=1"}],
        )
        parsed = self._parser.parse(mime)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.item_type, "url")

    def test_parse_text_utf16_not_misdetected_as_binary(self) -> None:
        payload = "清风小护店-M挂抽1".encode("utf-16le")
        mime = _FakeMimeData(parts=[{"mime_type": "text/plain;charset=utf-16le", "payload_blob": payload}])
        parsed = self._parser.parse(mime)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.item_type, "text")
        self.assertIn("清风小护店", parsed.display_text)

    def test_parse_short_chinese_marketing_text_not_misdetected_as_special(self) -> None:
        text = "清风官旗手帕纸 免费寄样+投流"
        mime = _FakeMimeData(
            text=text,
            parts=[{"mime_type": "text/plain;charset=utf-8", "payload_blob": text.encode("utf-8")}],
        )
        parsed = self._parser.parse(mime)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.item_type, "text")
        self.assertEqual(parsed.display_text, text)

    def test_parse_private_mime_with_dirty_text_falls_back_to_special(self) -> None:
        dirty_payload = b"\xff\xfe\x81\x00\x90\x00\xa3\x00\x00\xff\x00\x1f\x00\xee"
        mime = _FakeMimeData(
            parts=[
                {"mime_type": "application/x-qt-windows-mime;value=\"PixPinData\"", "payload_blob": b"\x12\x34"},
                {"mime_type": "application/x-qt-image", "payload_blob": b"\x89PNG"},
                {"mime_type": "text/plain", "payload_blob": dirty_payload},
            ],
        )
        parsed = self._parser.parse(mime)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.item_type, "special")
        self.assertEqual(parsed.display_text, "[特殊内容]")

    def test_parse_prefers_readable_text_over_dirty_candidate(self) -> None:
        readable = "超级幸运鹅".encode("utf-8")
        dirty = b"\x81\x30\xff\x0f\xe2\x99\x01\x00\x90\xfe"
        mime = _FakeMimeData(
            parts=[
                {"mime_type": "text/plain;charset=utf-8", "payload_blob": readable},
                {"mime_type": "text/plain", "payload_blob": dirty},
            ]
        )
        parsed = self._parser.parse(mime)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.item_type, "text")
        self.assertIn("超级幸运鹅", parsed.display_text)

    def test_private_mime_without_text_becomes_special(self) -> None:
        mime = _FakeMimeData(
            parts=[
                {"mime_type": "application/x-qt-windows-mime;value=\"PixPinData\"", "payload_blob": b"\x01\x02"},
                {"mime_type": "application/x-custom-private", "payload_blob": b"\x03\x04"},
            ]
        )
        parsed = self._parser.parse(mime)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.item_type, "special")
        self.assertEqual(parsed.display_text, "[特殊内容]")


if __name__ == "__main__":
    unittest.main()
