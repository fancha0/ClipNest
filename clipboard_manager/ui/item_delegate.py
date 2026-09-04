from __future__ import annotations

import re

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QStyledItemDelegate, QStyle, QStyleOptionViewItem

from .theme import ThemeTokens, default_light_business_theme


class ClipItemDelegate(QStyledItemDelegate):
    # Pinned cards get a clean accent tint (blend, not lighter()) plus an accent border.
    _PINNED_TINT_RATIO = 0.16
    _PINNED_BORDER_RATIO = 0.55

    def __init__(
        self,
        note_role: int,
        content_role: int,
        has_note_role: int,
        secondary_role: int,
        type_label_role: int,
        pinned_role: int,
        pinned_color: str,
        note_color: str,
        note_font_size: int,
        tokens: ThemeTokens | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._note_role = int(note_role)
        self._content_role = int(content_role)
        self._has_note_role = int(has_note_role)
        self._secondary_role = int(secondary_role)
        self._type_label_role = int(type_label_role)
        self._pinned_role = int(pinned_role)
        self._pinned_color = self._normalized_color(pinned_color, "#1fb8cb")
        self._note_color = QColor(note_color)
        self._note_font_size = int(note_font_size)
        self._tokens = tokens or default_light_business_theme()
        self._antialias_enabled = True

    def set_note_style(self, note_color: str, note_font_size: int) -> None:
        self._note_color = QColor(note_color)
        self._note_font_size = int(note_font_size)

    def set_pinned_color(self, color_hex: str) -> None:
        self._pinned_color = self._normalized_color(color_hex, "#1fb8cb")

    def set_theme_tokens(self, tokens: ThemeTokens) -> None:
        self._tokens = tokens or default_light_business_theme()

    def set_antialias_enabled(self, enabled: bool) -> None:
        self._antialias_enabled = bool(enabled)

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        base = super().sizeHint(option, index)
        has_note = bool(index.data(self._has_note_role)) and bool(
            str(index.data(self._note_role) or "").strip()
        )
        main_height = QFontMetrics(option.font).height()
        if has_note:
            note_font = QFont(option.font)
            note_font.setPointSize(self._note_font_size)
            note_height = QFontMetrics(note_font).height()
            main_height = max(
                main_height,
                note_height + self._tokens.note_badge_padding_y * 2,
            )

        secondary_font = QFont(option.font)
        secondary_font.setPointSize(max(9, secondary_font.pointSize() - 1))
        secondary_height = max(20, QFontMetrics(secondary_font).height())
        card_height = 28 + main_height + 3 + secondary_height
        return QSize(base.width(), max(76, base.height(), card_height))

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.state &= ~QStyle.StateFlag.State_HasFocus
        opt.text = ""
        opt.icon = QIcon()

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, self._antialias_enabled)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, self._antialias_enabled)
        painter.save()
        painter.setClipRect(option.rect)

        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        pinned = bool(index.data(self._pinned_role))
        card_rect = QRectF(option.rect.adjusted(5, 4, -5, -4))
        self._draw_card(painter, card_rect, selected=selected, hovered=hovered, pinned=pinned)

        text_rect = option.rect.adjusted(19, 14, -19, -14)
        if pinned:
            text_rect.setLeft(text_rect.left() + 4)
            pin_rect = self._draw_pin_glyph(painter, text_rect)
            text_rect.setRight(max(text_rect.left(), pin_rect.left() - 8))

        icon_data = index.data(Qt.ItemDataRole.DecorationRole)
        if isinstance(icon_data, QIcon) and not icon_data.isNull():
            base_size = option.decorationSize if option.decorationSize.isValid() else QSize(18, 18)
            src_w = max(1, int(base_size.width()))
            src_h = max(1, int(base_size.height()))
            max_icon_h = max(18, text_rect.height())
            max_icon_w = max(18, min(text_rect.width() // 3, 104))
            scale = min(max_icon_w / float(src_w), max_icon_h / float(src_h), 1.0)
            draw_w = max(1, int(round(src_w * scale)))
            draw_h = max(1, int(round(src_h * scale)))
            icon_rect = QRect(
                text_rect.left(),
                text_rect.center().y() - draw_h // 2,
                draw_w,
                draw_h,
            )
            if icon_rect.top() < text_rect.top():
                icon_rect.moveTop(text_rect.top())
            if icon_rect.bottom() > text_rect.bottom():
                icon_rect.moveBottom(text_rect.bottom())

            icon_frame = QRectF(icon_rect.adjusted(-6, -5, 6, 5))
            dark = bool(getattr(self._tokens, "is_dark", False))
            painter.setPen(
                QPen(
                    self._parse_token_color(
                        self._tokens.item_border,
                        fallback=QColor(70, 84, 106) if dark else QColor(232, 237, 244),
                    ),
                    1,
                )
            )
            painter.setBrush(
                self._parse_token_color(
                    self._tokens.input_bg,
                    fallback=QColor(46, 56, 72) if dark else QColor(248, 250, 252),
                )
            )
            painter.drawRoundedRect(icon_frame, 6.0, 6.0)
            clip_path = QPainterPath()
            clip_path.addRoundedRect(icon_frame.adjusted(1, 1, -1, -1), 5.0, 5.0)
            painter.save()
            painter.setClipPath(clip_path)
            icon_data.paint(
                painter,
                icon_rect,
                Qt.AlignmentFlag.AlignCenter,
                QIcon.Mode.Normal,
                QIcon.State.On if option.state & QStyle.StateFlag.State_Selected else QIcon.State.Off,
            )
            painter.restore()
            text_rect.setLeft(min(text_rect.right(), int(icon_frame.right()) + 12))

        note_text = str(index.data(self._note_role) or "").strip()
        content_text = str(index.data(self._content_role) or "").strip()
        secondary_text = str(index.data(self._secondary_role) or "").strip()
        type_label = str(index.data(self._type_label_role) or "").strip()
        has_note = bool(index.data(self._has_note_role)) and bool(note_text)
        if not content_text:
            content_text = str(index.data(Qt.ItemDataRole.DisplayRole) or "").strip()
        pill_rect = self._draw_type_pill(painter, text_rect, type_label) if type_label else QRect()
        main_rect = QRect(text_rect)
        if not pill_rect.isNull():
            main_rect.setRight(max(main_rect.left(), pill_rect.left() - 10))
        secondary_rect = QRect(text_rect.left(), text_rect.bottom() - 20, text_rect.width(), 20)
        main_rect.setBottom(secondary_rect.top() - 3)

        if has_note:
            content_rect = self._draw_note_badge_and_content(
                painter=painter,
                rect=main_rect,
                note_text=note_text,
                content_text=content_text,
                selected=selected,
            )
            self._draw_plain_content(
                painter,
                content_rect,
                content_text,
                selected=selected,
                primary=True,
            )
        else:
            self._draw_plain_content(
                painter,
                main_rect,
                content_text,
                selected=selected,
                primary=True,
            )
        if secondary_text:
            self._draw_plain_content(
                painter,
                secondary_rect,
                secondary_text,
                selected=False,
                primary=False,
            )
        painter.restore()

    def _draw_card(self, painter: QPainter, rect: QRectF, selected: bool, hovered: bool, pinned: bool = False) -> None:
        dark = bool(getattr(self._tokens, "is_dark", False))
        shadow_rect = QRectF(rect)
        shadow_color = (10, 14, 22) if dark else (30, 42, 62)
        for offset, alpha in ((5, 16), (3, 18), (1, 12)):
            painter.setPen(Qt.PenStyle.NoPen)
            color = QColor(*shadow_color, alpha)
            painter.setBrush(color)
            painter.drawRoundedRect(shadow_rect.translated(0, offset / 2.0), 9.0, 9.0)

        if selected:
            glow_color = self._parse_token_color(
                self._tokens.item_selected_border,
                fallback=QColor(45, 166, 224),
            )
            for grow, alpha in ((4.0, 54), (2.0, 78)):
                glow = rect.adjusted(-grow, -grow, grow, grow)
                painter.setPen(QPen(self._color_with_alpha(glow_color, alpha), 1.2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(glow, 11.0, 11.0)

        base_fill = self._parse_token_color(
            self._tokens.item_bg,
            fallback=QColor(39, 48, 63) if dark else QColor(255, 255, 255),
        )
        fill = base_fill
        if selected:
            fill = self._parse_token_color(self._tokens.item_selected_bg, fallback=base_fill)
        elif pinned:
            fill = self._blend(base_fill, self._pinned_color, self._PINNED_TINT_RATIO)
        elif hovered:
            fill = base_fill.lighter(112) if dark else QColor(253, 254, 255)
        painter.setBrush(fill)

        border = self._parse_token_color(
            self._tokens.item_selected_border if selected else self._tokens.item_border,
            fallback=QColor(70, 84, 106) if dark else QColor(232, 237, 244),
        )
        border_width = 1.4 if selected else 1.0
        if pinned and not selected:
            border = self._blend(border, self._pinned_color, self._PINNED_BORDER_RATIO)
            border_width = 1.2
        painter.setPen(QPen(border, border_width))
        painter.drawRoundedRect(rect, 9.0, 9.0)

        if pinned:
            self._draw_pinned_accent_bar(painter, rect)

    @staticmethod
    def _blend(base: QColor, accent: QColor, ratio: float) -> QColor:
        """Mix accent into base by ratio, keeping the result clean (no muddy lighter())."""
        t = max(0.0, min(1.0, float(ratio)))
        return QColor(
            int(round(base.red() * (1.0 - t) + accent.red() * t)),
            int(round(base.green() * (1.0 - t) + accent.green() * t)),
            int(round(base.blue() * (1.0 - t) + accent.blue() * t)),
        )

    def _draw_pinned_accent_bar(self, painter: QPainter, rect: QRectF) -> None:
        """Rounded accent bar hugging the card's left edge (native status-marker style)."""
        bar_width = 3.0
        inset_y = 8.0
        bar_rect = QRectF(
            rect.left() + 1.5,
            rect.top() + inset_y,
            bar_width,
            max(4.0, rect.height() - inset_y * 2),
        )
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._pinned_color)
        painter.drawRoundedRect(bar_rect, bar_width / 2.0, bar_width / 2.0)
        painter.restore()

    def _draw_pin_glyph(self, painter: QPainter, anchor: QRect) -> QRect:
        """Small pin icon drawn at the card's top-right corner."""
        size = 13
        glyph_rect = QRect(anchor.right() - size, anchor.top(), size, size)
        cx = glyph_rect.center().x() + 0.5
        top = float(glyph_rect.top()) + 1.0
        head_r = 3.4
        head_cy = top + head_r

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        color = QColor(self._pinned_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        # pin head
        painter.drawEllipse(QRectF(cx - head_r, head_cy - head_r, head_r * 2, head_r * 2))
        # pin needle
        needle = QPainterPath()
        needle.moveTo(cx - 1.15, head_cy + head_r - 0.6)
        needle.lineTo(cx + 1.15, head_cy + head_r - 0.6)
        needle.lineTo(cx, float(glyph_rect.bottom()) - 0.5)
        needle.closeSubpath()
        painter.drawPath(needle)
        painter.restore()
        return glyph_rect

    @staticmethod
    def _normalized_color(color_hex: str, fallback: str) -> QColor:
        color = QColor(str(color_hex or "").strip())
        if not color.isValid():
            color = QColor(fallback)
        return color

    @staticmethod
    def _color_with_alpha(color: QColor, alpha: int) -> QColor:
        copy = QColor(color)
        copy.setAlpha(max(0, min(255, int(alpha))))
        return copy

    def _effective_note_color(self) -> QColor:
        """Lighten a dark user note color so it stays readable on dark cards."""
        if not bool(getattr(self._tokens, "is_dark", False)):
            return self._note_color
        color = QColor(self._note_color)
        luminance = (
            0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
        )
        if luminance >= 150:
            return color
        # Blend toward the card's primary text color for guaranteed contrast.
        target = self._parse_token_color(self._tokens.text_primary, fallback=QColor(226, 233, 245))
        ratio = 0.72
        return QColor(
            int(round(color.red() * (1 - ratio) + target.red() * ratio)),
            int(round(color.green() * (1 - ratio) + target.green() * ratio)),
            int(round(color.blue() * (1 - ratio) + target.blue() * ratio)),
        )
    def _draw_type_pill(self, painter: QPainter, rect: QRect, type_label: str) -> QRect:
        pill_font = QFont(painter.font())
        pill_font.setPointSize(max(9, painter.font().pointSize() - 2))
        pill_font.setWeight(QFont.Weight.Medium)
        fm = QFontMetrics(pill_font)
        label = fm.elidedText(type_label, Qt.TextElideMode.ElideRight, min(64, max(0, rect.width() // 3)))
        if not label:
            return QRect()
        pill_w = fm.horizontalAdvance(label) + 18
        pill_h = max(22, fm.height() + 4)
        pill_rect = QRect(rect.right() - pill_w, rect.top() + 1, pill_w, pill_h)

        dark = bool(getattr(self._tokens, "is_dark", False))
        painter.save()
        painter.setFont(pill_font)
        painter.setPen(
            QPen(
                self._parse_token_color(
                    self._tokens.item_border,
                    fallback=QColor(78, 92, 114) if dark else QColor(215, 222, 232),
                ),
                1,
            )
        )
        painter.setBrush(
            self._parse_token_color(
                self._tokens.input_bg,
                fallback=QColor(46, 56, 72) if dark else QColor(246, 248, 251),
            )
        )
        painter.drawRoundedRect(QRectF(pill_rect), pill_h / 2.0, pill_h / 2.0)
        painter.setPen(
            QPen(
                self._parse_token_color(
                    self._tokens.text_secondary,
                    fallback=QColor(168, 180, 200) if dark else QColor(100, 112, 128),
                )
            )
        )
        painter.drawText(
            pill_rect,
            int(Qt.AlignmentFlag.AlignCenter),
            label,
        )
        painter.restore()
        return pill_rect

    def _draw_note_badge_and_content(
        self,
        painter: QPainter,
        rect: QRect,
        note_text: str,
        content_text: str,
        selected: bool,
    ) -> QRect:
        del selected  # Reserved for future selected-state tone adjustments.
        original_font = QFont(painter.font())
        badge_font = QFont(painter.font())
        badge_font.setPointSize(self._note_font_size)
        fm = QFontMetrics(badge_font)

        max_badge_width = max(0, rect.width() - 12)
        elided_note = fm.elidedText(
            note_text,
            Qt.TextElideMode.ElideRight,
            max(0, max_badge_width - self._tokens.note_badge_padding_x * 2),
        )
        badge_text_width = fm.horizontalAdvance(elided_note)
        badge_h = max(20, fm.height() + self._tokens.note_badge_padding_y * 2)
        badge_w = min(
            max_badge_width,
            badge_text_width + self._tokens.note_badge_padding_x * 2,
        )
        if badge_w <= 0:
            return rect

        badge_rect = QRect(
            rect.left(),
            rect.center().y() - badge_h // 2,
            badge_w,
            badge_h,
        )

        bg = QColor(self._note_color)
        bg.setAlpha(max(0, min(255, self._tokens.note_badge_bg_alpha)))
        painter.setPen(QPen(bg.darker(115), 1))
        painter.setBrush(bg)
        painter.drawRoundedRect(
            badge_rect,
            float(self._tokens.note_badge_radius),
            float(self._tokens.note_badge_radius),
        )

        painter.setFont(badge_font)
        painter.setPen(QPen(self._effective_note_color()))
        note_text_rect = badge_rect.adjusted(
            self._tokens.note_badge_padding_x,
            0,
            -self._tokens.note_badge_padding_x,
            0,
        )
        painter.drawText(
            note_text_rect,
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            elided_note,
        )
        painter.setFont(original_font)

        content_left = badge_rect.right() + 8
        if content_left >= rect.right():
            return QRect(rect.right(), rect.top(), 0, rect.height())
        return QRect(content_left, rect.top(), rect.right() - content_left, rect.height())

    def _draw_plain_content(
        self,
        painter: QPainter,
        rect: QRect,
        text: str,
        selected: bool,
        primary: bool,
    ) -> None:
        if rect.width() <= 0:
            return
        font = QFont(painter.font())
        if primary:
            font.setWeight(QFont.Weight.Medium)
        else:
            font.setPointSize(max(9, font.pointSize() - 1))
        painter.setFont(font)
        fm = QFontMetrics(painter.font())
        elided = fm.elidedText(text, Qt.TextElideMode.ElideRight, rect.width())
        token = self._tokens.text_primary if primary else self._tokens.text_secondary
        if selected and primary:
            token = self._tokens.item_selected_text or token
        painter.setPen(QPen(self._parse_token_color(token, fallback=QColor(26, 40, 62, 236))))
        painter.drawText(
            rect,
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            elided,
        )

    @staticmethod
    def _parse_token_color(token: str, fallback: QColor) -> QColor:
        text = (token or "").strip()
        if text == "":
            return QColor(fallback)

        # QColor doesn't reliably parse CSS rgb()/rgba() strings directly.
        m = re.fullmatch(
            r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})(?:\s*,\s*(\d{1,3}))?\s*\)",
            text,
            flags=re.IGNORECASE,
        )
        if m:
            r = max(0, min(255, int(m.group(1))))
            g = max(0, min(255, int(m.group(2))))
            b = max(0, min(255, int(m.group(3))))
            a = 255 if m.group(4) is None else max(0, min(255, int(m.group(4))))
            return QColor(r, g, b, a)

        parsed = QColor(text)
        return parsed if parsed.isValid() else QColor(fallback)
