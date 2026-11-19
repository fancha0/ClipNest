from __future__ import annotations

import unittest

from clipboard_manager.image_formats import detect_image_format
from clipboard_manager.repository import ClipRepository


class ImageFormatDetectionTests(unittest.TestCase):
    def test_known_magic_bytes(self) -> None:
        cases = {
            b"\x89PNG\r\n\x1a\nrest": "PNG",
            b"\xff\xd8\xffrest": "JPEG",
            b"GIF89arest": "GIF",
            b"GIF87arest": "GIF",
            b"BMrest": "BMP",
            b"RIFF\x00\x00\x00\x00WEBPrest": "WEBP",
            b"II*\x00rest": "TIFF",
            b"MM\x00*rest": "TIFF",
            b"\x00\x00\x01\x00rest": "ICO",
        }
        for payload, expected in cases.items():
            with self.subTest(expected=expected):
                self.assertEqual(detect_image_format(payload), expected)

    def test_unknown_and_empty_bytes_return_none(self) -> None:
        self.assertIsNone(detect_image_format(b""))
        self.assertIsNone(detect_image_format(None))
        self.assertIsNone(detect_image_format(b"same"))
        self.assertIsNone(detect_image_format(b"not-an-image"))

    def test_thumbnail_skips_unknown_payload(self) -> None:
        self.assertIsNone(ClipRepository._make_thumbnail_blob(b"same"))


if __name__ == "__main__":
    unittest.main()