from __future__ import annotations

import logging
import os
import sys
import tempfile

logger = logging.getLogger(__name__)


class SingleInstance:
    """Best-effort single-instance guard.

    On Windows a named mutex is used: the kernel releases it automatically when
    the owning process exits (even on crash), so there is no stale state to
    clean up. On other platforms falls back to an exclusive lock file.
    """

    def __init__(self, name: str) -> None:
        self._name = str(name)
        self._handle = None
        self._lock_path: str | None = None
        self._already_running = False
        if sys.platform == "win32":
            self._acquire_windows()
        else:
            self._acquire_lockfile()

    def _acquire_windows(self) -> None:
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.windll.kernel32
            kernel32.CreateMutexW.argtypes = [
                ctypes.c_void_p,
                wintypes.BOOL,
                wintypes.LPCWSTR,
            ]
            kernel32.CreateMutexW.restype = wintypes.HANDLE
            mutex_name = f"Local\\{self._name}.SingleInstance"
            handle = kernel32.CreateMutexW(None, False, mutex_name)
            if not handle:
                logger.warning("CreateMutexW failed; single-instance check skipped")
                return
            self._handle = handle
            self._already_running = kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS
        except Exception:
            logger.exception("single-instance Windows guard failed")

    def _acquire_lockfile(self) -> None:
        path = os.path.join(tempfile.gettempdir(), f"{self._name}.lock")
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
        except FileExistsError:
            self._already_running = True
            return
        except OSError:
            logger.exception("single-instance lock file failed")
            return
        os.write(fd, str(os.getpid()).encode("ascii"))
        os.close(fd)
        self._lock_path = path

    @property
    def already_running(self) -> bool:
        return self._already_running

    def release(self) -> None:
        if self._handle is not None:
            try:
                import ctypes

                ctypes.windll.kernel32.CloseHandle(self._handle)
            except Exception:
                logger.debug("CloseHandle failed", exc_info=True)
            finally:
                self._handle = None
        if self._lock_path is not None:
            try:
                os.remove(self._lock_path)
            except OSError:
                logger.debug("lock file remove failed", exc_info=True)
            finally:
                self._lock_path = None
