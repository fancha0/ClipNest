from __future__ import annotations

import hashlib
from typing import Any, Optional

from PySide6.QtGui import QImage, QPixmap

from .image_codec import encode_qimage_to_payload


class ImageMimeMixin:
    """Shared image-from-mime helpers for widgets that accept image drops/pastes."""

    @staticmethod
    def _mime_may_contain_images(mime_data) -> bool:
        if mime_data is None:
            return False
        if mime_data.hasImage():
            return True
        if not mime_data.hasUrls():
            return False
        for url in mime_data.urls():
            if not url.isLocalFile():
                continue
            local_path = url.toLocalFile()
            if local_path and not QImage(local_path).isNull():
                return True
        return False

    @staticmethod
    def _image_from_mime_data(mime_data) -> Optional[QImage]:
        if mime_data is None or not mime_data.hasImage():
            return None
        data = mime_data.imageData()
        image = QImage()
        if isinstance(data, QImage):
            image = data
        elif isinstance(data, QPixmap):
            image = data.toImage()
        elif data is not None:
            try:
                image = QImage(data)
            except Exception:
                image = QImage()
        return image if not image.isNull() else None

    @staticmethod
    def _image_fingerprint(image: QImage) -> str:
        try:
            data = bytes(image.constBits().tobytes())
        except Exception:
            data = b""
        if data:
            return hashlib.md5(data).hexdigest() + f":{image.width()}x{image.height()}"
        return f"{image.cacheKey()}:{image.width()}x{image.height()}"

    @staticmethod
    def _image_to_payload(image: QImage) -> Optional[dict[str, Any]]:
        return encode_qimage_to_payload(image, "image/png")
