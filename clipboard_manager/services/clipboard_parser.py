from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Iterable

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage

from ..models import ParsedClipboardItem


class ClipboardSnapshot:
    """QMimeData 的只读副本，供后台解析线程安全使用。

    QClipboard / QMimeData 只允许在 GUI 线程碰，所以"取数据"这一步留在
    GUI 线程；真正吃 CPU 的解析（全尺寸图片压缩、逐字评分、剥离 HTML
    正则）交给工作线程。快照本身只含 bytes / str / QImage 这类值对象，
    跨线程读取是安全的。
    """

    __slots__ = (
        "_formats",
        "_payloads",
        "_text",
        "_has_text",
        "_html",
        "_has_html",
        "_image",
        "_urls",
        "_has_urls",
    )

    @classmethod
    def capture(cls, mime_data, clipboard_text: str = "") -> "ClipboardSnapshot | None":
        if mime_data is None:
            return None
        try:
            formats = [str(value) for value in mime_data.formats()]
            payloads = {
                value: bytes(mime_data.data(value) or b"") for value in formats
            }

            has_text = bool(mime_data.hasText())
            text = str(mime_data.text() or "")
            has_html = bool(mime_data.hasHtml())
            html = str(mime_data.html() or "")

            has_image = bool(mime_data.hasImage())
            image = QImage()
            if has_image:
                data = mime_data.imageData()
                if isinstance(data, QImage):
                    image = data
                elif data is not None:
                    try:
                        image = QImage(data)
                    except Exception:
                        image = QImage()

            has_urls = bool(mime_data.hasUrls())
            urls = list(mime_data.urls()) if has_urls else []
        except Exception:
            # 剪贴板可能在读取过程中被别的程序改写，读不到就当作这次没抓到
            return None
        return cls(formats, payloads, text, has_text, html, has_html, image, urls, has_urls)

    def __init__(
        self,
        formats: list[str],
        payloads: dict[str, bytes],
        text: str,
        has_text: bool,
        html: str,
        has_html: bool,
        image: QImage,
        urls: list,
        has_urls: bool,
    ) -> None:
        self._formats = list(formats)
        self._payloads = dict(payloads)
        self._text = text
        self._has_text = has_text
        self._html = html
        self._has_html = has_html
        self._image = image
        self._urls = list(urls)
        self._has_urls = has_urls

    def formats(self) -> list[str]:
        return list(self._formats)

    def data(self, mime_type) -> bytes:
        return self._payloads.get(str(mime_type), b"")

    def hasText(self) -> bool:
        return self._has_text

    def text(self) -> str:
        return self._text

    def hasHtml(self) -> bool:
        return self._has_html

    def html(self) -> str:
        return self._html

    def hasImage(self) -> bool:
        return not self._image.isNull()

    def imageData(self) -> QImage:
        return self._image

    def hasUrls(self) -> bool:
        return self._has_urls

    def urls(self) -> list:
        return list(self._urls)


class ClipboardContentParser:
    _SAFE_TEXT_CODECS = ("utf-8-sig", "gb18030", "cp936")
    _UTF16_CODECS = ("utf-16", "utf-16le", "utf-16be")
    _URL_RE = re.compile(r"^(https?|ftp)://", re.IGNORECASE)

    def parse(self, mime_data, clipboard_text: str = "") -> ParsedClipboardItem | None:
        if mime_data is None:
            return None

        raw_parts = self._collect_raw_parts(mime_data, clipboard_text)
        if not raw_parts:
            return None
        mime_formats = [str(part["mime_type"]) for part in raw_parts]

        parsed_image = self._parse_image(mime_data, mime_formats, raw_parts)
        if parsed_image is not None:
            return parsed_image

        parsed_files = self._parse_files(mime_data, mime_formats, raw_parts)
        if parsed_files is not None:
            return parsed_files

        parsed_html = self._parse_html(mime_data, mime_formats, raw_parts)
        if parsed_html is not None:
            return parsed_html

        parsed_url = self._parse_url(mime_data, raw_parts, mime_formats)
        if parsed_url is not None:
            return parsed_url

        parsed_text = self._parse_text(mime_data, raw_parts, mime_formats)
        if parsed_text is not None:
            return parsed_text

        return ParsedClipboardItem(
            item_type="special",
            display_text="[特殊内容]",
            plain_text="",
            html_text="",
            image_blob=None,
            thumb_blob=None,
            width=None,
            height=None,
            file_paths=[],
            mime_formats=mime_formats,
            raw_parts=raw_parts,
        )

    def _parse_image(self, mime_data, mime_formats: list[str], raw_parts: list[dict[str, bytes]]) -> ParsedClipboardItem | None:
        image = QImage()
        if mime_data.hasImage():
            data = mime_data.imageData()
            if isinstance(data, QImage):
                image = data
            elif data is not None:
                try:
                    image = QImage(data)
                except Exception:
                    image = QImage()

        if image.isNull():
            for part in raw_parts:
                mime_type = str(part["mime_type"]).lower()
                if not mime_type.startswith("image/"):
                    continue
                candidate = QImage()
                if candidate.loadFromData(bytes(part["payload_blob"])):
                    image = candidate
                    break

        if image.isNull():
            return None

        width = image.width()
        height = image.height()
        image_blob = self._reused_png_payload(raw_parts, width, height)
        if image_blob is None:
            image_blob = self._image_to_png_bytes(image)
        if image_blob is None:
            return None
        thumb_blob = self._make_thumbnail_blob(image)
        return ParsedClipboardItem(
            item_type="image",
            display_text=f"[图片] {width}x{height}",
            plain_text="",
            html_text="",
            image_blob=image_blob,
            thumb_blob=thumb_blob,
            width=width,
            height=height,
            file_paths=[],
            mime_formats=mime_formats,
            raw_parts=raw_parts,
        )

    @staticmethod
    def _png_dimensions(payload: bytes) -> tuple[int, int] | None:
        """只读 PNG 的 IHDR 头取尺寸，不解码整张图。"""
        if len(payload) < 24 or payload[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        if payload[12:16] != b"IHDR":
            return None
        return (
            int.from_bytes(payload[16:20], "big"),
            int.from_bytes(payload[20:24], "big"),
        )

    def _reused_png_payload(
        self, raw_parts: list[dict[str, bytes]], width: int, height: int
    ) -> bytes | None:
        """剪贴板里已有的 PNG 原始字节且尺寸一致时直接复用，省掉一次全尺寸压缩。"""
        for part in raw_parts:
            mime_type = str(part.get("mime_type") or "").lower()
            if mime_type not in {"image/png", "png"}:
                continue
            payload = bytes(part.get("payload_blob") or b"")
            if payload and self._png_dimensions(payload) == (width, height):
                return payload
        return None

    def _parse_files(self, mime_data, mime_formats: list[str], raw_parts: list[dict[str, bytes]]) -> ParsedClipboardItem | None:
        if not mime_data.hasUrls():
            return None

        local_paths: list[str] = []
        for url in mime_data.urls():
            if url.isLocalFile():
                local_path = url.toLocalFile()
                if local_path:
                    local_paths.append(local_path)

        if not local_paths:
            return None

        first_name = Path(local_paths[0]).name or local_paths[0]
        if len(local_paths) == 1:
            display_text = first_name
        else:
            display_text = f"{first_name} 等 {len(local_paths)} 个文件"

        return ParsedClipboardItem(
            item_type="files",
            display_text=display_text,
            plain_text="\n".join(local_paths),
            html_text="",
            image_blob=None,
            thumb_blob=None,
            width=None,
            height=None,
            file_paths=local_paths,
            mime_formats=mime_formats,
            raw_parts=raw_parts,
        )

    def _parse_html(self, mime_data, mime_formats: list[str], raw_parts: list[dict[str, bytes]]) -> ParsedClipboardItem | None:
        html_text = ""
        if mime_data.hasHtml():
            html_text = str(mime_data.html() or "")
        if html_text.strip() == "":
            html_text = self._find_decoded_payload(raw_parts, starts_with="text/html")
        if html_text.strip() == "":
            return None

        plain = self._html_to_plain_text(html_text)
        if plain.strip() == "":
            return None
        display_text = self._normalize_display_text(plain)
        return ParsedClipboardItem(
            item_type="html",
            display_text=display_text,
            plain_text=plain,
            html_text=html_text,
            image_blob=None,
            thumb_blob=None,
            width=None,
            height=None,
            file_paths=[],
            mime_formats=mime_formats,
            raw_parts=raw_parts,
        )

    def _parse_url(self, mime_data, raw_parts: list[dict[str, bytes]], mime_formats: list[str]) -> ParsedClipboardItem | None:
        text = self._extract_plain_text(mime_data, raw_parts)
        if text == "":
            return None
        stripped = text.strip()
        if not self._URL_RE.match(stripped):
            return None
        return ParsedClipboardItem(
            item_type="url",
            display_text=self._normalize_display_text(stripped),
            plain_text=stripped,
            html_text="",
            image_blob=None,
            thumb_blob=None,
            width=None,
            height=None,
            file_paths=[],
            mime_formats=mime_formats,
            raw_parts=raw_parts,
        )

    def _parse_text(self, mime_data, raw_parts: list[dict[str, bytes]], mime_formats: list[str]) -> ParsedClipboardItem | None:
        text = self._extract_plain_text(mime_data, raw_parts)
        if text == "":
            return None
        stripped = text.strip()
        if stripped == "":
            return None

        display_text = self._normalize_display_text(stripped)
        if self._looks_like_style_source(display_text):
            return None

        return ParsedClipboardItem(
            item_type="text",
            display_text=display_text,
            plain_text=stripped,
            html_text="",
            image_blob=None,
            thumb_blob=None,
            width=None,
            height=None,
            file_paths=[],
            mime_formats=mime_formats,
            raw_parts=raw_parts,
        )

    def _collect_raw_parts(self, mime_data, clipboard_text: str) -> list[dict[str, bytes]]:
        parts: list[dict[str, bytes]] = []
        for mime_type in mime_data.formats():
            payload = bytes(mime_data.data(mime_type))
            parts.append({"mime_type": str(mime_type), "payload_blob": payload})
        if not parts:
            text = (clipboard_text or "").strip()
            if text:
                parts.append({"mime_type": "text/plain", "payload_blob": text.encode("utf-8")})
        return parts

    def _extract_plain_text(self, mime_data, raw_parts: list[dict[str, bytes]]) -> str:
        has_plain_part = False
        has_nontext_part = False
        candidates: list[tuple[str, bool]] = []
        for part in raw_parts:
            mime_type = str(part["mime_type"]).lower()
            if not mime_type.startswith("text/plain"):
                has_nontext_part = True
                continue
            has_plain_part = True
            decoded = self._decode_text(bytes(part["payload_blob"]), mime_type)
            if decoded:
                candidates.append((decoded, True))
        if mime_data.hasText():
            text = str(mime_data.text() or "").strip()
            if text:
                candidates.append((text, has_plain_part))

        best_text = ""
        best_score = -10**9
        for text, trusted in candidates:
            candidate_score = self._candidate_score(text)
            if not trusted:
                candidate_score -= 25
            if candidate_score > best_score:
                best_score = candidate_score
                best_text = text

        if best_text == "":
            return ""
        if has_nontext_part and not has_plain_part and not self._is_clearly_readable_text(best_text):
            return ""
        if best_score < 55:
            return ""
        return best_text

    def _find_decoded_payload(self, raw_parts: Iterable[dict[str, bytes]], starts_with: str) -> str:
        target = starts_with.lower()
        for part in raw_parts:
            mime_type = str(part["mime_type"]).lower()
            if mime_type.startswith(target):
                decoded = self._decode_text(bytes(part["payload_blob"]), mime_type)
                if decoded:
                    return decoded
        return ""

    def _decode_text(self, payload: bytes, mime_type: str) -> str:
        if not payload:
            return ""
        codecs = self._ordered_codecs(mime_type, payload)
        best_text = ""
        best_score = -10**9
        for enc in codecs:
            try:
                text = payload.decode(enc, errors="replace")
            except Exception:
                continue
            cleaned = text.strip()
            if cleaned == "":
                continue
            score = self._text_score(cleaned)
            if score > best_score:
                best_score = score
                best_text = cleaned
        return best_text if best_score >= 55 else ""

    def _ordered_codecs(self, mime_type: str, payload: bytes) -> tuple[str, ...]:
        lowered = (mime_type or "").lower()
        match = re.search(r"charset=([a-z0-9_\-]+)", lowered)
        ordered: list[str] = []
        if match:
            charset = match.group(1).replace("_", "-")
        else:
            charset = ""
        alias = {"gbk": "cp936", "gb2312": "gb18030", "utf8": "utf-8"}
        charset = alias.get(charset, charset)
        if charset:
            ordered.append(charset)
        ordered.extend(enc for enc in self._SAFE_TEXT_CODECS if enc not in ordered)
        if charset.startswith("utf-16") or charset == "utf16" or self._has_utf16_hint(payload, lowered):
            ordered.extend(enc for enc in self._UTF16_CODECS if enc not in ordered)
        return tuple(ordered)

    @staticmethod
    def _html_to_plain_text(html_text: str) -> str:
        text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html_text)
        text = re.sub(r"(?is)<[^>]+>", " ", text)
        text = html.unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    @staticmethod
    def _normalize_display_text(text: str, max_len: int = 180) -> str:
        simplified = re.sub(r"\s+", " ", text).strip()
        if len(simplified) <= max_len:
            return simplified
        return simplified[: max_len - 3] + "..."

    @staticmethod
    def _looks_like_style_source(text: str) -> bool:
        value = text.strip().lower()
        if value == "":
            return False
        css_tokens = ("font-size:", "font-family:", "border-left:", "border-top:", "line-height:")
        hit = sum(1 for token in css_tokens if token in value)
        if hit >= 2:
            return True
        if re.search(r"\.[a-z0-9_\-]+\s*\{", value) and ";" in value:
            return True
        if value.startswith("{\\rtf"):
            return True
        return False

    @staticmethod
    def _text_score(text: str) -> int:
        total = max(1, len(text))
        printable = sum(1 for ch in text if ch.isprintable())
        replacement = text.count("\ufffd") + text.count("�")
        control = sum(1 for ch in text if (ord(ch) < 32 and ch not in ("\t", "\n", "\r")))
        score = int(printable / total * 100) - replacement * 45 - control * 30
        if ClipboardContentParser._looks_like_mojibake(text):
            score -= 95
        return score

    @staticmethod
    def _has_utf16_hint(payload: bytes, mime_type: str) -> bool:
        if "charset=utf-16" in (mime_type or ""):
            return True
        if payload.startswith((b"\xff\xfe", b"\xfe\xff")):
            return True
        if len(payload) < 4 or len(payload) % 2 != 0:
            return False
        even_zeros = sum(1 for i in range(0, len(payload), 2) if payload[i] == 0)
        odd_zeros = sum(1 for i in range(1, len(payload), 2) if payload[i] == 0)
        half = len(payload) // 2
        return (even_zeros / half) > 0.35 or (odd_zeros / half) > 0.35

    @staticmethod
    def _looks_like_mojibake(text: str) -> bool:
        value = (text or "").strip()
        if value == "":
            return False
        if any(ch in value for ch in ("�", "□", "�", "\x00")):
            return True

        chars = [ch for ch in value if not ch.isspace()]
        if not chars:
            return False
        total = len(chars)
        private_use = sum(1 for ch in chars if 0xE000 <= ord(ch) <= 0xF8FF)
        odd_symbols = sum(1 for ch in chars if ord(ch) in (0xFFFD, 0x25A1, 0x25A0))
        if private_use > 0 or odd_symbols > 0:
            return True

        cjk = sum(1 for ch in chars if 0x4E00 <= ord(ch) <= 0x9FFF)
        punct = sum(1 for ch in chars if re.match(r"[\.\,\!\?\:\;\，\。\、\！\？\：\；\-\_\+\(\)\[\]【】《》“”‘’/\\|]", ch))
        ascii_alnum = sum(1 for ch in chars if ch.isascii() and ch.isalnum())
        unique_ratio = len(set(chars)) / total
        if total >= 24 and (cjk / total) > 0.9 and punct <= 1 and ascii_alnum == 0 and unique_ratio > 0.94:
            return True
        return False

    def _candidate_score(self, text: str) -> int:
        if not text:
            return -10**9
        score = self._text_score(text)
        if self._looks_like_style_source(text):
            score -= 220
        if self._looks_like_mojibake(text):
            score -= 180
        return score

    def _is_clearly_readable_text(self, text: str) -> bool:
        if text.strip() == "":
            return False
        if self._looks_like_style_source(text):
            return False
        if self._looks_like_mojibake(text):
            return False
        return self._text_score(text) >= 55

    @staticmethod
    def _image_to_png_bytes(image: QImage) -> bytes | None:
        data = QByteArray()
        buffer = QBuffer(data)
        if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
            return None
        ok = image.save(buffer, "PNG")
        buffer.close()
        if not ok:
            return None
        return bytes(data)

    def _make_thumbnail_blob(self, image: QImage, max_edge: int = 112) -> bytes | None:
        if image.isNull():
            return None
        thumb = image.scaled(
            max_edge,
            max_edge,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        return self._image_to_png_bytes(thumb)
