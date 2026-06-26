"""开机自启服务：管理 Windows 注册表 / macOS LaunchAgent。"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class AutoStartService:
    def __init__(self, app_name: str = "ClipNest") -> None:
        self._app_name = app_name

    # -- 公开接口 ---------------------------------------------------------------

    def is_enabled(self) -> bool:
        if sys.platform == "win32":
            return self._win_is_enabled()
        if sys.platform == "darwin":
            return self._mac_is_enabled()
        return False

    def set_enabled(self, enabled: bool) -> Optional[str]:
        """启用或禁用开机自启。返回错误信息，成功返回 None。"""
        if sys.platform == "win32":
            return self._win_set_enabled(enabled)
        if sys.platform == "darwin":
            return self._mac_set_enabled(enabled)
        return "当前系统暂不支持开机自启。"

    # -- Windows ---------------------------------------------------------------

    def _win_reg_path(self) -> str:
        return r"Software\Microsoft\Windows\CurrentVersion\Run"

    def _win_is_enabled(self) -> bool:
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                self._win_reg_path(),
                0,
                winreg.KEY_READ,
            ) as key:
                value, _ = winreg.QueryValueEx(key, self._app_name)
                return bool(value)
        except OSError:
            return False
        except Exception as exc:
            logger.debug("[AutoStart] 读取注册表失败: %s", exc)
            return False

    def _win_set_enabled(self, enabled: bool) -> Optional[str]:
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                self._win_reg_path(),
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                if enabled:
                    exe_path = self._resolve_exe_path()
                    winreg.SetValueEx(
                        key, self._app_name, 0, winreg.REG_SZ, exe_path
                    )
                    logger.info("[AutoStart] 注册表已写入: %s", exe_path)
                else:
                    try:
                        winreg.DeleteValue(key, self._app_name)
                    except FileNotFoundError:
                        pass
                    logger.info("[AutoStart] 注册表已移除")
            return None
        except Exception as exc:
            logger.warning("[AutoStart] 写入注册表失败: %s", exc)
            return str(exc)

    # -- macOS -----------------------------------------------------------------

    def _mac_plist_path(self) -> Path:
        return (
            Path.home()
            / "Library"
            / "LaunchAgents"
            / f"com.{self._app_name.lower()}.plist"
        )

    def _mac_is_enabled(self) -> bool:
        return self._mac_plist_path().exists()

    def _mac_set_enabled(self, enabled: bool) -> Optional[str]:
        plist_path = self._mac_plist_path()
        try:
            if enabled:
                exe_path = self._resolve_exe_path()
                label = f"com.{self._app_name.lower()}"
                plist_content = (
                    '<?xml version="1.0" encoding="UTF-8"?>\n'
                    '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
                    '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
                    '<plist version="1.0">\n'
                    "<dict>\n"
                    f"  <key>Label</key>\n  <string>{label}</string>\n"
                    "  <key>ProgramArguments</key>\n"
                    "  <array>\n"
                    f"    <string>{exe_path}</string>\n"
                    "  </array>\n"
                    "  <key>RunAtLoad</key>\n  <true/>\n"
                    "  <key>KeepAlive</key>\n  <false/>\n"
                    "</dict>\n"
                    "</plist>\n"
                )
                plist_path.parent.mkdir(parents=True, exist_ok=True)
                plist_path.write_text(plist_content, encoding="utf-8")
                logger.info("[AutoStart] plist 已创建: %s", plist_path)
            else:
                if plist_path.exists():
                    plist_path.unlink()
                logger.info("[AutoStart] plist 已移除")
            return None
        except Exception as exc:
            logger.warning("[AutoStart] macOS 设置失败: %s", exc)
            return str(exc)

    # -- 公共辅助 ---------------------------------------------------------------

    def _resolve_exe_path(self) -> str:
        """获取最佳的可执行路径用于自启动。"""
        if getattr(sys, "frozen", False):
            return str(Path(sys.executable).resolve())
        project_root = Path(__file__).resolve().parent.parent.parent
        main_py = project_root / "main.py"
        if main_py.exists():
            return f'"{sys.executable}" "{main_py}"'
        return str(Path(sys.executable).resolve())
