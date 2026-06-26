from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..models import ClipItem


@dataclass(frozen=True, slots=True)
class DisplayRow:
    primary_text: str
    secondary_text: str
    tooltip_text: str
    has_note: bool
    note_text: str = ""
    content_text: str = ""
    type_label: str = ""
    icon_kind: str | None = None
    file_icon_path: str | None = None


def present_item(item: ClipItem) -> DisplayRow:
    note = (item.note or "").strip()
    has_note = bool(note)
    content = _content_summary(item)
    if has_note and content:
        primary_source = f"{note} {content}"
    elif has_note:
        primary_source = note
    else:
        primary_source = content
    primary = _truncate_one_line(primary_source, 92)

    item_type = _type_label(item.content_type)
    time_text = _format_time(item.created_at)
    meta_text = _meta_summary(item)
    secondary_segments = [time_text]
    if meta_text:
        secondary_segments.append(meta_text)
    secondary = " · ".join(segment for segment in secondary_segments if segment)

    tooltip_sections: list[str] = []
    if has_note:
        tooltip_sections.append(note)
    plain_text = (item.plain_text or item.text or "").strip()
    if plain_text:
        tooltip_sections.append(plain_text)
    elif content:
        tooltip_sections.append(content)
    if item.content_type == "files" and item.file_paths:
        tooltip_sections.append("\n".join(item.file_paths))
    if item.content_type in {"special", "raw_snapshot"} and item.mime_formats:
        tooltip_sections.append("格式：\n" + "\n".join(item.mime_formats))
    tooltip = "\n---\n".join(section for section in tooltip_sections if section) or content

    icon_kind, file_icon_path = _resolve_icon(item)
    return DisplayRow(
        primary_text=primary or "[空内容]",
        secondary_text=secondary or item_type,
        tooltip_text=tooltip or "[空内容]",
        has_note=has_note,
        note_text=note,
        content_text=content or "[空内容]",
        type_label=item_type,
        icon_kind=icon_kind,
        file_icon_path=file_icon_path,
    )


def _resolve_icon(item: ClipItem) -> tuple[str | None, str | None]:
    if item.content_type == "image" and item.thumb_blob:
        return "image", None
    if item.content_type == "bundle" and item.thumb_blob:
        return "image", None
    if item.content_type == "rich" and item.thumb_blob:
        return "image", None
    if item.content_type == "files" and item.file_paths:
        return "file", item.file_paths[0]
    if item.content_type == "special":
        return "special", None
    return None, None


def _content_summary(item: ClipItem) -> str:
    text = (item.display_text or "").replace("\r", "\n")
    text = _compact_whitespace(text)
    if text:
        return text

    if item.content_type == "image":
        width = int(item.width or 0)
        height = int(item.height or 0)
        return f"[图片] {width}x{height}"
    if item.content_type == "files":
        paths = list(item.file_paths or [])
        if not paths:
            return "[文件]"
        if len(paths) == 1:
            return Path(paths[0]).name or paths[0]
        return f"{Path(paths[0]).name or paths[0]} 等 {len(paths)} 个文件"
    if item.content_type == "special":
        return "[特殊内容]"
    if item.content_type == "bundle":
        head = _compact_whitespace(item.text)
        count = int(item.image_count or 0)
        base = head or "[复合条目]"
        if count <= 0:
            return base
        if count == 1:
            return f"{base} [图片]"
        return f"{base} [图片x{count}] +{count - 1}"
    if item.content_type == "html":
        return _compact_whitespace(item.plain_text or item.text or "[HTML]")
    if item.content_type == "rich":
        rich_text = _compact_whitespace(item.plain_text or "")
        if rich_text:
            return rich_text
        if item.thumb_blob:
            width = int(item.width or 0)
            height = int(item.height or 0)
            if width > 0 and height > 0:
                return f"[图片] {width}x{height}"
            return "[图文内容]"
        return "[图文内容]"
    if item.content_type == "url":
        return _compact_whitespace(item.plain_text or item.text or "[链接]")
    if item.content_type == "raw_snapshot":
        formats = list(item.mime_formats or [])
        if formats:
            top = " + ".join(formats[:2])
            if len(formats) > 2:
                top = f"{top} + ..."
            return f"[原格式] {top}"
        return "[原格式]"
    return _compact_whitespace(item.text)


def _meta_summary(item: ClipItem) -> str:
    if item.content_type == "image":
        width = int(item.width or 0)
        height = int(item.height or 0)
        return f"{width}x{height}"
    if item.content_type == "files":
        count = len(item.file_paths or [])
        if count <= 0:
            return ""
        return f"{count} 个文件"
    if item.content_type == "bundle":
        count = int(item.image_count or 0)
        if count > 0:
            return f"图片x{count}"
    if item.content_type in {"special", "raw_snapshot"}:
        count = len(item.mime_formats or [])
        if count > 0:
            return f"{count} 种格式"
    return ""


def _type_label(content_type: str) -> str:
    mapping = {
        "text": "文本",
        "html": "富文本",
        "rich": "图文",
        "image": "图片",
        "files": "文件",
        "url": "链接",
        "special": "特殊",
        "bundle": "复合",
        "raw_snapshot": "原格式",
    }
    return mapping.get(content_type, "条目")


def _format_time(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    try:
        dt = datetime.fromisoformat(text)
        return dt.strftime("%m-%d %H:%M")
    except ValueError:
        pass
    try:
        dt = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%m-%d %H:%M")
    except ValueError:
        return text[-16:] if len(text) > 16 else text


def _compact_whitespace(text: str) -> str:
    cleaned = " ".join((text or "").replace("\r", "\n").split())
    return cleaned.strip()


def _truncate_one_line(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."
