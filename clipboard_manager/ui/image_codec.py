from __future__ import annotations

from typing import Any, Optional

from PySide6.QtCore import QByteArray, QBuffer, QIODevice
from PySide6.QtGui import QImage


def encode_qimage_to_payload(
    image: QImage,
    mime_type: str = "image/png",
) -> Optional[dict[str, Any]]:
    if image.isNull():
        return None
    data = QByteArray()
    buf = QBuffer(data)
    if not buf.open(QIODevice.OpenModeFlag.WriteOnly):
        return None
    ok = image.save(buf, "PNG")
    buf.close()
    if not ok:
        return None
    return {
        "image_blob": bytes(data),
        "mime_type": str(mime_type or "image/png"),
        "width": image.width(),
        "height": image.height(),
    }
