from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from typing import Optional


@dataclass(slots=True)
class FocusTarget:
    window_handle: Optional[int] = None
    app_name: Optional[str] = None


class FocusService:
    def __init__(self) -> None:
        self.platform = sys.platform

    def capture_current_target(self) -> FocusTarget:
        if self.platform == "win32":
            return FocusTarget(window_handle=self._capture_windows_handle())
        if self.platform == "darwin":
            return FocusTarget(app_name=self._capture_macos_app_name())
        return FocusTarget()

    def restore_target(self, target: FocusTarget) -> bool:
        if self.platform == "win32" and target.window_handle:
            return self._restore_windows_handle(target.window_handle)
        if self.platform == "darwin" and target.app_name:
            return self._restore_macos_app(target.app_name)
        return False

    def _capture_windows_handle(self) -> Optional[int]:
        try:
            import ctypes

            user32 = ctypes.windll.user32
            hwnd = int(user32.GetForegroundWindow())
            return hwnd if hwnd else None
        except Exception:
            return None

    def _restore_windows_handle(self, hwnd: int) -> bool:
        try:
            import ctypes

            user32 = ctypes.windll.user32
            return bool(user32.SetForegroundWindow(hwnd))
        except Exception:
            return False

    @staticmethod
    def _escape_applescript(text: str) -> str:
        return text.replace("\\", "\\\\").replace('"', '\\"')

    def _capture_macos_app_name(self) -> Optional[str]:
        script = (
            'tell application "System Events" to '
            'get name of first application process whose frontmost is true'
        )
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                return None
            name = result.stdout.strip()
            return name or None
        except Exception:
            return None

    def _restore_macos_app(self, app_name: str) -> bool:
        escaped_name = self._escape_applescript(app_name)
        script = f'tell application "{escaped_name}" to activate'
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                check=False,
            )
            return result.returncode == 0
        except Exception:
            return False

    @staticmethod
    def accessibility_hint() -> str:
        return "On macOS, grant Accessibility permission to enable global hotkey and auto paste."
