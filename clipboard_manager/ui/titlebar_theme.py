"""Windows title bar (DWM non-client area) theming helpers.

The window caption is drawn by the OS, not by our stylesheet, so switching the
app theme leaves it light unless we ask DWM to restyle it. Windows 10 2004+
supports dark mode captions; Windows 11 22000+ also allows an explicit caption
color so it can match the app background exactly.

All calls fail silently on unsupported platforms/builds.
"""

from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)

# DwmSetWindowAttribute attribute ids.
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_USE_IMMERSIVE_DARK_MODE_LEGACY = 19  # Windows 10 build < 19041
_DWMWA_CAPTION_COLOR = 35  # Windows 11 22000+
_DWMWA_TEXT_COLOR = 36  # Windows 11 22000+
_DWMWA_BORDER_COLOR = 34  # Windows 11 22000+


def _hex_to_colorref(color_hex: str) -> int | None:
    """Convert '#rrggbb' to Win32 COLORREF (0x00bbggrr)."""
    text = (color_hex or "").strip().lstrip("#")
    if len(text) != 6:
        return None
    try:
        r = int(text[0:2], 16)
        g = int(text[2:4], 16)
        b = int(text[4:6], 16)
    except ValueError:
        return None
    return (b << 16) | (g << 8) | r


def _windows_build() -> int:
    if sys.platform != "win32":
        return 0
    try:
        return int(sys.getwindowsversion().build)
    except Exception:
        return 0


def apply_titlebar_theme(
    hwnd: int,
    dark: bool,
    caption_hex: str | None = None,
    text_hex: str | None = None,
) -> bool:
    """Restyle a window's caption to match the app theme.

    Returns True when at least one attribute was applied.
    """
    if sys.platform != "win32" or not hwnd:
        return False

    try:
        import ctypes
        from ctypes import wintypes

        dwmapi = ctypes.windll.dwmapi
    except Exception:
        return False

    applied = False
    build = _windows_build()

    def set_attr(attribute: int, value: int) -> bool:
        try:
            data = ctypes.c_int(int(value))
            result = dwmapi.DwmSetWindowAttribute(
                wintypes.HWND(hwnd),
                ctypes.c_uint(attribute),
                ctypes.byref(data),
                ctypes.sizeof(data),
            )
            return result == 0
        except Exception:
            return False

    # Dark caption: try modern id first, fall back to the legacy one.
    if set_attr(_DWMWA_USE_IMMERSIVE_DARK_MODE, 1 if dark else 0):
        applied = True
    elif set_attr(_DWMWA_USE_IMMERSIVE_DARK_MODE_LEGACY, 1 if dark else 0):
        applied = True

    # Windows 11 lets us match the caption color to the app background.
    if build >= 22000:
        if caption_hex:
            colorref = _hex_to_colorref(caption_hex)
            if colorref is not None and set_attr(_DWMWA_CAPTION_COLOR, colorref):
                applied = True
        if text_hex:
            colorref = _hex_to_colorref(text_hex)
            if colorref is not None and set_attr(_DWMWA_TEXT_COLOR, colorref):
                applied = True
        if caption_hex:
            colorref = _hex_to_colorref(caption_hex)
            if colorref is not None:
                set_attr(_DWMWA_BORDER_COLOR, colorref)

    logger.debug(
        "[Theme] titlebar applied dark=%s caption=%s build=%s ok=%s",
        dark,
        caption_hex,
        build,
        applied,
    )
    return applied
