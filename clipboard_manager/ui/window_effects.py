from __future__ import annotations

import ctypes
import logging
import sys

logger = logging.getLogger(__name__)

_ACCENT_DISABLED = 0
_ACCENT_ENABLE_BLURBEHIND = 3
_ACCENT_ENABLE_ACRYLICBLURBEHIND = 4
_WCA_ACCENT_POLICY = 19
# Flags that make the acrylic fill the whole client area including rounded corners.
_ACCENT_FLAGS = 0x20 | 0x40 | 0x80 | 0x100


class _AccentPolicy(ctypes.Structure):
    _fields_ = [
        ("AccentState", ctypes.c_int),
        ("AccentFlags", ctypes.c_int),
        ("GradientColor", ctypes.c_uint),
        ("AnimationId", ctypes.c_int),
    ]


class _WinCompAttrData(ctypes.Structure):
    _fields_ = [
        ("Attribute", ctypes.c_int),
        ("Data", ctypes.POINTER(_AccentPolicy)),
        ("SizeOfData", ctypes.c_size_t),
    ]


def _available() -> bool:
    return sys.platform == "win32"


def _apply(hwnd: int, accent_state: int, gradient_color: int) -> bool:
    if not _available() or not hwnd:
        return False
    try:
        user32 = ctypes.windll.user32
        set_attr = user32.SetWindowCompositionAttribute
        set_attr.argtypes = [ctypes.c_void_p, ctypes.POINTER(_WinCompAttrData)]
        set_attr.restype = ctypes.c_int
        accent = _AccentPolicy(accent_state, _ACCENT_FLAGS, gradient_color, 0)
        data = _WinCompAttrData(
            _WCA_ACCENT_POLICY,
            ctypes.pointer(accent),
            ctypes.sizeof(accent),
        )
        return bool(set_attr(ctypes.c_void_p(int(hwnd)), ctypes.byref(data)))
    except Exception:
        logger.debug("SetWindowCompositionAttribute failed", exc_info=True)
        return False


def argb_tint(color_hex: str, alpha: int) -> int:
    """Pack #rrggbb + alpha into the 0xAABBGGRR value the accent policy expects."""
    text = (color_hex or "").strip().lstrip("#")
    if len(text) != 6:
        text = "f6fafe"
    try:
        r = int(text[0:2], 16)
        g = int(text[2:4], 16)
        b = int(text[4:6], 16)
    except ValueError:
        r, g, b = 0xF6, 0xFA, 0xFE
    a = max(0, min(255, int(alpha)))
    return (a << 24) | (b << 16) | (g << 8) | r


def apply_acrylic(hwnd: int, tint_argb: int) -> bool:
    return _apply(hwnd, _ACCENT_ENABLE_ACRYLICBLURBEHIND, tint_argb)


def apply_blur(hwnd: int, tint_argb: int) -> bool:
    return _apply(hwnd, _ACCENT_ENABLE_BLURBEHIND, tint_argb)


def disable_backdrop(hwnd: int) -> bool:
    return _apply(hwnd, _ACCENT_DISABLED, 0)
