from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap


_STATUS_COLORS = {
    "success": "#2e9e6b",
    "error": "#d0534b",
    "warning": "#d9902b",
    "info": "#3b82c4",
}


def status_icon(kind: str, size: int = 22) -> QIcon:
    """Filled circular status badge with a check / cross / exclamation glyph."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    color = QColor(_STATUS_COLORS.get(kind, _STATUS_COLORS["info"]))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawEllipse(QRectF(0.8, 0.8, size - 1.6, size - 1.6))

    pen = QPen(QColor("#ffffff"))
    pen.setWidthF(max(1.6, size * 0.1))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    s = float(size)

    if kind == "success":
        painter.drawLine(QPointF(0.28 * s, 0.53 * s), QPointF(0.44 * s, 0.69 * s))
        painter.drawLine(QPointF(0.44 * s, 0.69 * s), QPointF(0.74 * s, 0.33 * s))
    elif kind == "error":
        painter.drawLine(QPointF(0.34 * s, 0.34 * s), QPointF(0.66 * s, 0.66 * s))
        painter.drawLine(QPointF(0.66 * s, 0.34 * s), QPointF(0.34 * s, 0.66 * s))
    else:
        painter.drawLine(QPointF(0.5 * s, 0.27 * s), QPointF(0.5 * s, 0.58 * s))
        painter.setBrush(QColor("#ffffff"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(0.5 * s, 0.71 * s), 0.06 * s, 0.06 * s)

    painter.end()
    return QIcon(pixmap)


def line_icon(kind: str, color: str = "#5a6a7e", size: int = 16) -> QIcon:
    """Hand-drawn line icons so menus and buttons render consistently."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(QColor(color))
    pen.setWidthF(max(1.4, size * 0.1))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    s = float(size) / 16.0

    def p(x: float, y: float) -> QPointF:
        return QPointF(x * s, y * s)

    if kind == "search":
        painter.drawEllipse(QRectF(3.4 * s, 3.4 * s, 7.2 * s, 7.2 * s))
        painter.drawLine(p(10.6, 10.6), p(14.0, 14.0))
    elif kind == "add":
        painter.drawLine(p(8, 2.8), p(8, 13.2))
        painter.drawLine(p(2.8, 8), p(13.2, 8))
    elif kind == "gear":
        painter.drawEllipse(QRectF(5.2 * s, 5.2 * s, 5.6 * s, 5.6 * s))
        painter.drawEllipse(QRectF(2.4 * s, 2.4 * s, 11.2 * s, 11.2 * s))
        painter.drawLine(p(8, 0.8), p(8, 3.0))
        painter.drawLine(p(8, 13.0), p(8, 15.2))
        painter.drawLine(p(0.8, 8), p(3.0, 8))
        painter.drawLine(p(13.0, 8), p(15.2, 8))
        painter.drawLine(p(2.8, 2.8), p(4.4, 4.4))
        painter.drawLine(p(13.2, 2.8), p(11.6, 4.4))
        painter.drawLine(p(2.8, 13.2), p(4.4, 11.6))
        painter.drawLine(p(13.2, 13.2), p(11.6, 11.6))
    elif kind == "pin":
        painter.drawLine(p(8, 1.6), p(8, 9.4))
        painter.drawLine(p(5.4, 3.2), p(10.6, 3.2))
        painter.drawLine(p(6.2, 3.2), p(6.2, 8.2))
        painter.drawLine(p(9.8, 3.2), p(9.8, 8.2))
        painter.drawLine(p(4.6, 8.2), p(11.4, 8.2))
        painter.drawLine(p(8, 8.2), p(8, 14.2))
    elif kind == "edit":
        painter.drawLine(p(3, 13), p(3, 10.6))
        painter.drawLine(p(3, 10.6), p(10.4, 3.2))
        painter.drawLine(p(10.4, 3.2), p(12.8, 5.6))
        painter.drawLine(p(12.8, 5.6), p(5.4, 13))
        painter.drawLine(p(3, 13), p(5.4, 13))
    elif kind == "note":
        painter.drawRoundedRect(QRectF(3.4 * s, 2.6 * s, 9.2 * s, 10.8 * s), 1.6 * s, 1.6 * s)
        painter.drawLine(p(5.6, 6.2), p(10.4, 6.2))
        painter.drawLine(p(5.6, 8.6), p(10.4, 8.6))
        painter.drawLine(p(5.6, 11.0), p(8.4, 11.0))
    elif kind == "move":
        painter.drawRoundedRect(QRectF(2.6 * s, 5.4 * s, 10.8 * s, 8.0 * s), 1.6 * s, 1.6 * s)
        painter.drawLine(p(5.6, 5.4), p(5.6, 3.4))
        painter.drawLine(p(5.6, 3.4), p(10.4, 3.4))
        painter.drawLine(p(10.4, 3.4), p(10.4, 5.4))
    elif kind == "delete":
        painter.drawLine(p(3, 4.4), p(13, 4.4))
        painter.drawLine(p(6.4, 4.4), p(6.4, 2.8))
        painter.drawLine(p(6.4, 2.8), p(9.6, 2.8))
        painter.drawLine(p(9.6, 2.8), p(9.6, 4.4))
        painter.drawLine(p(4.4, 4.4), p(5.0, 13.2))
        painter.drawLine(p(11.6, 4.4), p(11.0, 13.2))
        painter.drawLine(p(5.0, 13.2), p(11.0, 13.2))
    elif kind == "clear":
        painter.drawLine(p(3.4, 8), p(12.6, 8))
        painter.drawLine(p(3.4, 8), p(6.0, 5.4))
        painter.drawLine(p(3.4, 8), p(6.0, 10.6))
        painter.drawLine(p(7.4, 5.4), p(12.6, 5.4))
        painter.drawLine(p(7.4, 10.6), p(12.6, 10.6))
    elif kind == "tab_add":
        painter.drawLine(p(8, 3.2), p(8, 12.8))
        painter.drawLine(p(3.2, 8), p(12.8, 8))
    elif kind == "tab_rename":
        painter.drawLine(p(3, 12.4), p(3, 9.8))
        painter.drawLine(p(3, 9.8), p(10.0, 2.8))
        painter.drawLine(p(10.0, 2.8), p(12.6, 5.4))
        painter.drawLine(p(12.6, 5.4), p(5.6, 12.4))
        painter.drawLine(p(3, 12.4), p(5.6, 12.4))
    elif kind == "tab_delete":
        painter.drawRoundedRect(QRectF(3.0 * s, 3.4 * s, 10.0 * s, 9.2 * s), 1.6 * s, 1.6 * s)
        painter.drawLine(p(5.6, 6.2), p(10.4, 10.4))
        painter.drawLine(p(10.4, 6.2), p(5.6, 10.4))
    elif kind == "show":
        painter.drawEllipse(QRectF(3.4 * s, 4.4 * s, 9.2 * s, 7.2 * s))
        painter.drawEllipse(QRectF(6.6 * s, 6.2 * s, 2.8 * s, 2.8 * s))
    elif kind == "exit":
        painter.drawLine(p(9.6, 2.8), p(3.4, 2.8))
        painter.drawLine(p(3.4, 2.8), p(3.4, 13.2))
        painter.drawLine(p(3.4, 13.2), p(9.6, 13.2))
        painter.drawLine(p(7.0, 8), p(13.2, 8))
        painter.drawLine(p(10.6, 5.4), p(13.2, 8))
        painter.drawLine(p(10.6, 10.6), p(13.2, 8))
    elif kind == "capture_on":
        painter.drawEllipse(QRectF(4.4 * s, 4.4 * s, 7.2 * s, 7.2 * s))
        painter.setBrush(QColor(color))
        painter.drawEllipse(QRectF(6.6 * s, 6.6 * s, 2.8 * s, 2.8 * s))
    elif kind == "capture_off":
        painter.drawEllipse(QRectF(4.4 * s, 4.4 * s, 7.2 * s, 7.2 * s))
        painter.drawLine(p(4.2, 11.8), p(11.8, 4.2))
    elif kind == "check":
        painter.drawLine(p(3.2, 8.4), p(6.6, 11.8))
        painter.drawLine(p(6.6, 11.8), p(12.8, 4.4))
    elif kind == "close":
        painter.drawLine(p(4, 4), p(12, 12))
        painter.drawLine(p(12, 4), p(4, 12))
    elif kind == "copy":
        painter.drawRoundedRect(QRectF(5.4 * s, 3.0 * s, 7.6 * s, 8.0 * s), 1.4 * s, 1.4 * s)
        painter.drawLine(p(3.0, 5.0), p(3.0, 12.8))
        painter.drawLine(p(3.0, 12.8), p(10.4, 12.8))
    elif kind == "nav_general":
        painter.drawLine(p(3.0, 5.4), p(13.0, 5.4))
        painter.drawEllipse(QRectF(4.6 * s, 3.9 * s, 3.0 * s, 3.0 * s))
        painter.drawLine(p(3.0, 10.6), p(13.0, 10.6))
        painter.drawEllipse(QRectF(8.4 * s, 9.1 * s, 3.0 * s, 3.0 * s))
    elif kind == "nav_appearance":
        painter.drawEllipse(QRectF(2.8 * s, 2.8 * s, 10.4 * s, 10.4 * s))
        painter.setBrush(QColor(color))
        painter.drawEllipse(QPointF(6.0 * s, 6.2 * s), 1.0 * s, 1.0 * s)
        painter.drawEllipse(QPointF(10.0 * s, 6.6 * s), 1.0 * s, 1.0 * s)
        painter.drawEllipse(QPointF(7.4 * s, 10.2 * s), 1.0 * s, 1.0 * s)
    elif kind == "nav_note":
        painter.drawRoundedRect(QRectF(3.4 * s, 2.6 * s, 9.2 * s, 10.8 * s), 1.6 * s, 1.6 * s)
        painter.drawLine(p(5.6, 6.2), p(10.4, 6.2))
        painter.drawLine(p(5.6, 8.6), p(10.4, 8.6))
        painter.drawLine(p(5.6, 11.0), p(8.4, 11.0))
    elif kind == "nav_data":
        painter.drawEllipse(QRectF(3.6 * s, 2.8 * s, 8.8 * s, 3.2 * s))
        painter.drawLine(p(3.6, 4.4), p(3.6, 11.6))
        painter.drawLine(p(12.4, 4.4), p(12.4, 11.6))
        painter.drawEllipse(QRectF(3.6 * s, 10.0 * s, 8.8 * s, 3.2 * s))
    elif kind == "nav_about":
        painter.drawEllipse(QRectF(3.0 * s, 3.0 * s, 10.0 * s, 10.0 * s))
        painter.setBrush(QColor(color))
        painter.drawEllipse(QPointF(8.0 * s, 5.6 * s), 0.7 * s, 0.7 * s)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(p(8.0, 8.0), p(8.0, 11.2))
    else:
        painter.drawEllipse(QRectF(5.0 * s, 5.0 * s, 6.0 * s, 6.0 * s))

    painter.end()
    return QIcon(pixmap)


def resolved_line_icon(kind: str, is_dark: bool, size: int = 16) -> QIcon:
    color = "#cdd8e6" if is_dark else "#5a6a7e"
    return line_icon(kind, color, size)


def menu_icon(kind: str, is_dark: bool, danger: bool = False) -> QIcon:
    if danger:
        color = "#e07a72" if is_dark else "#c2413d"
    else:
        color = "#c8d3e2" if is_dark else "#4a5866"
    return line_icon(kind, color, 16)


def color_for_menu(is_dark: bool, danger: bool = False) -> str:
    if danger:
        return "#e07a72" if is_dark else "#c2413d"
    return "#c8d3e2" if is_dark else "#4a5866"


def empty_icon() -> QIcon:
    return QIcon(QPixmap(1, 1))
