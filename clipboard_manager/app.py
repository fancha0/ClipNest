from __future__ import annotations

import logging

from PySide6.QtWidgets import QApplication

from .config import APP_NAME, database_path
from .controller import AppController
from .icon_utils import resolve_app_icon, set_windows_app_user_model_id
from .repository import ClipRepository
from .services.clipboard_service import ClipboardService
from .services.focus_service import FocusService
from .services.hotkey_service import HotkeyService
from .services.paste_service import PasteService
from .ui.main_window import MainWindow


def run() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    app = QApplication([])
    app.setApplicationName(APP_NAME)
    set_windows_app_user_model_id()
    app_icon = resolve_app_icon(app)
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)
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
