from __future__ import annotations


def detect_image_format(data: bytes | bytearray | None) -> str | None:
    """Return the Qt image format name from magic bytes, or None if unknown."""
    if not data:
        return None
    payload = bytes(data)
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if payload.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if payload.startswith((b"GIF87a", b"GIF89a")):
        return "GIF"
    if payload.startswith(b"BM"):
        return "BMP"
    if (
        len(payload) >= 12
        and payload.startswith(b"RIFF")
        and payload[8:12] == b"WEBP"
    ):
        return "WEBP"
    if payload.startswith((b"II*\x00", b"MM\x00*")):
        return "TIFF"
    if payload.startswith(b"\x00\x00\x01\x00"):
        return "ICO"
    return None