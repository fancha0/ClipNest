from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from .dialog_base import ResizableDialog


class UpdateDialog(ResizableDialog):
    _size_key = "update"
    _default_size = (520, 420)
    _min_size = (440, 360)

    download_requested = Signal(str, str)
    install_requested = Signal(str, str)

    def __init__(self, parent, info: dict, frozen: bool) -> None:
        super().__init__(parent)
        self.setWindowTitle("软件更新")
        self._info = dict(info)
        self._zip_path: str = ""
        self._frozen = bool(frozen)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        version_label = QLabel(f"发现新版本 v{self._info.get('version', '')}", self)
        version_label.setObjectName("updateVersionLabel")
        layout.addWidget(version_label)

        body = QTextEdit(self)
        body.setReadOnly(True)
        body.setPlainText(str(self._info.get("body") or "（无更新日志）"))
        layout.addWidget(body, 1)

        size_mb = int(self._info.get("size") or 0) / (1024 * 1024)
        self._size_label = QLabel(
            f"更新包大小：约 {size_mb:.1f} MB" if size_mb > 0 else "",
            self,
        )
        layout.addWidget(self._size_label)

        self._progress = QProgressBar(self)
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self._action_btn = QPushButton("下载更新", self)
        self._action_btn.setObjectName("primaryButton")
        self._action_btn.setDefault(True)
        self._cancel_btn = QPushButton("取消", self)
        buttons.addWidget(self._action_btn)
        buttons.addWidget(self._cancel_btn)
        layout.addLayout(buttons)

        self._action_btn.clicked.connect(self._on_action_clicked)
        self._cancel_btn.clicked.connect(self.reject)

        if not self._frozen:
            self._action_btn.setEnabled(False)
            self._action_btn.setToolTip("开发模式下无法自动安装更新")

    def _on_action_clicked(self) -> None:
        if self._zip_path:
            self.install_requested.emit(self._zip_path, str(self._info.get("version", "")))
            return
        url = str(self._info.get("url") or "")
        version = str(self._info.get("version") or "")
        if not url:
            return
        self._action_btn.setEnabled(False)
        self._action_btn.setText("正在下载...")
        self._progress.setVisible(True)
        self.download_requested.emit(url, version)

    def set_progress(self, received: int, total: int) -> None:
        if total > 0:
            self._progress.setRange(0, 100)
            self._progress.setValue(min(100, int(received * 100 / total)))
        else:
            self._progress.setRange(0, 0)
        self._size_label.setText(
            f"已下载 {received / (1024 * 1024):.1f} MB"
            + (f" / {total / (1024 * 1024):.1f} MB" if total > 0 else "")
        )

    def set_ready(self, zip_path: str, _version: str) -> None:
        self._zip_path = zip_path
        self._progress.setVisible(False)
        self._action_btn.setEnabled(self._frozen)
        self._action_btn.setText("立即安装并重启")
        self._size_label.setText("下载完成")

    def set_failed(self, message: str) -> None:
        self._progress.setVisible(False)
        self._action_btn.setEnabled(True)
        self._action_btn.setText("重试下载")
        self._size_label.setText(f"下载失败：{message}")
