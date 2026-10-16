from __future__ import annotations

import unittest

from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage

from clipboard_manager.services.clipboard_parser import ClipboardContentParser


def _png_header(width: int, height: int) -> bytes:
    """只构造 PNG 文件头（签名 + IHDR 长度/类型 + 宽高），足够测尺寸解析。"""
    return (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\x0d"
        + b"IHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x00" * 8
    )


def _real_png(width: int, height: int) -> bytes:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.red)
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise AssertionError("测试图片编码失败")
    return bytes(buffer.data())


class _FakeMimeData:
    def __init__(self, image: QImage) -> None:
        self._image = image

    def hasImage(self) -> bool:
        return True

    def imageData(self) -> QImage:
        return self._image


class PngHeaderTests(unittest.TestCase):
    def test_png_dimensions_reads_header_only(self) -> None:
        self.assertEqual(ClipboardContentParser._png_dimensions(_png_header(1920, 1080)), (1920, 1080))
        self.assertIsNone(ClipboardContentParser._png_dimensions(b"not a png"))
        self.assertIsNone(ClipboardContentParser._png_dimensions(b""))
        # 太短的文件即使有签名也要判为无效
        self.assertIsNone(ClipboardContentParser._png_dimensions(b"\x89PNG\r\n\x1a\n"))

    def test_reused_png_payload_requires_matching_size(self) -> None:
        png = _png_header(4, 2)
        parts = [
            {"mime_type": "image/bmp", "payload_blob": b"dib"},
            {"mime_type": "image/png", "payload_blob": png},
        ]
        parser = ClipboardContentParser()
        self.assertEqual(parser._reused_png_payload(parts, 4, 2), png)
        self.assertIsNone(parser._reused_png_payload(parts, 4, 3))
        self.assertIsNone(
            parser._reused_png_payload(
                [{"mime_type": "image/png", "payload_blob": b"\x89PNG\r\n\x1a\n"}],
                4,
                2,
            )
        )

    def test_windows_png_format_alias_is_recognized(self) -> None:
        png = _png_header(1, 1)
        parts = [{"mime_type": "PNG", "payload_blob": png}]
        parser = ClipboardContentParser()
        self.assertEqual(parser._reused_png_payload(parts, 1, 1), png)


class ParseImageReuseTests(unittest.TestCase):
    def test_parse_image_reuses_existing_png_bytes(self) -> None:
        """剪贴板里已有 PNG 原始字节时，不再重新压缩一次全尺寸图。"""
        image = QImage(8, 4, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.blue)
        png = _real_png(8, 4)
        mime_data = _FakeMimeData(image)
        raw_parts = [{"mime_type": "image/png", "payload_blob": png}]

        parsed = ClipboardContentParser()._parse_image(mime_data, ["image/png"], raw_parts)

        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.item_type, "image")
        self.assertEqual((parsed.width, parsed.height), (8, 4))
        # 直接复用原始字节，而不是重新编码出另一份
        self.assertEqual(parsed.image_blob, png)
        self.assertEqual(parsed.raw_parts, raw_parts)


if __name__ == "__main__":
    unittest.main()
