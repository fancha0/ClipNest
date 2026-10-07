from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler


def set_diagnostic_logging(enabled: bool) -> None:
    """Enable or mute the rotating ClipNest file handler without touching console logs."""
    level = logging.INFO if enabled else logging.CRITICAL + 1
    for handler in logging.getLogger().handlers:
        if isinstance(handler, RotatingFileHandler):
            handler.setLevel(level)
