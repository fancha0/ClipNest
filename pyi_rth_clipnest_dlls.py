import os
import sys

if sys.platform == "win32":
    _base = getattr(sys, "_MEIPASS", "")
    _paths = [
        _base,
        os.path.join(_base, "PySide6"),
        os.path.join(_base, "shiboken6"),
    ]
    _paths = [path for path in _paths if os.path.isdir(path)]
    if _paths:
        os.environ["PATH"] = os.pathsep.join(_paths + [os.environ.get("PATH", "")])
        for _path in _paths:
            try:
                os.add_dll_directory(_path)
            except (AttributeError, OSError):
                pass
