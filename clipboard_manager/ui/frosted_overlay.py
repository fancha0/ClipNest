from __future__ import annotations

import random

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import QWidget


class FrostedOverlay(QWidget):
    """Subtle noise + top highlight layered over the translucent window to give
    a frosted-glass texture. Fully click-through and mouse-transparent."""

    def __init__(self, parent: QWidget | None = None, noise_alpha: int = 9) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._noise = self._build_noise(160, max(1, int(noise_alpha)))

    @staticmethod
    def _build_noise(size: int, alpha: int) -> QPixmap:
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        for _ in range((size * size) // 6):
            x = random.randint(0, size - 1)
            y = random.randint(0, size - 1)
            value = random.randint(40, 255)
            painter.setPen(QColor(value, value, value, random.randint(0, alpha)))
            painter.drawPoint(x, y)
        painter.end()
        return pixmap

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.drawTiledPixmap(self.rect(), self._noise)
        highlight = QLinearGradient(0, 0, 0, self.height())
        highlight.setColorAt(0.0, QColor(255, 255, 255, 16))
        highlight.setColorAt(0.18, QColor(255, 255, 255, 0))
        painter.fillRect(self.rect(), highlight)
        painter.end()
