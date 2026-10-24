from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .dialog_base import ResizableDialog
from .icons import status_icon


class _MessageBase(ResizableDialog):
    _size_key = ""
    _default_size = (440, 190)
    _min_size = (360, 150)
    _frameless_resize = False
    _maximizable = False

    def __init__(self, parent: Optional[QWidget]) -> None:
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, False)
        self.setModal(True)

    def _build_body(self, kind: str, message: str) -> QVBoxLayout:
        layout = self.content_layout
        layout.setContentsMargins(22, 14, 22, 18)
        layout.setSpacing(14)

        row = QHBoxLayout()
        row.setSpacing(14)
        icon_label = QLabel(self)
        icon_label.setPixmap(status_icon(kind, 24).pixmap(24, 24))
        icon_label.setFixedSize(24, 24)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        row.addWidget(icon_label)

        body = QLabel(message, self)
        body.setObjectName("messageDialogBody")
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._body_label = body
        row.addWidget(body, 1)
        layout.addLayout(row)
        return layout

    def _finalize(self) -> None:
        self.adjustSize()
        width = max(self._min_size[0], min(self.sizeHint().width(), 560))
        self.setFixedWidth(width)
        self.adjustSize()
        self.setFixedHeight(max(self._min_size[1], self.height()))


class MessageDialog(_MessageBase):
    def __init__(
        self,
        parent: Optional[QWidget],
        title: str,
        message: str,
        kind: str = "info",
        ok_text: str = "确定",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        layout = self._build_body(kind, message)
        layout.addStretch(1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        ok_btn = QPushButton(ok_text, self)
        ok_btn.setObjectName("primaryButton")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self.accept)
        buttons.addWidget(ok_btn)
        layout.addLayout(buttons)
        self._finalize()


class ConfirmDialog(_MessageBase):
    def __init__(
        self,
        parent: Optional[QWidget],
        title: str,
        message: str,
        confirm_text: str = "确定",
        destructive: bool = False,
        kind: str = "warning",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        layout = self._build_body(kind, message)
        layout.addStretch(1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel_btn = QPushButton("取消", self)
        cancel_btn.clicked.connect(self.reject)
        confirm_btn = QPushButton(confirm_text, self)
        confirm_btn.setObjectName("dangerButton" if destructive else "primaryButton")
        confirm_btn.setDefault(True)
        confirm_btn.clicked.connect(self.accept)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(confirm_btn)
        layout.addLayout(buttons)
        self._finalize()


class ProgressDialog(_MessageBase):
    """长耗时后台操作用的不可关闭提示框。

    没有按钮、屏蔽 ESC 和关闭按钮，直到 finish() 才放行，避免用户中途打断。
    """

    _show_titlebar_close = False

    def __init__(
        self,
        parent: Optional[QWidget],
        title: str,
        message: str,
        kind: str = "info",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        layout = self._build_body(kind, message)
        layout.addStretch(1)
        self._finalize()

    def set_message(self, message: str) -> None:
        self._body_label.setText(message)
        self._finalize()

    def finish(self) -> None:
        self.done(QDialog.DialogCode.Accepted)

    def reject(self) -> None:
        # 进行中不接受 Esc / 关闭
        return

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            return
        super().keyPressEvent(event)


class TextInputDialog(ResizableDialog):
    _size_key = ""
    _default_size = (420, 180)
    _min_size = (360, 160)
    _frameless_resize = False
    _maximizable = False

    def __init__(
        self,
        parent: Optional[QWidget],
        title: str,
        label: str,
        text: str = "",
        placeholder: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, False)
        self.setWindowTitle(title)
        self.setModal(True)
        layout = self.content_layout
        layout.setContentsMargins(20, 14, 20, 16)
        layout.setSpacing(12)
        if label:
            hint = QLabel(label, self)
            hint.setObjectName("settingRowDescription")
            layout.addWidget(hint)
        self._edit = QLineEdit(self)
        self._edit.setText(text or "")
        if placeholder:
            self._edit.setPlaceholderText(placeholder)
        self._edit.selectAll()
        layout.addWidget(self._edit)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel_btn = QPushButton("取消", self)
        cancel_btn.clicked.connect(self.reject)
        ok_btn = QPushButton("确定", self)
        ok_btn.setObjectName("primaryButton")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._on_accept)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(ok_btn)
        layout.addLayout(buttons)
        self._finalize()

    def _finalize(self) -> None:
        self.setFixedWidth(max(self._min_size[0], 440))

    def _on_accept(self) -> None:
        if self._edit.text().strip() == "":
            return
        self.accept()

    def value(self) -> str:
        return self._edit.text()


class NoteEditDialog(ResizableDialog):
    _size_key = "edit_note"
    _default_size = (540, 400)
    _min_size = (420, 320)

    def __init__(self, parent: Optional[QWidget], note: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("编辑备注")
        layout = self.content_layout
        layout.setContentsMargins(20, 14, 20, 16)
        layout.setSpacing(10)
        hint = QLabel("备注仅用于展示，不会随点击粘贴输出。", self)
        hint.setObjectName("settingRowDescription")
        layout.addWidget(hint)
        self._edit = QTextEdit(self)
        self._edit.setPlainText(note or "")
        self._edit.setPlaceholderText("可选，支持多行")
        layout.addWidget(self._edit, 1)
        self._count_label = QLabel("", self)
        self._count_label.setObjectName("settingRowDescription")
        layout.addWidget(self._count_label)
        self._edit.textChanged.connect(self._update_count)
        self._update_count()

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel_btn = QPushButton("取消", self)
        cancel_btn.clicked.connect(self.reject)
        ok_btn = QPushButton("确定", self)
        ok_btn.setObjectName("primaryButton")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self.accept)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(ok_btn)
        layout.addLayout(buttons)

    def _update_count(self) -> None:
        self._count_label.setText(f"{len(self._edit.toPlainText())} 个字符")

    def value(self) -> str:
        return self._edit.toPlainText().strip()


class ExportProgressDialog(ResizableDialog):
    """Glass progress dialog used while exporting the database."""

    canceled = Signal()

    _size_key = ""
    _default_size = (460, 210)
    _min_size = (380, 180)
    _frameless_resize = False
    _maximizable = False
    _show_titlebar_close = False

    def __init__(self, parent: Optional[QWidget], title: str, message: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(False)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self._finished = False

        layout = self.content_layout
        layout.setContentsMargins(20, 14, 20, 16)
        layout.setSpacing(12)

        self._label = QLabel(message, self)
        self._label.setWordWrap(True)
        layout.addWidget(self._label)

        self._progress = QProgressBar(self)
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        layout.addWidget(self._progress)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self._cancel_btn = QPushButton("取消导出", self)
        self._cancel_btn.clicked.connect(self._cancel)
        buttons.addWidget(self._cancel_btn)
        layout.addLayout(buttons)

    def setLabelText(self, text: str) -> None:
        self._label.setText(text)

    def setMaximum(self, maximum: int) -> None:
        self._progress.setMaximum(int(maximum))

    def setValue(self, value: int) -> None:
        self._progress.setValue(int(value))

    def setMinimumDuration(self, _duration: int) -> None:
        return

    def _cancel(self) -> None:
        if self._finished:
            return
        self._finished = True
        self.canceled.emit()
        self.close()

    def reject(self) -> None:
        self._cancel()

    def finish(self) -> None:
        self._finished = True
        self.close()


class Toast(QWidget):
    """Lightweight non-blocking notification pinned to the parent's top-center."""

    def __init__(
        self,
        parent: QWidget,
        text: str,
        kind: str = "info",
        duration_ms: int = 2400,
    ) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.ToolTip
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setObjectName("toast")
        self.setProperty("toastKind", kind)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 9, 16, 9)
        layout.setSpacing(9)
        icon_label = QLabel(self)
        icon_label.setPixmap(status_icon(kind, 16).pixmap(16, 16))
        icon_label.setFixedSize(16, 16)
        layout.addWidget(icon_label)
        text_label = QLabel(text, self)
        text_label.setObjectName("toastText")
        layout.addWidget(text_label)
        self.adjustSize()

        self._dismiss = QTimer(self)
        self._dismiss.setSingleShot(True)
        self._dismiss.timeout.connect(self._dismiss_now)
        self._duration_ms = int(duration_ms)

    def popup(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            top_left = parent.mapToGlobal(QPoint(0, 0))
            x = top_left.x() + (parent.width() - self.width()) // 2
            y = top_left.y() + 24
            self.move(max(top_left.x() + 8, x), y)
        self.show()
        self.raise_()
        self._dismiss.start(self._duration_ms)

    def _dismiss_now(self) -> None:
        self.close()
        self.deleteLater()


def show_toast(parent: Optional[QWidget], text: str, kind: str = "info") -> None:
    if parent is None:
        return
    Toast(parent, text, kind).popup()


def show_message(
    parent: Optional[QWidget],
    title: str,
    message: str,
    kind: str = "info",
) -> None:
    MessageDialog(parent, title, message, kind=kind).exec()


def show_confirm(
    parent: Optional[QWidget],
    title: str,
    message: str,
    confirm_text: str = "确定",
    destructive: bool = False,
) -> bool:
    dialog = ConfirmDialog(
        parent,
        title,
        message,
        confirm_text=confirm_text,
        destructive=destructive,
    )
    return dialog.exec() == QDialog.DialogCode.Accepted
