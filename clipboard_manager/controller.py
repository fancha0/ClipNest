from __future__ import annotations

import logging
import re
import sys
import time
from typing import Optional

from PySide6.QtCore import QTimer, Qt

from .config import AUTO_HIDE_ON_PASTE, default_hotkey
from .models import ParsedClipboardItem
from .repository import ClipRepository
from .services.clipboard_service import ClipboardService
from .services.focus_service import FocusService, FocusTarget
from .services.hotkey_service import HotkeyService
from .services.paste_service import PasteService
from .services.autostart_service import AutoStartService
from .ui.main_window import MainWindow
from .ui.theme import AppearanceSettings, default_appearance_settings, normalize_hex_color

logger = logging.getLogger(__name__)


class AppController:
    def __init__(
        self,
        repository: ClipRepository,
        window: MainWindow,
        clipboard_service: ClipboardService,
        focus_service: FocusService,
        hotkey_service: HotkeyService,
        paste_service: PasteService,
    ) -> None:
        self._repository = repository
        self._window = window
        self._clipboard_service = clipboard_service
        self._focus_service = focus_service
        self._hotkey_service = hotkey_service
        self._paste_service = paste_service
        self._autostart_service = AutoStartService()
        self._pending_focus_target: Optional[FocusTarget] = None
        self._auto_hide_on_paste = AUTO_HIDE_ON_PASTE
        self._capture_tab_id: Optional[int] = None
        self._search_query: str = ""
        self._items_cache: dict[int, list] = {}
        self._rich_segments_cache: dict[int, list[dict]] = {}
        self._rich_prewarm_queue: list[int] = []
        self._rich_prewarm_ids: set[int] = set()
        self._rich_prewarm_timer = QTimer()
        self._rich_prewarm_timer.setSingleShot(True)
        self._rich_prewarm_timer.setInterval(80)
        self._rich_prewarm_timer.timeout.connect(self._prewarm_next_rich_batch)
        self._connect_signals()

    def initialize(self) -> None:
        tabs = self._repository.list_tabs()
        active_tab_id = self._parse_int_setting("active_tab_id")
        if not tabs:
            return
        if active_tab_id not in {tab.id for tab in tabs}:
            active_tab_id = tabs[0].id
            self._repository.set_setting("active_tab_id", str(active_tab_id))
        capture_tab_id = self._parse_int_setting("capture_tab_id")
        if capture_tab_id not in {tab.id for tab in tabs}:
            capture_tab_id = tabs[0].id
            self._repository.set_setting("capture_tab_id", str(capture_tab_id))
        self._capture_tab_id = capture_tab_id

        note_color = self._repository.get_setting("note_text_color") or "#1f2937"
        note_font_size = self._parse_int_setting("note_font_size")
        if note_font_size is None:
            note_font_size = 13
            self._repository.set_setting("note_font_size", str(note_font_size))
        note_font_size = max(10, min(28, note_font_size))
        self._repository.set_setting("note_text_color", note_color)

        self._window.set_tabs(tabs, active_tab_id)
        self._window.set_capture_tab(capture_tab_id, self._tab_name(tabs, capture_tab_id))
        self._window.set_note_style(note_color, note_font_size)
        self._window.set_hotkey_text(self._hotkey_service.hotkey_text)
        autostart_enabled = self._autostart_service.is_enabled()
        self._window.set_autostart_state(autostart_enabled)

        appearance = self._load_appearance_settings()
        self._save_appearance_settings(appearance)
        self._window.set_appearance(appearance)
        splitter_sizes = self._parse_splitter_sizes_setting()
        if splitter_sizes is not None:
            self._window.set_main_splitter_sizes(splitter_sizes[0], splitter_sizes[1])

        if self._hotkey_service.last_error:
            fallback = default_hotkey()
            ok, error = self._hotkey_service.update_hotkey(fallback)
            if ok:
                self._repository.set_setting("hotkey", fallback)
                self._window.set_hotkey_text(fallback)
                self._window.show_info(
                    "已自动恢复默认快捷键。你可以在右上角设置菜单中重新配置。"
                )
            else:
                self._window.show_error(
                    "全局快捷键监听失败："
                    f"{self._hotkey_service.last_error or error or '未知错误'}"
                )
                if sys.platform == "darwin":
                    self._window.show_info(FocusService.accessibility_hint())

    def shutdown(self) -> None:
        self._hotkey_service.stop()
        self._repository.close()

    def _connect_signals(self) -> None:
        self._clipboard_service.parsed_captured.connect(self._on_clipboard_parsed_captured)
        self._hotkey_service.hotkey_pressed.connect(self._on_hotkey_pressed)

        self._window.tab_selected.connect(self._on_tab_selected)
        self._window.tab_order_changed.connect(self._on_tab_order_changed)
        self._window.item_order_changed.connect(self._on_item_order_changed)
        self._window.create_tab_requested.connect(self._on_create_tab)
        self._window.rename_tab_requested.connect(self._on_rename_tab)
        self._window.delete_tab_requested.connect(self._on_delete_tab)
        self._window.add_item_requested.connect(self._on_add_item)
        self._window.add_bundle_item_requested.connect(self._on_add_bundle_item)
        self._window.add_mixed_item_requested.connect(self._on_add_mixed_item)
        self._window.edit_item_requested.connect(self._on_edit_item)
        self._window.edit_item_image_requested.connect(self._on_edit_item_image)
        self._window.edit_bundle_requested.connect(self._on_edit_bundle)
        self._window.edit_note_requested.connect(self._on_edit_note)
        self._window.item_pin_change_requested.connect(self._on_item_pin_change_requested)
        self._window.delete_item_requested.connect(self._on_delete_item)
        self._window.clear_items_requested.connect(self._on_clear_items)
        self._window.move_items_requested.connect(self._on_move_items_to_tab)
        self._window.item_activated.connect(self._on_item_activated)
        self._window.hotkey_change_requested.connect(self._on_hotkey_change_requested)
        self._window.hotkey_reset_requested.connect(self._on_hotkey_reset_requested)
        self._window.capture_tab_change_requested.connect(self._on_capture_tab_change_requested)
        self._window.note_color_change_requested.connect(self._on_note_color_change_requested)
        self._window.note_font_size_change_requested.connect(self._on_note_font_size_change_requested)
        self._window.export_requested.connect(self._on_export_requested)
        self._window.import_requested.connect(self._on_import_requested)
        self._window.search_text_changed.connect(self._on_search_text_changed)
        self._window.splitter_sizes_changed.connect(self._on_splitter_sizes_changed)
        self._window.appearance_change_requested.connect(self._on_appearance_change_requested)
        self._window.start_inline_edit_requested.connect(self._on_start_inline_edit)
        self._window.save_inline_edit_requested.connect(self._on_save_inline_edit)
        self._window.autostart_change_requested.connect(self._on_autostart_change_requested)

    def _parse_int_setting(self, key: str) -> Optional[int]:
        value = self._repository.get_setting(key)
        if value is None:
            return None
        try:
            return int(value)
        except ValueError:
            return None

    def _parse_splitter_sizes_setting(self) -> Optional[tuple[int, int]]:
        value = (self._repository.get_setting("main_splitter_sizes") or "").strip()
        if value == "":
            return None
        parts = value.split(",")
        if len(parts) != 2:
            return None
        try:
            left = max(0, int(parts[0].strip()))
            right = max(0, int(parts[1].strip()))
        except ValueError:
            return None
        if left == 0 and right == 0:
            return None
        return left, right

    def _parse_bool_setting(self, key: str, default: bool) -> bool:
        raw = self._repository.get_setting(key)
        if raw is None:
            return bool(default)
        value = raw.strip().lower()
        if value in {"1", "true", "yes", "on"}:
            return True
        if value in {"0", "false", "no", "off"}:
            return False
        return bool(default)

    @staticmethod
    def _normalize_hex(value: Optional[str], fallback: str) -> str:
        text = (value or "").strip()
        if re.fullmatch(r"#[0-9a-fA-F]{6}", text):
            return text.lower()
        return normalize_hex_color("", fallback)

    def _load_appearance_settings(self) -> AppearanceSettings:
        defaults = default_appearance_settings()
        font_size = self._parse_int_setting("appearance_font_size")
        if font_size is None:
            font_size = defaults.font_size
        return AppearanceSettings(
            window_bg=self._normalize_hex(
                self._repository.get_setting("appearance_window_bg"),
                defaults.window_bg,
            ),
            font_size=max(10, min(28, int(font_size))),
            item_bg=self._normalize_hex(
                self._repository.get_setting("appearance_item_bg"),
                defaults.item_bg,
            ),
            item_selected_bg=self._normalize_hex(
                self._repository.get_setting("appearance_item_selected_bg"),
                defaults.item_selected_bg,
            ),
            show_scrollbar=self._parse_bool_setting(
                "appearance_show_scrollbar",
                defaults.show_scrollbar,
            ),
            item_antialias=self._parse_bool_setting(
                "appearance_item_antialias",
                defaults.item_antialias,
            ),
        )

    def _save_appearance_settings(self, appearance: AppearanceSettings) -> None:
        self._repository.set_setting("appearance_window_bg", appearance.window_bg)
        self._repository.set_setting("appearance_font_size", str(int(appearance.font_size)))
        self._repository.set_setting("appearance_item_bg", appearance.item_bg)
        self._repository.set_setting("appearance_item_selected_bg", appearance.item_selected_bg)
        self._repository.set_setting("appearance_show_scrollbar", "1" if appearance.show_scrollbar else "0")
        self._repository.set_setting("appearance_item_antialias", "1" if appearance.item_antialias else "0")

    def _on_hotkey_pressed(self) -> None:
        logger.info("[Hotkey] showClipboardPanel from globalShortcut")
        logger.info(
            "[Hotkey] showClipboardPanel enter window_exists=%s visible_before=%s active_before=%s minimized_before=%s",
            self._window is not None,
            self._window.isVisible(),
            self._window.isActiveWindow(),
            bool(self._window.windowState() & Qt.WindowState.WindowMinimized),
        )
        if self._window.should_hide_on_hotkey():
            self._window.hide()
            self._pending_focus_target = None
            logger.info("[Hotkey] panel hidden by toggle logic")
            return
        self._pending_focus_target = self._focus_service.capture_current_target()
        try:
            self._window.show_for_quick_paste()
        except Exception:
            logger.exception("[Hotkey] showClipboardPanel failed during show_for_quick_paste")
            return
        logger.info(
            "[Hotkey] showClipboardPanel exit visible_after=%s active_after=%s minimized_after=%s",
            self._window.isVisible(),
            self._window.isActiveWindow(),
            bool(self._window.windowState() & Qt.WindowState.WindowMinimized),
        )

    def _on_tab_selected(self, tab_id: int) -> None:
        self._repository.set_setting("active_tab_id", str(tab_id))
        self._window.hide_inline_editor()
        self._clear_rich_prewarm()
        self._refresh_items(tab_id)

    def _on_search_text_changed(self, query: str) -> None:
        self._search_query = (query or "").strip()
        self._refresh_items(self._window.current_tab_id())

    def _on_splitter_sizes_changed(self, value: str) -> None:
        clean_value = (value or "").strip()
        if clean_value == "":
            return
        self._repository.set_setting("main_splitter_sizes", clean_value)

    def _on_autostart_change_requested(self, enabled: bool) -> None:
        error = self._autostart_service.set_enabled(enabled)
        if error:
            self._window.show_error(f"设置开机自启失败：{error}")
            self._window.set_autostart_state(not enabled)
            return
        actual = self._autostart_service.is_enabled()
        self._window.set_autostart_state(actual)
        if actual:
            self._window.show_info("已开启开机自启动。")
        else:
            self._window.show_info("已关闭开机自启动。")

    def _on_appearance_change_requested(self, appearance: AppearanceSettings) -> None:
        defaults = default_appearance_settings()
        normalized = AppearanceSettings(
            window_bg=self._normalize_hex(appearance.window_bg, defaults.window_bg),
            font_size=max(10, min(28, int(appearance.font_size))),
            item_bg=self._normalize_hex(appearance.item_bg, defaults.item_bg),
            item_selected_bg=self._normalize_hex(
                appearance.item_selected_bg,
                defaults.item_selected_bg,
            ),
            show_scrollbar=bool(appearance.show_scrollbar),
            item_antialias=bool(appearance.item_antialias),
        )
        try:
            self._window.set_appearance(normalized)
            self._save_appearance_settings(normalized)
        except Exception as exc:
            self._window.show_error(f"应用外观设置失败：{exc}")

    def _on_tab_order_changed(self, tab_ids: list[int]) -> None:
        if not tab_ids:
            return
        active_tab_id = self._window.current_tab_id()
        try:
            self._repository.reorder_tabs(tab_ids)
        except Exception as exc:
            self._window.show_error(f"保存标签顺序失败：{exc}")
            self._refresh_tabs(active_tab_id=active_tab_id)
            return
        self._refresh_tabs(active_tab_id=active_tab_id)

    def _on_item_order_changed(self, item_ids: list[int], tab_id: int) -> None:
        if not item_ids:
            return
        current_tab_id = self._window.current_tab_id()
        if self._search_query:
            return
        try:
            self._repository.reorder_items(tab_id, item_ids)
        except ValueError:
            self._invalidate_items_cache(current_tab_id)
            self._refresh_items(current_tab_id)
            return
        except Exception as exc:
            self._window.show_error(f"保存条目顺序失败：{exc}")
            self._invalidate_items_cache(current_tab_id)
            self._refresh_items(current_tab_id)
            return
        self._invalidate_items_cache(current_tab_id)
        self._refresh_items(current_tab_id)

    def _on_create_tab(self, name: str) -> None:
        try:
            tab = self._repository.create_tab(name)
        except Exception as exc:
            self._window.show_error(f"创建标签页失败：{exc}")
            return
        self._invalidate_items_cache()
        self._refresh_tabs(active_tab_id=tab.id)

    def _on_rename_tab(self, tab_id: int, name: str) -> None:
        try:
            self._repository.rename_tab(tab_id, name)
        except Exception as exc:
            self._window.show_error(f"重命名失败：{exc}")
            return
        self._refresh_tabs(active_tab_id=tab_id)

    def _on_delete_tab(self, tab_id: int) -> None:
        tabs = self._repository.list_tabs()
        if len(tabs) <= 1:
            self._window.show_error("至少保留一个标签页。")
            return

        item_count = self._repository.tab_item_count(tab_id)
        if item_count > 0:
            ok = self._window.confirm(
                "删除标签页",
                f"该标签页包含 {item_count} 条记录，确认删除吗？",
            )
            if not ok:
                return
        try:
            self._repository.delete_tab(tab_id)
        except Exception as exc:
            self._window.show_error(f"删除标签页失败：{exc}")
            return
        self._invalidate_items_cache(tab_id)

        remaining_tabs = self._repository.list_tabs()
        next_tab_id = remaining_tabs[0].id if remaining_tabs else None
        if self._capture_tab_id == tab_id and next_tab_id is not None:
            self._capture_tab_id = next_tab_id
            self._repository.set_setting("capture_tab_id", str(next_tab_id))
            self._window.show_info(
                f"监听存储标签已自动切换为：{self._tab_name(remaining_tabs, next_tab_id)}"
            )
        self._refresh_tabs(active_tab_id=next_tab_id)

    def _on_add_item(self, text: str) -> None:
        tab_id = self._window.current_tab_id()
        if tab_id is None:
            return
        self._repository.upsert_text_item(tab_id, text)
        self._invalidate_items_cache(tab_id)
        self._refresh_items(tab_id)

    def _on_add_bundle_item(self, text: str, images: list[dict], note: str) -> None:
        tab_id = self._window.current_tab_id()
        if tab_id is None:
            return
        try:
            item = self._repository.create_bundle_item(tab_id, text, images, note=note)
        except Exception as exc:
            self._window.show_error(f"创建复合条目失败：{exc}")
            return
        if item is None:
            self._window.show_error("创建失败：请至少添加一张图片。")
            return
        self._invalidate_rich_cache(item.id)
        self._invalidate_items_cache(tab_id)
        self._refresh_items(tab_id)

    def _on_add_mixed_item(self, segments: object, note: str) -> None:
        tab_id = self._window.current_tab_id()
        if tab_id is None:
            return
        if not isinstance(segments, list):
            self._window.show_error("创建失败：图文内容格式错误。")
            return
        try:
            item = self._repository.create_mixed_item(tab_id, segments, note=note)
        except Exception as exc:
            self._window.show_error(f"创建图文条目失败：{exc}")
            return
        if any(isinstance(seg, dict) and str(seg.get("type") or "").lower() == "image" for seg in segments):
            self._rich_segments_cache[int(item.id)] = list(segments)
            self._paste_service.prepare_mixed_segments(list(segments))
        self._invalidate_items_cache(tab_id)
        self._refresh_items(tab_id)

    def _on_edit_item(self, item_id: int, text: str, note: str) -> None:
        try:
            self._repository.update_item_text(item_id, text, note=note)
        except Exception as exc:
            self._window.show_error(f"编辑失败：{exc}")
            return
        self._invalidate_rich_cache(item_id)
        tab_id = self._window.current_tab_id()
        if tab_id is not None:
            self._invalidate_items_cache(tab_id)
            self._refresh_items(tab_id)

    def _on_edit_item_image(
        self,
        item_id: int,
        image_bytes: bytes,
        mime_type: str,
        width: int,
        height: int,
        note: str,
    ) -> None:
        try:
            self._repository.update_item_image(
                item_id=item_id,
                image_bytes=image_bytes,
                mime_type=mime_type,
                width=width,
                height=height,
                note=note,
            )
        except Exception as exc:
            self._window.show_error(f"编辑失败：{exc}")
            return
        self._invalidate_rich_cache(item_id)
        tab_id = self._window.current_tab_id()
        if tab_id is not None:
            self._invalidate_items_cache(tab_id)
            self._refresh_items(tab_id)

    def _on_edit_bundle(self, item_id: int) -> None:
        result = self._repository.get_bundle_item(item_id)
        if result is None:
            self._window.show_error("未找到复合条目。")
            return
        item, bundle_images = result
        initial_images = [
            {
                "image_blob": img.image_blob,
                "mime_type": img.mime_type or "image/png",
                "width": img.width or 0,
                "height": img.height or 0,
            }
            for img in bundle_images
        ]
        accepted, new_text, new_images, new_note = self._window.prompt_bundle_edit(
            item.text,
            initial_images,
            item.note,
        )
        if not accepted:
            return
        try:
            self._repository.update_bundle_item(item_id, new_text, new_images, note=new_note)
        except Exception as exc:
            self._window.show_error(f"编辑失败：{exc}")
            return
        self._invalidate_rich_cache(item_id)
        current_tab_id = self._window.current_tab_id()
        if current_tab_id is not None:
            self._invalidate_items_cache(current_tab_id)
            self._refresh_items(current_tab_id)

    def _on_start_inline_edit(self, item_id: int) -> None:
        item = self._repository.get_item(item_id)
        if item is None:
            self._window.show_error("未找到条目。")
            return
        segments = self._build_inline_segments(item)
        self._window.show_inline_editor(item_id, segments)

    def _on_save_inline_edit(self, item_id: int, segments: object) -> None:
        if not isinstance(segments, list):
            self._window.show_error("编辑内容格式错误。")
            return
        try:
            self._repository.update_item_mixed(item_id, segments)
        except Exception as exc:
            self._window.show_error(f"保存失败：{exc}")
            return
        if any(isinstance(seg, dict) and str(seg.get("type") or "").lower() == "image" for seg in segments):
            self._rich_segments_cache[int(item_id)] = list(segments)
            self._paste_service.prepare_mixed_segments(list(segments))
        else:
            self._invalidate_rich_cache(item_id)
        tab_id = self._window.current_tab_id()
        if tab_id is not None:
            self._invalidate_items_cache(tab_id)
            self._refresh_items(tab_id)
        self._window.hide_inline_editor()

    def _build_inline_segments(self, item) -> list[dict]:
        if item.content_type == "rich":
            segments = self._repository.get_item_rich_segments(item.id)
            if segments:
                return segments
            payload = self._repository.get_item_payload_typed(item.id) or {}
            text_value = str(payload.get("plain_text") or payload.get("text") or "")
            return [{"type": "text", "content": text_value}] if text_value else []

        if item.content_type == "bundle":
            result = self._repository.get_bundle_item(item.id)
            if result is None:
                return [{"type": "text", "content": item.text}] if item.text else []
            _, bundle_images = result
            segments: list[dict] = []
            if item.text.strip():
                segments.append({"type": "text", "content": item.text.strip()})
            for idx, img in enumerate(bundle_images):
                if segments:
                    tail = segments[-1]
                    if tail.get("type") != "text" or not str(tail.get("content") or "").endswith("\n"):
                        segments.append({"type": "text", "content": "\n"})
                segments.append(
                    {
                        "type": "image",
                        "image_blob": img.image_blob,
                        "mime_type": img.mime_type or "image/png",
                        "width": int(img.width or 0),
                        "height": int(img.height or 0),
                    }
                )
                if idx < len(bundle_images) - 1:
                    segments.append({"type": "text", "content": "\n"})
            return segments

        if item.content_type == "image":
            payload = self._repository.get_item_payload(item.id)
            if payload:
                return [
                    {
                        "type": "image",
                        "image_blob": payload,
                        "mime_type": item.mime_type or "image/png",
                        "width": int(item.width or 0),
                        "height": int(item.height or 0),
                    }
                ]
            return []

        payload = self._repository.get_item_payload_typed(item.id) or {}
        text_value = str(payload.get("plain_text") or payload.get("text") or item.text or "")
        if text_value.strip() == "":
            return []
        return [{"type": "text", "content": text_value}]

    def _on_delete_item(self, item_id: int) -> None:
        self._repository.delete_item(item_id)
        self._invalidate_rich_cache(item_id)
        tab_id = self._window.current_tab_id()
        if tab_id is not None:
            self._invalidate_items_cache(tab_id)
            self._refresh_items(tab_id)

    def _on_edit_note(self, item_id: int, note: str) -> None:
        try:
            self._repository.update_item_note(item_id, note)
        except Exception as exc:
            self._window.show_error(f"备注保存失败：{exc}")
            return
        tab_id = self._window.current_tab_id()
        if tab_id is not None:
            self._invalidate_items_cache(tab_id)
            self._refresh_items(tab_id)

    def _on_item_pin_change_requested(self, item_id: int, pinned: bool) -> None:
        try:
            item = self._repository.set_item_pinned(item_id, pinned)
        except Exception as exc:
            self._window.show_error(f"置顶失败：{exc}")
            return
        self._invalidate_items_cache(item.tab_id)
        current_tab_id = self._window.current_tab_id()
        if current_tab_id is not None:
            self._refresh_items(current_tab_id)

    def _on_clear_items(self, tab_id: int) -> None:
        ok = self._window.confirm("清空列表", "确认清空当前标签页所有条目吗？")
        if not ok:
            return
        self._repository.clear_items(tab_id)
        self._clear_rich_prewarm()
        self._invalidate_items_cache(tab_id)
        self._refresh_items(tab_id)

    def _on_move_items_to_tab(self, item_ids: list[int], target_tab_id: int) -> None:
        if not item_ids:
            self._window.show_error("未选择可移动的条目。")
            return
        tabs = self._repository.list_tabs()
        tab_map = {int(tab.id): tab for tab in tabs}
        target_tab = tab_map.get(int(target_tab_id))
        if target_tab is None:
            self._window.show_error("目标标签不存在。")
            return

        try:
            result = self._repository.move_items_to_tab(item_ids, int(target_tab_id))
        except Exception as exc:
            self._window.show_error(f"移动条目失败：{exc}")
            return
        for item_id in item_ids:
            self._invalidate_rich_cache(int(item_id))
        self._invalidate_items_cache()

        if result.moved_count == 0 and result.already_in_target_count > 0:
            self._window.show_info("已在当前标签页")
        elif result.moved_count == 1:
            self._window.show_info(f"已移动到 {target_tab.name}")
        elif result.moved_count > 1:
            self._window.show_info(f"已移动 {result.moved_count} 条到 {target_tab.name}")

        current_tab_id = self._window.current_tab_id()
        self._refresh_tabs(active_tab_id=current_tab_id)

    def _on_item_activated(self, item_id: int) -> None:
        item = self._repository.get_item(item_id)
        if item is None:
            return
        hide_window_cb = self._window.hide if self._auto_hide_on_paste else None
        if item.content_type == "image":
            payload = self._repository.get_item_payload(item_id)
            if not payload:
                self._window.show_error("图片数据不存在或已损坏。")
                return
            pasted = self._paste_service.paste_image(
                payload,
                self._pending_focus_target,
                hide_window=hide_window_cb,
            )
        elif item.content_type == "bundle":
            bundle = self._repository.get_bundle_item(item_id)
            if bundle is None:
                self._window.show_error("复合条目数据不存在或已损坏。")
                return
            _, bundle_images = bundle
            pasted = self._paste_service.paste_bundle(
                item.text,
                [img.image_blob for img in bundle_images],
                self._pending_focus_target,
                hide_window=hide_window_cb,
            )
        elif item.content_type in {"raw_snapshot", "special", "files", "html", "url", "text", "rich"}:
            payload = self._repository.get_item_payload_typed(item_id)
            if payload is None:
                self._window.show_error("条目数据不存在或已损坏。")
                return
            item_type = str(payload["content_type"])
            if item_type == "files":
                pasted = self._paste_service.paste_files(
                    list(payload.get("file_paths") or []),
                    self._pending_focus_target,
                    hide_window=hide_window_cb,
                )
            elif item_type == "html":
                pasted = self._paste_service.paste_html(
                    str(payload.get("html_text") or ""),
                    str(payload.get("plain_text") or ""),
                    self._pending_focus_target,
                    hide_window=hide_window_cb,
                )
            elif item_type == "rich":
                segments = self._rich_segments_cache.get(int(item_id))
                if segments is None:
                    segments = self._repository.get_item_rich_segments(item_id)
                    if segments:
                        self._rich_segments_cache[int(item_id)] = segments
                        self._paste_service.prepare_mixed_segments(segments)
                if segments:
                    pasted = self._paste_service.paste_mixed_segments(
                        segments,
                        self._pending_focus_target,
                        hide_window=hide_window_cb,
                    )
                else:
                    pasted = self._paste_service.paste_html(
                        str(payload.get("html_text") or ""),
                        str(payload.get("plain_text") or ""),
                        self._pending_focus_target,
                        hide_window=hide_window_cb,
                    )
            elif item_type in {"special", "raw_snapshot"}:
                parts = list(payload.get("raw_parts") or [])
                if not parts:
                    self._window.show_error("原格式条目数据不存在或已损坏。")
                    return
                pasted = self._paste_service.paste_raw_snapshot(
                    parts,
                    self._pending_focus_target,
                    hide_window=hide_window_cb,
                )
            else:
                pasted = self._paste_service.paste_text(
                    str(payload.get("plain_text") or payload.get("text") or ""),
                    self._pending_focus_target,
                    hide_window=hide_window_cb,
                )
        else:
            pasted = self._paste_service.paste_text(
                item.text,
                self._pending_focus_target,
                hide_window=hide_window_cb,
            )
        if not pasted:
            self._window.show_error("粘贴失败，请重试。")
            return
        self._repository.mark_item_used(item_id)
        self._pending_focus_target = None

    def _on_clipboard_parsed_captured(self, parsed: ParsedClipboardItem) -> None:
        tab_id = self._capture_tab_id
        if tab_id is None:
            tabs = self._repository.list_tabs()
            if not tabs:
                return
            tab_id = tabs[0].id
            self._capture_tab_id = tab_id
            self._repository.set_setting("capture_tab_id", str(tab_id))
            self._window.set_capture_tab(tab_id, self._tab_name(tabs, tab_id))
        inserted = self._repository.insert_parsed_item(tab_id, parsed)
        if inserted is None:
            return
        current_tab_id = self._window.current_tab_id()
        if self._search_query:
            self._invalidate_items_cache(tab_id)
            self._refresh_items(current_tab_id or tab_id)
        elif current_tab_id == tab_id:
            if int(tab_id) in self._items_cache:
                self._items_cache[int(tab_id)].insert(0, inserted)
            self._window.prepend_item(inserted)
        else:
            self._invalidate_items_cache(tab_id)

    def _on_hotkey_change_requested(self, raw_hotkey: str) -> None:
        normalized, error = HotkeyService.normalize_hotkey(raw_hotkey)
        if error or not normalized:
            self._window.show_error(f"快捷键无效：{error or '未知错误'}")
            return

        logger.info(
            "[Hotkey] user change requested old=%s new=%s",
            self._hotkey_service.hotkey_text,
            normalized,
        )
        ok, start_error = self._hotkey_service.update_hotkey(normalized)
        if not ok:
            self._window.show_error(
                f"应用快捷键失败：{start_error or '未知错误'}。已回滚到上一个可用快捷键。"
            )
            return

        self._repository.set_setting("hotkey", normalized)
        self._window.set_hotkey_text(normalized)
        self._window.show_info(f"全局快捷键已更新为：{normalized}")

    def _on_hotkey_reset_requested(self) -> None:
        default_value = default_hotkey()
        ok, error = self._hotkey_service.update_hotkey(default_value)
        if not ok:
            self._window.show_error(f"恢复默认快捷键失败：{error or '未知错误'}")
            return
        self._repository.set_setting("hotkey", default_value)
        self._window.set_hotkey_text(default_value)
        self._window.show_info(f"已恢复默认快捷键：{default_value}")

    def _on_capture_tab_change_requested(self, tab_id: int) -> None:
        tabs = self._repository.list_tabs()
        if tab_id not in {tab.id for tab in tabs}:
            self._window.show_error("无效的监听存储标签。")
            return
        self._capture_tab_id = tab_id
        self._repository.set_setting("capture_tab_id", str(tab_id))
        self._window.set_capture_tab(tab_id, self._tab_name(tabs, tab_id))
        self._window.show_info(f"监听存储标签已设置为：{self._tab_name(tabs, tab_id)}")

    def _on_note_color_change_requested(self, color_hex: str) -> None:
        self._repository.set_setting("note_text_color", color_hex)
        font_size = self._parse_int_setting("note_font_size") or 13
        font_size = max(10, min(28, font_size))
        self._window.set_note_style(color_hex, font_size)

    def _on_note_font_size_change_requested(self, font_size: int) -> None:
        safe_size = max(10, min(28, int(font_size)))
        self._repository.set_setting("note_font_size", str(safe_size))
        color_hex = self._repository.get_setting("note_text_color") or "#1f2937"
        self._window.set_note_style(color_hex, safe_size)

    def _on_export_requested(self) -> None:
        tabs = self._repository.list_tabs()
        if not tabs:
            self._window.show_error("当前没有可导出的标签页。")
            return
        item_counts = {tab.id: self._repository.tab_item_count(tab.id) for tab in tabs}
        selected_tab_ids = self._window.prompt_select_local_tabs_for_export(tabs, item_counts)
        if selected_tab_ids is None:
            return
        export_path = self._window.prompt_export_file_path()
        if not export_path:
            return
        try:
            result = self._repository.export_tabs(selected_tab_ids, export_path)
        except Exception as exc:
            self._window.show_error(f"导出失败：{exc}")
            return
        self._window.show_info(
            "导出完成：\n"
            f"标签页：{result.tab_count}\n"
            f"条目：{result.item_count}\n"
            f"文件：{result.path}"
        )

    def _on_import_requested(self) -> None:
        import_path = self._window.prompt_import_file_path()
        if not import_path:
            return
        try:
            summary = self._repository.inspect_import_package(import_path)
        except Exception as exc:
            self._window.show_error(f"读取导入包失败：{exc}")
            return
        if not summary.tab_summaries:
            self._window.show_error("导入包中没有可导入的标签页。")
            return
        options = [
            (tab.package_tab_id, tab.name, tab.item_count)
            for tab in summary.tab_summaries
        ]
        selected_package_tab_ids = self._window.prompt_select_package_tabs_for_import(options)
        if selected_package_tab_ids is None:
            return
        try:
            result = self._repository.import_tabs(
                import_path,
                selected_package_tab_ids,
                conflict_mode="merge",
            )
        except Exception as exc:
            self._window.show_error(f"导入失败：{exc}")
            return
        self._invalidate_items_cache()
        active_tab_id = self._window.current_tab_id()
        self._refresh_tabs(active_tab_id=active_tab_id)
        self._window.show_info(
            "导入完成：\n"
            f"处理标签：{result.imported_tabs}（新建 {result.created_tabs}，合并 {result.merged_tabs}）\n"
            f"新增条目：{result.imported_items}\n"
            f"跳过重复：{result.skipped_items}\n"
            f"失败：{result.failed_items}"
        )

    def _refresh_tabs(self, active_tab_id: Optional[int] = None) -> None:
        tabs = self._repository.list_tabs()
        if not tabs:
            return
        if self._capture_tab_id not in {tab.id for tab in tabs}:
            self._capture_tab_id = tabs[0].id
            self._repository.set_setting("capture_tab_id", str(self._capture_tab_id))
        if active_tab_id is None:
            active_tab_id = tabs[0].id
        self._repository.set_setting("active_tab_id", str(active_tab_id))
        self._window.set_tabs(tabs, active_tab_id)
        self._window.set_capture_tab(self._capture_tab_id, self._tab_name(tabs, self._capture_tab_id))

    def _refresh_items(self, tab_id: Optional[int]) -> None:
        logger.debug(
            "[UI] refresh_items enter tab_id=%s search_mode=%s query=%s",
            tab_id,
            bool(self._search_query),
            self._search_query,
        )
        try:
            if self._search_query:
                started = time.perf_counter()
                items = self._repository.search_items_all_tabs(self._search_query, limit=1000)
                tabs = self._repository.list_tabs()
                load_ms = (time.perf_counter() - started) * 1000
                tab_name_map = {tab.id: tab.name for tab in tabs}
                self._window.set_items(items, search_mode=True, tab_name_map=tab_name_map)
                self._schedule_rich_prewarm(items)
                logger.info(
                    "[Perf] refresh_items search items=%s load_ms=%.1f cache_hit=False",
                    len(items),
                    load_ms,
                )
                return
            if tab_id is None:
                self._window.set_items([])
                self._schedule_rich_prewarm([])
                logger.debug("[UI] refresh_items done tab_id=None items=0")
                return
            cached_items = self._items_cache.get(int(tab_id))
            if cached_items is None:
                started = time.perf_counter()
                items = self._repository.list_items(tab_id)
                load_ms = (time.perf_counter() - started) * 1000
                self._items_cache[int(tab_id)] = list(items)
                cache_hit = False
            else:
                items = list(cached_items)
                load_ms = 0.0
                cache_hit = True
            self._window.set_items(items, search_mode=False, tab_name_map=None)
            self._schedule_rich_prewarm(items)
            logger.info(
                "[Perf] refresh_items tab_id=%s items=%s cache_hit=%s load_ms=%.1f",
                tab_id,
                len(items),
                cache_hit,
                load_ms,
            )
        except Exception:
            logger.exception(
                "[UI] refresh_items failed tab_id=%s search_mode=%s",
                tab_id,
                bool(self._search_query),
            )

    def _invalidate_items_cache(self, tab_id: Optional[int] = None) -> None:
        if tab_id is None:
            self._items_cache.clear()
            return
        self._items_cache.pop(int(tab_id), None)

    def _schedule_rich_prewarm(self, items: list) -> None:
        visible_rich_ids = [
            int(item.id)
            for item in items
            if getattr(item, "content_type", "") == "rich"
        ]
        visible_id_set = set(visible_rich_ids)
        for cached_id in list(self._rich_segments_cache.keys()):
            if cached_id not in visible_id_set:
                self._rich_segments_cache.pop(cached_id, None)

        self._rich_prewarm_timer.stop()
        self._rich_prewarm_ids = visible_id_set
        self._rich_prewarm_queue = [
            item_id
            for item_id in visible_rich_ids
            if item_id not in self._rich_segments_cache
        ]
        if self._rich_prewarm_queue:
            self._rich_prewarm_timer.start(120)

    def _prewarm_next_rich_batch(self) -> None:
        batch_size = 2
        processed = 0
        while self._rich_prewarm_queue and processed < batch_size:
            item_id = self._rich_prewarm_queue.pop(0)
            if item_id not in self._rich_prewarm_ids:
                continue
            if item_id in self._rich_segments_cache:
                continue
            try:
                segments = self._repository.get_item_rich_segments(item_id)
                if segments:
                    self._rich_segments_cache[item_id] = segments
                    self._paste_service.prepare_mixed_segments(segments)
            except Exception:
                logger.exception("[Paste] rich prewarm failed item_id=%s", item_id)
            processed += 1
        if self._rich_prewarm_queue:
            self._rich_prewarm_timer.start(120)

    def _invalidate_rich_cache(self, item_id: int) -> None:
        clean_id = int(item_id)
        self._rich_segments_cache.pop(clean_id, None)
        self._rich_prewarm_ids.discard(clean_id)
        self._rich_prewarm_queue = [queued_id for queued_id in self._rich_prewarm_queue if queued_id != clean_id]

    def _clear_rich_prewarm(self) -> None:
        self._rich_prewarm_timer.stop()
        self._rich_segments_cache.clear()
        self._rich_prewarm_queue = []
        self._rich_prewarm_ids.clear()

    @staticmethod
    def _tab_name(tabs, tab_id: Optional[int]) -> str:
        if tab_id is None:
            return "未设置"
        for tab in tabs:
            if tab.id == tab_id:
                return tab.name
        return "未设置"


