from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import QApplication


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "assets" / "desktop_icon"
PNG_DIR = OUT_DIR / "png"
SIZES = (16, 32, 48, 64, 128, 256, 512, 1024)


def _color(hex_value: str, alpha: int | None = None) -> QColor:
    c = QColor(hex_value)
    if alpha is not None:
        c.setAlpha(alpha)
    return c


def _round_rect_path(x: float, y: float, w: float, h: float, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(QRectF(x, y, w, h), radius, radius)
    return path


def _draw_soft_shadow(
    painter: QPainter,
    path: QPainterPath,
    offset_y: float,
    color: QColor,
    layers: int,
    spread: float,
) -> None:
    for i in range(layers, 0, -1):
        alpha = max(1, int(color.alpha() * (i / layers) ** 2))
        c = QColor(color)
        c.setAlpha(alpha)
        painter.save()
        painter.translate(0, offset_y + i * spread / layers)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(c)
        painter.drawPath(path)
        painter.restore()


def _draw_rotated_sheet(
    painter: QPainter,
    cx: float,
    cy: float,
    x: float,
    y: float,
    w: float,
    h: float,
    radius: float,
    angle: float,
    opacity: float,
) -> None:
    painter.save()
    painter.translate(cx, cy)
    painter.rotate(angle)
    painter.translate(-cx, -cy)
    path = _round_rect_path(x, y, w, h, radius)
    _draw_soft_shadow(painter, path, 14, QColor(20, 81, 164, int(45 * opacity)), 8, 18)
    grad = QLinearGradient(x, y, x + w, y + h)
    grad.setColorAt(0.0, QColor(232, 247, 255, int(245 * opacity)))
    grad.setColorAt(1.0, QColor(153, 214, 250, int(235 * opacity)))
    painter.setPen(QPen(QColor(246, 252, 255, int(170 * opacity)), 3))
    painter.setBrush(grad)
    painter.drawPath(path)
    painter.restore()


def _draw_base(painter: QPainter) -> None:
    base = _round_rect_path(92, 92, 840, 840, 168)
    _draw_soft_shadow(painter, base, 22, QColor(15, 41, 82, 44), 14, 30)

    grad = QLinearGradient(100, 900, 900, 110)
    grad.setColorAt(0.0, QColor("#2468f2"))
    grad.setColorAt(0.48, QColor("#1fa8e6"))
    grad.setColorAt(1.0, QColor("#44dcc8"))
    painter.setPen(QPen(QColor(255, 255, 255, 76), 2))
    painter.setBrush(grad)
    painter.drawPath(base)

    glow = QRadialGradient(QPointF(800, 210), 430)
    glow.setColorAt(0.0, QColor(107, 255, 223, 88))
    glow.setColorAt(1.0, QColor(107, 255, 223, 0))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(glow)
    painter.drawPath(base)

    painter.setPen(QPen(QColor(255, 255, 255, 64), 4))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(QRectF(100, 101, 824, 824), 160, 160)


def _draw_clipboard(painter: QPainter, detailed: bool) -> None:
    if detailed:
        _draw_rotated_sheet(painter, 548, 560, 263, 292, 510, 536, 58, -7.5, 0.92)
        _draw_rotated_sheet(painter, 560, 562, 313, 292, 510, 536, 58, 8.5, 0.82)

    board = _round_rect_path(274, 244, 500, 588, 58)
    _draw_soft_shadow(painter, board, 19, QColor(19, 54, 111, 54), 13, 22)
    board_grad = QLinearGradient(274, 244, 774, 832)
    board_grad.setColorAt(0.0, QColor("#ffffff"))
    board_grad.setColorAt(0.58, QColor("#fbfdff"))
    board_grad.setColorAt(1.0, QColor("#edf5ff"))
    painter.setBrush(board_grad)
    painter.setPen(QPen(QColor("#f4f8fc"), 3))
    painter.drawPath(board)

    clip_loop = QPainterPath()
    clip_loop.addEllipse(QRectF(462, 139, 118, 118))
    inner = QPainterPath()
    inner.addEllipse(QRectF(501, 178, 40, 40))
    clip_loop = clip_loop.subtracted(inner)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#ffffff"))
    painter.drawPath(clip_loop)

    clip = _round_rect_path(386, 198, 306, 86, 26)
    clip_top = QPainterPath(clip)
    clip_top.addEllipse(QRectF(462, 139, 118, 118))
    clip_top = clip_top.subtracted(inner)
    _draw_soft_shadow(painter, clip_top, 9, QColor(24, 97, 184, 50), 8, 12)
    clip_grad = QLinearGradient(386, 168, 690, 286)
    clip_grad.setColorAt(0.0, QColor("#dcefff"))
    clip_grad.setColorAt(1.0, QColor("#8fc5f4"))
    painter.setBrush(clip_grad)
    painter.setPen(QPen(QColor("#ffffff"), 5))
    painter.drawPath(clip_top)
    painter.setPen(QPen(QColor("#3a92e9"), 4))
    painter.drawLine(416, 286, 662, 286)


def _draw_text_icon(painter: QPainter, box: QRectF) -> None:
    font = QFont("Segoe UI", 74)
    font.setWeight(QFont.Weight.DemiBold)
    painter.setFont(font)
    painter.setPen(QPen(QColor("#277bf3"), 7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawText(box, int(Qt.AlignmentFlag.AlignCenter), "T")


def _draw_image_icon(painter: QPainter, x: float, y: float) -> None:
    path = QPainterPath()
    path.moveTo(x + 28, y + 78)
    path.lineTo(x + 64, y + 25)
    path.quadTo(x + 71, y + 15, x + 80, y + 26)
    path.lineTo(x + 107, y + 61)
    path.lineTo(x + 126, y + 39)
    path.quadTo(x + 134, y + 29, x + 142, y + 43)
    path.lineTo(x + 168, y + 83)
    path.quadTo(x + 175, y + 96, x + 157, y + 96)
    path.lineTo(x + 39, y + 96)
    path.quadTo(x + 20, y + 96, x + 28, y + 78)
    grad = QLinearGradient(x + 20, y + 18, x + 170, y + 105)
    grad.setColorAt(0.0, QColor("#20cfe0"))
    grad.setColorAt(1.0, QColor("#26bda7"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(grad)
    painter.drawPath(path)
    painter.setBrush(QColor("#32d3ca"))
    painter.drawEllipse(QRectF(x + 116, y + 6, 22, 22))


def _draw_link_icon(painter: QPainter, x: float, y: float) -> None:
    pen = QPen(QColor("#2e77ee"), 19, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawArc(QRectF(x + 16, y + 32, 84, 58), 40 * 16, 270 * 16)
    painter.drawArc(QRectF(x + 72, y + 6, 84, 58), 220 * 16, 270 * 16)
    painter.drawLine(QPointF(x + 67, y + 66), QPointF(x + 103, y + 38))


def _draw_rows(painter: QPainter, detailed: bool) -> None:
    rows = [(328, 326), (328, 482), (328, 638)]
    if not detailed:
        rows = [(368, 378), (368, 534)]

    for index, (x, y) in enumerate(rows):
        if detailed:
            if index > 0:
                painter.setPen(QPen(QColor(226, 233, 242, 150), 2))
                painter.drawLine(298, y - 34, 730, y - 34)
            tile = _round_rect_path(x, y, 114, 114, 25)
            _draw_soft_shadow(painter, tile, 9, QColor(24, 62, 116, 25), 7, 10)
            tile_grad = QLinearGradient(x, y, x + 114, y + 114)
            tile_grad.setColorAt(0, QColor("#ffffff"))
            tile_grad.setColorAt(1, QColor("#f3f8ff"))
            painter.setBrush(tile_grad)
            painter.setPen(QPen(QColor("#eef3fa"), 2))
            painter.drawPath(tile)

        line_x = x + (148 if detailed else 0)
        line_y = y + (28 if detailed else 0)
        line_pen = QPen(QColor("#b7d3f4"), 16 if detailed else 22, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(line_pen)
        painter.drawLine(line_x, line_y + 12, line_x + (232 if detailed else 260), line_y + 12)
        painter.setPen(QPen(QColor("#c4d9f4"), 15 if detailed else 20, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(line_x, line_y + 54, line_x + (170 if index != 2 else 92), line_y + 54)

        if detailed:
            if index == 0:
                _draw_text_icon(painter, QRectF(x + 24, y + 17, 66, 78))
            elif index == 1:
                _draw_image_icon(painter, x + 17, y + 23)
            else:
                _draw_link_icon(painter, x + 14, y + 24)


def _draw_badge(painter: QPainter, detailed: bool) -> None:
    if not detailed:
        center = QPointF(692, 690)
        outer_r = 108
        inner_r = 82
    else:
        center = QPointF(690, 720)
        outer_r = 112
        inner_r = 84

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(16, 65, 106, 42))
    painter.drawEllipse(QRectF(center.x() - outer_r + 8, center.y() - outer_r + 14, outer_r * 2, outer_r * 2))
    painter.setBrush(QColor("#f8fbff"))
    painter.drawEllipse(QRectF(center.x() - outer_r, center.y() - outer_r, outer_r * 2, outer_r * 2))
    bg = QLinearGradient(center.x() - inner_r, center.y() - inner_r, center.x() + inner_r, center.y() + inner_r)
    bg.setColorAt(0, QColor("#31d9df"))
    bg.setColorAt(1, QColor("#22b99e"))
    painter.setBrush(bg)
    painter.drawEllipse(QRectF(center.x() - inner_r, center.y() - inner_r, inner_r * 2, inner_r * 2))

    painter.setPen(QPen(QColor("#ffffff"), 13 if detailed else 20, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    sx = center.x() - 30
    sy = center.y() - 43
    painter.drawRoundedRect(QRectF(sx, sy + 16, 60, 74), 10, 10)
    painter.drawRoundedRect(QRectF(sx + 14, sy, 32, 28), 8, 8)
    painter.drawLine(QPointF(sx + 24, sy + 16), QPointF(sx + 36, sy + 16))


def draw_icon(size: int, detailed: bool) -> QImage:
    scale = 4 if size <= 64 else 1
    canvas_size = size * scale
    img = QImage(canvas_size, canvas_size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)

    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    painter.scale(canvas_size / 1024.0, canvas_size / 1024.0)
    _draw_base(painter)
    _draw_clipboard(painter, detailed=detailed)
    _draw_rows(painter, detailed=detailed)
    _draw_badge(painter, detailed=detailed)
    painter.end()

    if scale != 1:
        return img.scaled(size, size, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    return img


def _png_bytes(path: Path) -> bytes:
    return path.read_bytes()


def write_ico(png_paths: dict[int, Path], out_path: Path) -> None:
    sizes = [16, 32, 48, 64, 128, 256]
    entries = []
    data_blobs = []
    offset = 6 + 16 * len(sizes)
    for size in sizes:
        data = _png_bytes(png_paths[size])
        width = 0 if size == 256 else size
        height = 0 if size == 256 else size
        entries.append(struct.pack("<BBBBHHII", width, height, 0, 0, 1, 32, len(data), offset))
        data_blobs.append(data)
        offset += len(data)
    with out_path.open("wb") as f:
        f.write(struct.pack("<HHH", 0, 1, len(sizes)))
        for entry in entries:
            f.write(entry)
        for data in data_blobs:
            f.write(data)


def write_icns(png_paths: dict[int, Path], out_path: Path) -> None:
    chunks = [
        ("icp4", png_paths[16]),
        ("icp5", png_paths[32]),
        ("icp6", png_paths[64]),
        ("ic07", png_paths[128]),
        ("ic08", png_paths[256]),
        ("ic09", png_paths[512]),
        ("ic10", png_paths[1024]),
    ]
    payloads = []
    total = 8
    for code, path in chunks:
        data = _png_bytes(path)
        payload = code.encode("ascii") + struct.pack(">I", len(data) + 8) + data
        payloads.append(payload)
        total += len(payload)
    with out_path.open("wb") as f:
        f.write(b"icns")
        f.write(struct.pack(">I", total))
        for payload in payloads:
            f.write(payload)


def write_flat_svg(out_path: Path) -> None:
    out_path.write_text(
        """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">
  <defs>
    <linearGradient id="bg" x1="128" y1="896" x2="896" y2="128" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#2468f2"/>
      <stop offset=".55" stop-color="#1fa8e6"/>
      <stop offset="1" stop-color="#44dcc8"/>
    </linearGradient>
    <linearGradient id="badge" x1="588" y1="620" x2="770" y2="802" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#31d9df"/>
      <stop offset="1" stop-color="#22b99e"/>
    </linearGradient>
  </defs>
  <rect x="92" y="92" width="840" height="840" rx="168" fill="url(#bg)"/>
  <rect x="276" y="248" width="500" height="584" rx="58" fill="#fff"/>
  <path d="M464 198a76 76 0 0 1 152 0h72a34 34 0 0 1 34 34v36a34 34 0 0 1-34 34H390a34 34 0 0 1-34-34v-36a34 34 0 0 1 34-34h74Zm76-26a26 26 0 1 0 0 52 26 26 0 0 0 0-52Z" fill="#c9e3fb"/>
  <rect x="358" y="382" width="108" height="108" rx="24" fill="#f4f8ff"/>
  <path d="M389 421h46m-23 0v48m-22 0h44" stroke="#277bf3" stroke-width="18" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M516 416h234M516 470h168M516 578h234M516 632h156" stroke="#b7d3f4" stroke-width="18" stroke-linecap="round"/>
  <circle cx="690" cy="720" r="112" fill="#f8fbff"/>
  <circle cx="690" cy="720" r="84" fill="url(#badge)"/>
  <path d="M660 693h60v74h-60zM674 673h32v28" fill="none" stroke="#fff" stroke-width="14" stroke-linejoin="round" stroke-linecap="round"/>
</svg>
""",
        encoding="utf-8",
    )


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    del app
    PNG_DIR.mkdir(parents=True, exist_ok=True)

    png_paths: dict[int, Path] = {}
    for size in SIZES:
        detailed = size >= 128
        img = draw_icon(size, detailed=detailed)
        path = PNG_DIR / f"clipnest-{size}.png"
        if not img.save(str(path), "PNG"):
            raise RuntimeError(f"Failed to save {path}")
        png_paths[size] = path

    main_png = OUT_DIR / "clipnest-icon-1024.png"
    QImage(str(png_paths[1024])).save(str(main_png), "PNG")
    write_ico(png_paths, OUT_DIR / "clipnest.ico")
    write_icns(png_paths, OUT_DIR / "clipnest.icns")
    write_flat_svg(OUT_DIR / "clipnest-flat-logo.svg")
    print(f"Wrote icon assets to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
