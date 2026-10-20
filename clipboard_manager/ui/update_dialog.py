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

    download_requested = Signal(str, str, int, str)
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

        self._version_label = QLabel(self)
        self._version_label.setObjectName("updateVersionLabel")
        layout.addWidget(self._version_label)

        self._body = QTextEdit(self)
        self._body.setReadOnly(True)
        layout.addWidget(self._body, 1)

        self._size_label = QLabel(self)
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
        self.set_info(info)

    def set_info(self, info: dict) -> None:
        self._info = dict(info)
        self._version_label.setText(
            f"发现新版本 v{self._info.get('version', '')}"
        )
        self._body.setPlainText(
            str(self._info.get("body") or "（无更新日志）")
        )
        self.set_available()

    def set_available(self) -> None:
        self._zip_path = ""
        self._progress.setVisible(False)
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._action_btn.setEnabled(self._frozen)
        self._action_btn.setText("下载更新")
        self._action_btn.setToolTip(
            "" if self._frozen else "开发模式下无法自动安装更新"
        )
        self._cancel_btn.setText("取消")
        size_mb = int(self._info.get("size") or 0) / (1024 * 1024)
        self._size_label.setText(
            f"更新包大小：约 {size_mb:.1f} MB" if size_mb > 0 else ""
        )

    def set_downloading(self) -> None:
        self._progress.setVisible(True)
        self._action_btn.setEnabled(False)
        self._action_btn.setText("正在下载...")
        self._cancel_btn.setText("稍后")

    def set_progress(self, received: int, total: int) -> None:
        self.set_downloading()
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
        self._action_btn.setToolTip(
            "" if self._frozen else "开发模式下无法自动安装更新"
        )
        self._cancel_btn.setText("稍后")
        self._size_label.setText("下载完成")

    def set_failed(self, message: str) -> None:
        self._progress.setVisible(False)
        self._action_btn.setEnabled(self._frozen)
        self._action_btn.setText("重试下载")
        self._cancel_btn.setText("关闭")
        self._size_label.setText(f"下载失败：{message}")

    def _on_action_clicked(self) -> None:
        if self._zip_path:
            self.install_requested.emit(
                self._zip_path, str(self._info.get("version", ""))
            )
            return
        url = str(self._info.get("url") or "")
        version = str(self._info.get("version") or "")
        if not url:
            return
        self.set_downloading()
        self.download_requested.emit(
            url,
            version,
            int(self._info.get("size") or 0),
            str(self._info.get("sha256") or ""),
        )
