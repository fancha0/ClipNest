from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ClipboardItemType = Literal["text", "html", "image", "files", "url", "special"]


@dataclass(slots=True)
class Tab:
    id: int
    name: str
    sort_order: int
    created_at: str
    updated_at: str


@dataclass(slots=True)
class ClipItem:
    id: int
    tab_id: int
    sort_order: int
    content_type: str
    text: str
    mime_type: str | None
    width: int | None
    height: int | None
    content_hash: str
    created_at: str
    last_used_at: str
    use_count: int
    note: str = ""
    image_count: int | None = None
    mime_part_count: int | None = None
    display_text: str = ""
    plain_text: str = ""
    html_text: str = ""
    file_paths: list[str] | None = None
    mime_formats: list[str] | None = None
    pinned: bool = False
    source_app: str | None = None
    thumb_blob: bytes | None = None


@dataclass(slots=True)
class BundleImage:
    id: int
    item_id: int
    sort_order: int
    image_blob: bytes
    mime_type: str | None
    width: int | None
    height: int | None
    image_hash: str


@dataclass(slots=True)
class MimePart:
    id: int
    item_id: int
    sort_order: int
    mime_type: str
    payload_blob: bytes
    payload_hash: str


@dataclass(slots=True)
class ParsedClipboardItem:
    item_type: ClipboardItemType
    display_text: str
    plain_text: str
    html_text: str
    image_blob: bytes | None
    thumb_blob: bytes | None
    width: int | None
    height: int | None
    file_paths: list[str]
    mime_formats: list[str]
    raw_parts: list[dict[str, bytes]]
    source_app: str | None = None


@dataclass(slots=True)
class PackageTabSummary:
    package_tab_id: str
    name: str
    item_count: int


@dataclass(slots=True)
class PackageSummary:
    version: int
    exported_at: str
    tab_summaries: list[PackageTabSummary]


@dataclass(slots=True)
class ExportResult:
    path: str
    tab_count: int
    item_count: int
    binary_count: int


@dataclass(slots=True)
class ImportResult:
    imported_tabs: int
    created_tabs: int
    merged_tabs: int
    imported_items: int
    skipped_items: int
    failed_items: int


@dataclass(slots=True)
class MoveItemsResult:
    moved_count: int
    already_in_target_count: int
