from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

from PySide6.QtWidgets import QApplication

from .config import APP_NAME, database_path, log_file_path
from .controller import AppController
from .icon_utils import resolve_app_icon, set_windows_app_user_model_id
from .repository import ClipRepository
from .services.clipboard_service import ClipboardService
from .services.focus_service import FocusService
from .services.hotkey_service import HotkeyService
from .services.paste_service import PasteService
from .services.single_instance import SingleInstance
from .ui.feedback import MessageDialog
from .ui.main_window import MainWindow


def _attach_file_logging() -> None:
    enabled = os.environ.get("CLIPNEST_DIAGNOSTIC_LOG", "1").strip().lower()
    if enabled in {"0", "false", "off", "no"}:
        return
    try:
        handler = RotatingFileHandler(
            log_file_path(), maxBytes=1024 * 1024, backupCount=2, encoding="utf-8"
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        logging.getLogger().addHandler(handler)
    except OSError:
        logging.getLogger(__name__).debug("file logging unavailable", exc_info=True)


def _notify_already_running() -> None:
    try:
        MessageDialog(
            None,
            APP_NAME,
            f"{APP_NAME} 已在运行，请查看系统托盘中的图标。",
            kind="info",
        ).exec()
    except Exception:
        logging.getLogger(__name__).debug(
            "already-running notice failed", exc_info=True
        )


def run() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    _attach_file_logging()
    app = QApplication([])
    app.setApplicationName(APP_NAME)
    set_windows_app_user_model_id()
    app_icon = resolve_app_icon(app)
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)

    instance = SingleInstance(APP_NAME)
    if instance.already_running:
        _notify_already_running()
        instance.release()
        return 0

    clipboard = app.clipboard()

    repository = ClipRepository(database_path())
    window = MainWindow()
    focus_service = FocusService()
    clipboard_service = ClipboardService(clipboard)
    hotkey_text = repository.get_setting("hotkey") or "Ctrl+Shift+V"
    hotkey_service = HotkeyService(hotkey_text)
    paste_service = PasteService(clipboard, clipboard_service, focus_service)

    controller = AppController(
        repository=repository,
        window=window,
        clipboard_service=clipboard_service,
        focus_service=focus_service,
        hotkey_service=hotkey_service,
        paste_service=paste_service,
    )
    hotkey_service.start()
    controller.initialize()
    window.show()

    app.aboutToQuit.connect(controller.shutdown)
    return app.exec()
