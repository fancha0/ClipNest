from __future__ import annotations

import logging
import re
import sys
from typing import Optional

from PySide6.QtCore import QObject, Signal
from pynput import keyboard

logger = logging.getLogger(__name__)


class HotkeyService(QObject):
    hotkey_pressed = Signal()

    def __init__(self, hotkey_text: str) -> None:
        super().__init__()
        self.hotkey_text = hotkey_text
        self._listener: Optional[keyboard.GlobalHotKeys] = None
        self.last_error: Optional[str] = None

    def start(self) -> bool:
        if self._listener is not None:
            logger.info("[Hotkey] start skipped; already running with config = %s", self.hotkey_text)
            return True

        logger.info("[Hotkey] current config = %s", self.hotkey_text)
        combo, combo_error = self._build_and_validate_combo(self.hotkey_text)
        if combo_error:
            self.last_error = combo_error
            logger.error("[Hotkey] validate failed for %s: %s", self.hotkey_text, combo_error)
            return False

        try:
            self._listener = keyboard.GlobalHotKeys({combo: self._on_hotkey_triggered})
            self._listener.start()
            self.last_error = None
            logger.info("[Hotkey] register shortcut = %s (%s) success", self.hotkey_text, combo)
            return True
        except Exception as exc:
            self.last_error = str(exc)
            self._listener = None
            logger.exception("[Hotkey] register shortcut = %s failed: %s", self.hotkey_text, exc)
            return False

    def stop(self) -> None:
        if self._listener is None:
            return
        logger.info("[Hotkey] unregister shortcut = %s", self.hotkey_text)
        try:
            self._listener.stop()
        except Exception as exc:
            logger.debug("[Hotkey] unregister failed for %s: %s", self.hotkey_text, exc)
        finally:
            self._listener = None

    def update_hotkey_registration(self, new_hotkey: str) -> tuple[bool, Optional[str]]:
        old_hotkey = self.hotkey_text
        was_running = self._listener is not None
        logger.info("[Hotkey] update requested: old = %s, new = %s", old_hotkey, new_hotkey)
        self.stop()

        self.hotkey_text = new_hotkey
        started = self.start()
        if started:
            logger.info("[Hotkey] update success: active = %s", self.hotkey_text)
            return True, None

        error = self.last_error or "Unknown hotkey error."
        self.hotkey_text = old_hotkey
        logger.error("[Hotkey] update failed for %s: %s", new_hotkey, error)
        if was_running:
            self.start()
            logger.info("[Hotkey] rollback to old shortcut = %s", old_hotkey)
        return False, error

    def update_hotkey(self, new_hotkey: str) -> tuple[bool, Optional[str]]:
        return self.update_hotkey_registration(new_hotkey)

    def _on_hotkey_triggered(self) -> None:
        logger.info("[Hotkey] triggered by %s", self.hotkey_text)
        self.hotkey_pressed.emit()

    @classmethod
    def _build_and_validate_combo(cls, hotkey_text: str) -> tuple[Optional[str], Optional[str]]:
        combo = cls._to_pynput_combo(hotkey_text)
        try:
            keyboard.HotKey.parse(combo)
            return combo, None
        except Exception:
            return None, f"快捷键不受支持或格式无效：{hotkey_text}"

    @staticmethod
    def normalize_hotkey(hotkey_text: str) -> tuple[Optional[str], Optional[str]]:
        if hotkey_text is None:
            return None, "快捷键不能为空。"

        raw = hotkey_text.strip()
        if not raw:
            return None, "快捷键不能为空。"
        if "," in raw:
            return None, "仅支持一个组合键。"

        parts = [part.strip() for part in raw.split("+") if part.strip()]
        if not parts:
            return None, "快捷键不能为空。"

        modifier_alias = {
            "ctrl": "Ctrl",
            "control": "Ctrl",
            "alt": "Alt",
            "option": "Alt",
            "shift": "Shift",
            "cmd": "Cmd",
            "command": "Cmd",
            "meta": "Win" if sys.platform == "win32" else "Cmd",
            "super": "Win" if sys.platform == "win32" else "Cmd",
            "win": "Win" if sys.platform == "win32" else "Cmd",
            "windows": "Win" if sys.platform == "win32" else "Cmd",
        }
        modifiers: set[str] = set()
        main_key: Optional[str] = None

        for part in parts:
            lowered = part.lower()
            if lowered in modifier_alias:
                modifiers.add(modifier_alias[lowered])
                continue
            if main_key is not None:
                return None, "仅支持一个主键。"
            main_key = HotkeyService._normalize_main_key(part)

        if not modifiers:
            return None, "快捷键至少包含一个修饰键（Ctrl/Alt/Shift/Cmd/Win）。"
        if not main_key:
            return None, "快捷键必须包含主键。"

        ordered_modifiers: list[str] = []
        for key in ("Ctrl", "Alt", "Shift", "Cmd", "Win"):
            if key in modifiers:
                ordered_modifiers.append(key)
        return "+".join([*ordered_modifiers, main_key]), None

    @staticmethod
    def _normalize_main_key(key: str) -> str:
        normalized_map = {
            "space": "Space",
            "tab": "Tab",
            "enter": "Enter",
            "return": "Enter",
            "esc": "Esc",
            "escape": "Esc",
            "delete": "Delete",
            "backspace": "Backspace",
            "insert": "Insert",
            "home": "Home",
            "end": "End",
            "pageup": "PageUp",
            "page_up": "PageUp",
            "pagedown": "PageDown",
            "page_down": "PageDown",
            "up": "Up",
            "down": "Down",
            "left": "Left",
            "right": "Right",
        }
        raw = key.strip()
        lowered = raw.lower()
        if lowered in normalized_map:
            return normalized_map[lowered]
        if len(raw) == 1:
            return raw.upper()
        if re.fullmatch(r"f\d{1,2}", lowered):
            return lowered.upper()
        return raw[0].upper() + raw[1:]

    @staticmethod
    def _to_pynput_combo(hotkey_text: str) -> str:
        token_map = {
            "ctrl": "<ctrl>",
            "control": "<ctrl>",
            "shift": "<shift>",
            "alt": "<alt>",
            "option": "<alt>",
            "cmd": "<cmd>",
            "command": "<cmd>",
            "meta": "<cmd>",
            "super": "<cmd>",
            "win": "<cmd>",
            "windows": "<cmd>",
        }
        special_key_map = {
            "space": "<space>",
            "tab": "<tab>",
            "enter": "<enter>",
            "esc": "<esc>",
            "delete": "<delete>",
            "backspace": "<backspace>",
            "insert": "<insert>",
            "home": "<home>",
            "end": "<end>",
            "pageup": "<page_up>",
            "page_up": "<page_up>",
            "pagedown": "<page_down>",
            "page_down": "<page_down>",
            "up": "<up>",
            "down": "<down>",
            "left": "<left>",
            "right": "<right>",
        }
        tokens = [part.strip().lower() for part in hotkey_text.split("+") if part.strip()]
        if not tokens:
            return "<ctrl>+<shift>+v"
        converted: list[str] = []
        for token in tokens:
            if token in token_map:
                converted.append(token_map[token])
            elif token in special_key_map:
                converted.append(special_key_map[token])
            elif re.fullmatch(r"f\d{1,2}", token):
                converted.append(f"<{token}>")
            else:
                converted.append(token)
        return "+".join(converted)
