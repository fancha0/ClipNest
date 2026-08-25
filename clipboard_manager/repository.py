from __future__ import annotations

import base64
import hashlib
import html as html_lib
import json
import sqlite3
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage

from .config import DEFAULT_TABS, MAX_ITEMS_PER_TAB, default_hotkey
from .models import (
    BundleImage,
    ClipItem,
    ExportResult,
    ImportResult,
    MoveItemsResult,
    MimePart,
    PackageSummary,
    PackageTabSummary,
    ParsedClipboardItem,
    Tab,
)


class ClipRepository:
    RAW_SNAPSHOT_DEDUPE_WINDOW_MS = 1000
    PACKAGE_VERSION = 1

    _LIST_ITEM_COLUMNS = ",\n                    ".join(
        [
            "i.id",
            "i.tab_id",
            "i.sort_order",
            "i.content_type",
            "i.text",
            "i.mime_type",
            "i.width",
            "i.height",
            "i.content_hash",
            "i.created_at",
            "i.last_used_at",
            "i.use_count",
            "i.note",
            "i.display_text",
            "i.plain_text",
            "i.html_text",
            "i.file_paths_json",
            "i.mime_formats_json",
            "i.pinned",
            "i.source_app",
            "i.thumb_blob",
        ]
    )

    def __init__(self, db_path: Path, max_items_per_tab: int = MAX_ITEMS_PER_TAB) -> None:
        self.db_path = Path(db_path)
        self.max_items_per_tab = max_items_per_tab
        self._tab_capacity_overrides: dict[int, int] = {}
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = None
        self._initialize()

    def _open_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA cache_size = -8000")
        return conn

    def _get_conn(self):
        if self._conn is None:
            self._conn = self._open_connection()
        return self._conn

    @contextmanager
    def _connect(self):
        conn = self._get_conn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS tabs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    sort_order INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tab_id INTEGER NOT NULL,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    content_type TEXT NOT NULL DEFAULT 'text',
                    text TEXT NOT NULL DEFAULT '',
                    note TEXT NOT NULL DEFAULT '',
                    image_blob BLOB,
                    mime_type TEXT,
                    width INTEGER,
                    height INTEGER,
                    content_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_used_at TEXT NOT NULL,
                    use_count INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(tab_id) REFERENCES tabs(id) ON DELETE CASCADE,
                    UNIQUE(tab_id, content_hash)
                );

                CREATE INDEX IF NOT EXISTS idx_items_tab_created
                    ON items(tab_id, created_at DESC, id DESC);
                CREATE INDEX IF NOT EXISTS idx_items_tab_last_used
                    ON items(tab_id, last_used_at DESC, id DESC);

                CREATE TABLE IF NOT EXISTS item_images (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id INTEGER NOT NULL,
                    sort_order INTEGER NOT NULL,
                    image_blob BLOB NOT NULL,
                    mime_type TEXT,
                    width INTEGER,
                    height INTEGER,
                    image_hash TEXT NOT NULL,
                    FOREIGN KEY(item_id) REFERENCES items(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_item_images_item_sort
                    ON item_images(item_id, sort_order, id);

                CREATE TABLE IF NOT EXISTS item_mime_parts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id INTEGER NOT NULL,
                    sort_order INTEGER NOT NULL,
                    mime_type TEXT NOT NULL,
                    payload_blob BLOB NOT NULL,
                    payload_hash TEXT NOT NULL,
                    FOREIGN KEY(item_id) REFERENCES items(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_item_mime_parts_item_sort
                    ON item_mime_parts(item_id, sort_order, id);

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            self._ensure_items_columns(conn)

            tab_count = conn.execute("SELECT COUNT(*) FROM tabs").fetchone()[0]
            if tab_count == 0:
                now = self._now()
                for idx, tab_name in enumerate(DEFAULT_TABS):
                    conn.execute(
                        "INSERT INTO tabs(name, sort_order, created_at, updated_at) VALUES (?, ?, ?, ?)",
                        (tab_name, idx, now, now),
                    )

            if self.get_setting("hotkey", conn=conn) is None:
                self.set_setting("hotkey", default_hotkey(), conn=conn)
            if self.get_setting("always_on_top", conn=conn) is None:
                self.set_setting("always_on_top", "0", conn=conn)
            if self.get_setting("active_tab_id", conn=conn) is None:
                first_tab = conn.execute("SELECT id FROM tabs ORDER BY sort_order, id LIMIT 1").fetchone()
                if first_tab:
                    self.set_setting("active_tab_id", str(first_tab["id"]), conn=conn)
            if self.get_setting("capture_tab_id", conn=conn) is None:
                first_tab = conn.execute("SELECT id FROM tabs ORDER BY sort_order, id LIMIT 1").fetchone()
                if first_tab:
                    self.set_setting("capture_tab_id", str(first_tab["id"]), conn=conn)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _to_epoch_ms(iso_value: str) -> int:
        return int(datetime.fromisoformat(iso_value).timestamp() * 1000)

    @staticmethod
    def _hash_text(text: str) -> str:
        return "text:" + hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _hash_image(image_bytes: bytes) -> str:
        return "image:" + hashlib.sha256(image_bytes).hexdigest()

    @staticmethod
    def _hash_bundle(text: str, image_hashes: list[str]) -> str:
        digest = hashlib.sha256()
        digest.update(text.encode("utf-8"))
        digest.update(b"\x1f")
        for image_hash in image_hashes:
            digest.update(image_hash.encode("utf-8"))
            digest.update(b"\x1e")
        return "bundle:" + digest.hexdigest()

    @staticmethod
    def _hash_raw_snapshot(parts: list[dict[str, Any]]) -> str:
        digest = hashlib.sha256()
        normalized = sorted(parts, key=lambda x: str(x["mime_type"]))
        for part in normalized:
            digest.update(str(part["mime_type"]).encode("utf-8"))
            digest.update(b"\x1f")
            digest.update(bytes(part["payload_blob"]))
            digest.update(b"\x1e")
        return "raw:" + digest.hexdigest()

    @staticmethod
    def _make_thumbnail_blob(image_bytes: bytes, max_edge: int = 112) -> bytes | None:
        if not image_bytes:
            return None
        image = QImage()
        if not image.loadFromData(image_bytes):
            return None
        thumb = image.scaled(
            max_edge,
            max_edge,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        data = QByteArray()
        buffer = QBuffer(data)
        if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
            return None
        ok = thumb.save(buffer, "PNG")
        buffer.close()
        if not ok:
            return None
        return bytes(data)

    def _bundle_thumb_blob(self, images: list[dict[str, Any]]) -> bytes | None:
        if not images:
            return None
        first_blob = images[0].get("image_blob")
        if not isinstance(first_blob, (bytes, bytearray)):
            return None
        raw = bytes(first_blob)
        thumb = self._make_thumbnail_blob(raw)
        return thumb or raw

    @staticmethod
    def _next_item_sort_order(conn: sqlite3.Connection, tab_id: int) -> int:
        row = conn.execute(
            "SELECT MIN(sort_order) AS min_order FROM items WHERE tab_id = ?",
            (tab_id,),
        ).fetchone()
        if not row:
            return 0
        min_order = row["min_order"]
        if min_order is None:
            return 0
        return int(min_order) - 1

    @staticmethod
    def _to_tab(row: sqlite3.Row) -> Tab:
        return Tab(
            id=row["id"],
            name=row["name"],
            sort_order=row["sort_order"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _to_item(row: sqlite3.Row) -> ClipItem:
        file_paths = []
        mime_formats = []
        if "file_paths_json" in row.keys():
            try:
                file_paths = json.loads(row["file_paths_json"] or "[]")
            except Exception:
                file_paths = []
        if "mime_formats_json" in row.keys():
            try:
                mime_formats = json.loads(row["mime_formats_json"] or "[]")
            except Exception:
                mime_formats = []
        return ClipItem(
            id=row["id"],
            tab_id=row["tab_id"],
            sort_order=int(row["sort_order"]) if "sort_order" in row.keys() else 0,
            content_type=row["content_type"],
            text=row["text"],
            mime_type=row["mime_type"],
            width=row["width"],
            height=row["height"],
            content_hash=row["content_hash"],
            created_at=row["created_at"],
            last_used_at=row["last_used_at"],
            use_count=row["use_count"],
            note=row["note"] if "note" in row.keys() else "",
            image_count=row["image_count"] if "image_count" in row.keys() else None,
            mime_part_count=row["mime_part_count"] if "mime_part_count" in row.keys() else None,
            display_text=row["display_text"] if "display_text" in row.keys() else row["text"],
            plain_text=row["plain_text"] if "plain_text" in row.keys() else row["text"],
            html_text=row["html_text"] if "html_text" in row.keys() else "",
            file_paths=file_paths,
            mime_formats=mime_formats,
            pinned=bool(row["pinned"]) if "pinned" in row.keys() else False,
            source_app=row["source_app"] if "source_app" in row.keys() else None,
            thumb_blob=row["thumb_blob"] if "thumb_blob" in row.keys() else None,
        )

    @staticmethod
    def _to_bundle_image(row: sqlite3.Row) -> BundleImage:
        return BundleImage(
            id=row["id"],
            item_id=row["item_id"],
            sort_order=row["sort_order"],
            image_blob=row["image_blob"],
            mime_type=row["mime_type"],
            width=row["width"],
            height=row["height"],
            image_hash=row["image_hash"],
        )

    @staticmethod
    def _to_mime_part(row: sqlite3.Row) -> MimePart:
        return MimePart(
            id=row["id"],
            item_id=row["item_id"],
            sort_order=row["sort_order"],
            mime_type=row["mime_type"],
            payload_blob=row["payload_blob"],
            payload_hash=row["payload_hash"],
        )

    def list_tabs(self) -> list[Tab]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM tabs ORDER BY sort_order, id").fetchall()
        return [self._to_tab(row) for row in rows]

    def create_tab(self, name: str) -> Tab:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("标签页名称不能为空。")
        now = self._now()
        with self._connect() as conn:
            max_order_row = conn.execute("SELECT COALESCE(MAX(sort_order), -1) AS max_order FROM tabs").fetchone()
            sort_order = int(max_order_row["max_order"]) + 1
            cursor = conn.execute(
                "INSERT INTO tabs(name, sort_order, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (clean_name, sort_order, now, now),
            )
            row = conn.execute("SELECT * FROM tabs WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return self._to_tab(row)

    def reorder_tabs(self, tab_ids: list[int]) -> None:
        normalized_ids: list[int] = []
        for tab_id in tab_ids:
            try:
                normalized_ids.append(int(tab_id))
            except (TypeError, ValueError) as exc:
                raise ValueError("标签页顺序包含无效 ID。") from exc
        if len(set(normalized_ids)) != len(normalized_ids):
            raise ValueError("标签页顺序包含重复 ID。")

        with self._connect() as conn:
            rows = conn.execute("SELECT id FROM tabs").fetchall()
            existing_ids = [int(row["id"]) for row in rows]
            if len(normalized_ids) != len(existing_ids) or set(normalized_ids) != set(existing_ids):
                raise ValueError("标签页顺序必须完整且仅包含当前全部标签。")

            now = self._now()
            for sort_order, tab_id in enumerate(normalized_ids):
                conn.execute(
                    "UPDATE tabs SET sort_order = ?, updated_at = ? WHERE id = ?",
                    (sort_order, now, tab_id),
                )

    def reorder_items(self, tab_id: int, item_ids: list[int]) -> None:
        normalized_tab_id = int(tab_id)
        normalized_ids = [int(item_id) for item_id in item_ids]
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id FROM items WHERE tab_id = ?",
                (normalized_tab_id,),
            ).fetchall()
            existing_ids = [int(row["id"]) for row in rows]
            existing_set = set(existing_ids)
            provided_set = set(normalized_ids)
            if len(normalized_ids) != len(provided_set):
                raise ValueError("条目顺序包含重复 ID。")
            if provided_set != existing_set:
                raise ValueError("条目顺序必须完整且仅包含当前标签页全部条目。")
            for sort_order, item_id in enumerate(normalized_ids):
                conn.execute(
                    "UPDATE items SET sort_order = ? WHERE id = ?",
                    (sort_order, item_id),
                )

    def move_items_to_tab(self, item_ids: list[int], target_tab_id: int) -> MoveItemsResult:
        normalized_target_tab_id = int(target_tab_id)
        normalized_ids: list[int] = []
        seen: set[int] = set()
        for raw in item_ids:
            try:
                item_id = int(raw)
            except (TypeError, ValueError) as exc:
                raise ValueError("条目列表包含无效 ID。") from exc
            if item_id in seen:
                continue
            seen.add(item_id)
            normalized_ids.append(item_id)
        if not normalized_ids:
            raise ValueError("未选择可移动的条目。")

        with self._connect() as conn:
            target_row = conn.execute(
                "SELECT id FROM tabs WHERE id = ?",
                (normalized_target_tab_id,),
            ).fetchone()
            if target_row is None:
                raise ValueError("目标标签不存在。")

            placeholders = ",".join("?" for _ in normalized_ids)
            rows = conn.execute(
                f"SELECT id, tab_id, content_hash FROM items WHERE id IN ({placeholders})",
                tuple(normalized_ids),
            ).fetchall()
            row_map = {int(row["id"]): row for row in rows}
            missing_ids = [item_id for item_id in normalized_ids if item_id not in row_map]
            if missing_ids:
                raise ValueError("存在无效条目，移动已取消。")

            moved_count = 0
            already_in_target_count = 0
            for item_id in normalized_ids:
                row = row_map[item_id]
                source_tab_id = int(row["tab_id"])
                if source_tab_id == normalized_target_tab_id:
                    already_in_target_count += 1
                    continue

                sort_order = self._next_item_sort_order(conn, normalized_target_tab_id)
                content_hash = str(row["content_hash"] or "")
                try:
                    conn.execute(
                        "UPDATE items SET tab_id = ?, sort_order = ? WHERE id = ?",
                        (normalized_target_tab_id, sort_order, item_id),
                    )
                except sqlite3.IntegrityError:
                    conflict_safe_hash = self._next_move_conflict_hash(
                        conn=conn,
                        tab_id=normalized_target_tab_id,
                        content_hash=content_hash,
                        item_id=item_id,
                    )
                    conn.execute(
                        "UPDATE items SET tab_id = ?, sort_order = ?, content_hash = ? WHERE id = ?",
                        (normalized_target_tab_id, sort_order, conflict_safe_hash, item_id),
                    )

                self._enforce_capacity(conn, normalized_target_tab_id)
                moved_count += 1

            return MoveItemsResult(
                moved_count=moved_count,
                already_in_target_count=already_in_target_count,
            )

    def _next_move_conflict_hash(
        self,
        conn: sqlite3.Connection,
        tab_id: int,
        content_hash: str,
        item_id: int,
    ) -> str:
        base = (content_hash or "").strip()
        if base == "":
            base = f"move#{item_id}"
        suffix = 1
        while True:
            candidate = f"{base}#move#{item_id}#{suffix}"
            row = conn.execute(
                "SELECT 1 FROM items WHERE tab_id = ? AND content_hash = ?",
                (tab_id, candidate),
            ).fetchone()
            if row is None:
                return candidate
            suffix += 1

    def export_tabs(self, tab_ids: list[int], output_path: str) -> ExportResult:
        normalized_ids: list[int] = []
        for tab_id in tab_ids:
            try:
                normalized_ids.append(int(tab_id))
            except (TypeError, ValueError) as exc:
                raise ValueError("导出标签列表包含无效 ID。") from exc
        if not normalized_ids:
            raise ValueError("请至少选择一个标签页。")
        if len(set(normalized_ids)) != len(normalized_ids):
            raise ValueError("导出标签列表包含重复 ID。")

        export_path = Path(output_path).expanduser()
        export_path.parent.mkdir(parents=True, exist_ok=True)
        if export_path.suffix.lower() != ".fluxpkg":
            export_path = export_path.with_suffix(".fluxpkg")

        conn = self._open_connection()
        try:
            rows = conn.execute("SELECT * FROM tabs").fetchall()
            tab_map = {int(row["id"]): row for row in rows}
            if set(normalized_ids) - set(tab_map.keys()):
                raise ValueError("导出标签列表包含不存在的标签。")

            binary_refs: dict[str, str] = {}
            manifest_tabs: list[dict[str, Any]] = []
            total_items = 0

            with zipfile.ZipFile(export_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for tab_id in normalized_ids:
                    tab_row = tab_map[tab_id]
                    item_rows = conn.execute(
                        """
                        SELECT *
                        FROM items
                        WHERE tab_id = ?
                        ORDER BY created_at DESC, id DESC
                        """,
                        (tab_id,),
                    ).fetchall()
                    tab_payload: dict[str, Any] = {
                        "package_tab_id": str(tab_id),
                        "name": str(tab_row["name"]),
                        "sort_order": int(tab_row["sort_order"]),
                        "items": [],
                    }
                    for item_row in item_rows:
                        item_payload = self._serialize_item_for_export(
                            conn=conn,
                            zf=zf,
                            binary_refs=binary_refs,
                            item_row=item_row,
                        )
                        tab_payload["items"].append(item_payload)
                        total_items += 1
                    manifest_tabs.append(tab_payload)

                manifest = {
                    "format": "clipnest-package",
                    "version": self.PACKAGE_VERSION,
                    "exported_at": self._now(),
                    "tabs": manifest_tabs,
                }
                zf.writestr(
                    "manifest.json",
                    json.dumps(manifest, ensure_ascii=False, indent=2),
                )
        finally:
            conn.close()

        return ExportResult(
            path=str(export_path),
            tab_count=len(manifest_tabs),
            item_count=total_items,
            binary_count=len(binary_refs),
        )

    def inspect_import_package(self, path: str) -> PackageSummary:
        manifest = self._read_package_manifest(path)
        tab_summaries: list[PackageTabSummary] = []
        tabs = manifest.get("tabs") or []
        if not isinstance(tabs, list):
            raise ValueError("导入包格式错误：tabs 无效。")
        for tab in tabs:
            if not isinstance(tab, dict):
                continue
            items = tab.get("items") or []
            if not isinstance(items, list):
                items = []
            tab_summaries.append(
                PackageTabSummary(
                    package_tab_id=str(tab.get("package_tab_id") or ""),
                    name=str(tab.get("name") or "未命名标签"),
                    item_count=len(items),
                )
            )
        return PackageSummary(
            version=int(manifest.get("version") or 0),
            exported_at=str(manifest.get("exported_at") or ""),
            tab_summaries=tab_summaries,
        )

    def import_tabs(
        self,
        path: str,
        selected_package_tab_ids: list[str],
        conflict_mode: str = "merge",
    ) -> ImportResult:
        if conflict_mode != "merge":
            raise ValueError("当前仅支持合并导入模式。")
        selected_ids = {str(tab_id).strip() for tab_id in selected_package_tab_ids if str(tab_id).strip()}
        if not selected_ids:
            raise ValueError("请至少选择一个导入标签页。")

        manifest = self._read_package_manifest(path)
        tabs = manifest.get("tabs") or []
        if not isinstance(tabs, list):
            raise ValueError("导入包格式错误：tabs 无效。")

        imported_tabs = 0
        created_tabs = 0
        merged_tabs = 0
        imported_items = 0
        skipped_items = 0
        failed_items = 0

        with self._connect() as conn:
            tab_rows = conn.execute("SELECT id, name FROM tabs").fetchall()
            local_tab_by_name = {str(row["name"]): int(row["id"]) for row in tab_rows}
            max_sort_row = conn.execute("SELECT COALESCE(MAX(sort_order), -1) AS m FROM tabs").fetchone()
            max_sort_order = int(max_sort_row["m"])

            with zipfile.ZipFile(path, "r") as zf:
                for tab_payload in tabs:
                    if not isinstance(tab_payload, dict):
                        continue
                    package_tab_id = str(tab_payload.get("package_tab_id") or "")
                    if package_tab_id not in selected_ids:
                        continue

                    tab_name = str(tab_payload.get("name") or "").strip() or "未命名标签"
                    target_tab_id = local_tab_by_name.get(tab_name)
                    if target_tab_id is None:
                        max_sort_order += 1
                        now = self._now()
                        cursor = conn.execute(
                            "INSERT INTO tabs(name, sort_order, created_at, updated_at) VALUES (?, ?, ?, ?)",
                            (tab_name, max_sort_order, now, now),
                        )
                        target_tab_id = int(cursor.lastrowid)
                        local_tab_by_name[tab_name] = target_tab_id
                        created_tabs += 1
                    else:
                        merged_tabs += 1
                    imported_tabs += 1

                    tab_items = tab_payload.get("items") or []
                    if not isinstance(tab_items, list):
                        continue
                    for item_payload in tab_items:
                        try:
                            inserted = self._import_item_from_package(
                                conn=conn,
                                zf=zf,
                                target_tab_id=target_tab_id,
                                item_payload=item_payload,
                            )
                            if inserted:
                                imported_items += 1
                            else:
                                skipped_items += 1
                        except Exception:
                            failed_items += 1
                    self._enforce_capacity(conn, target_tab_id)

        return ImportResult(
            imported_tabs=imported_tabs,
            created_tabs=created_tabs,
            merged_tabs=merged_tabs,
            imported_items=imported_items,
            skipped_items=skipped_items,
            failed_items=failed_items,
        )

    def rename_tab(self, tab_id: int, new_name: str) -> None:
        clean_name = new_name.strip()
        if not clean_name:
            raise ValueError("标签页名称不能为空。")
        with self._connect() as conn:
            conn.execute(
                "UPDATE tabs SET name = ?, updated_at = ? WHERE id = ?",
                (clean_name, self._now(), tab_id),
            )

    def delete_tab(self, tab_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM tabs WHERE id = ?", (tab_id,))

    def tab_item_count(self, tab_id: int) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM items WHERE tab_id = ?", (tab_id,)).fetchone()
        return int(row["c"])

    def list_items(self, tab_id: int) -> list[ClipItem]:
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    {self._LIST_ITEM_COLUMNS},
                    (SELECT COUNT(*) FROM item_images bi WHERE bi.item_id = i.id) AS image_count,
                    (SELECT COUNT(*) FROM item_mime_parts mp WHERE mp.item_id = i.id) AS mime_part_count
                FROM items i
                WHERE i.tab_id = ?
                ORDER BY i.pinned DESC, i.sort_order ASC, i.created_at DESC, i.id DESC
                """,
                (tab_id,),
            ).fetchall()
        return [self._to_item(row) for row in rows]

    def search_items_all_tabs(self, query: str, limit: int = 1000) -> list[ClipItem]:
        clean_query = (query or "").strip()
        if clean_query == "":
            return []
        try:
            safe_limit = max(1, int(limit))
        except (TypeError, ValueError):
            safe_limit = 1000
        escaped_query = self._escape_like(clean_query)
        like_pattern = f"%{escaped_query}%"
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    {self._LIST_ITEM_COLUMNS},
                    (SELECT COUNT(*) FROM item_images bi WHERE bi.item_id = i.id) AS image_count,
                    (SELECT COUNT(*) FROM item_mime_parts mp WHERE mp.item_id = i.id) AS mime_part_count
                FROM items i
                WHERE
                    COALESCE(i.display_text, '') LIKE ? ESCAPE '\\'
                    OR COALESCE(i.plain_text, '') LIKE ? ESCAPE '\\'
                    OR COALESCE(i.text, '') LIKE ? ESCAPE '\\'
                    OR COALESCE(i.html_text, '') LIKE ? ESCAPE '\\'
                    OR COALESCE(i.note, '') LIKE ? ESCAPE '\\'
                    OR COALESCE(i.file_paths_json, '') LIKE ? ESCAPE '\\'
                    OR COALESCE(i.mime_formats_json, '') LIKE ? ESCAPE '\\'
                ORDER BY i.pinned DESC, i.created_at DESC, i.id DESC
                LIMIT ?
                """,
                (
                    like_pattern,
                    like_pattern,
                    like_pattern,
                    like_pattern,
                    like_pattern,
                    like_pattern,
                    like_pattern,
                    safe_limit,
                ),
            ).fetchall()
        return [self._to_item(row) for row in rows]

    def set_item_pinned(self, item_id: int, pinned: bool) -> ClipItem:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM items WHERE id = ?", (int(item_id),)).fetchone()
            if row is None:
                raise ValueError("未找到条目。")
            conn.execute(
                "UPDATE items SET pinned = ? WHERE id = ?",
                (1 if bool(pinned) else 0, int(item_id)),
            )
            updated = conn.execute("SELECT * FROM items WHERE id = ?", (int(item_id),)).fetchone()
            return self._to_item(updated)

    def get_item(self, item_id: int) -> Optional[ClipItem]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    i.*,
                    (SELECT COUNT(*) FROM item_images bi WHERE bi.item_id = i.id) AS image_count,
                    (SELECT COUNT(*) FROM item_mime_parts mp WHERE mp.item_id = i.id) AS mime_part_count
                FROM items i
                WHERE i.id = ?
                """,
                (item_id,),
            ).fetchone()
        if not row:
            return None
        return self._to_item(row)

    def upsert_text_item(self, tab_id: int, text: str) -> Optional[ClipItem]:
        if text is None:
            return None
        if text.strip() == "":
            return None

        content_hash = self._hash_text(text)
        now = self._now()
        with self._connect() as conn:
            existing_row = conn.execute(
                """
                SELECT * FROM items
                WHERE tab_id = ? AND content_type = 'text' AND content_hash = ?
                """,
                (tab_id, content_hash),
            ).fetchone()
            if existing_row:
                return self._to_item(existing_row)

            sort_order = self._next_item_sort_order(conn, tab_id)
            cursor = conn.execute(
                """
                INSERT INTO items(
                    tab_id, sort_order, content_type, text, note, image_blob, mime_type, width, height,
                    content_hash, created_at, last_used_at, use_count
                )
                VALUES (?, ?, 'text', ?, '', NULL, NULL, NULL, NULL, ?, ?, ?, 0)
                """,
                (tab_id, sort_order, text, content_hash, now, now),
            )
            inserted = conn.execute("SELECT * FROM items WHERE id = ?", (cursor.lastrowid,)).fetchone()
            self._enforce_capacity(conn, tab_id)
            return self._to_item(inserted)

    def upsert_image_item(
        self,
        tab_id: int,
        image_bytes: bytes,
        mime_type: str = "image/png",
        width: int | None = None,
        height: int | None = None,
    ) -> Optional[ClipItem]:
        if not image_bytes:
            return None

        content_hash = self._hash_image(image_bytes)
        now = self._now()
        with self._connect() as conn:
            existing_row = conn.execute(
                """
                SELECT * FROM items
                WHERE tab_id = ? AND content_type = 'image' AND content_hash = ?
                """,
                (tab_id, content_hash),
            ).fetchone()
            if existing_row:
                return self._to_item(existing_row)

            sort_order = self._next_item_sort_order(conn, tab_id)
            cursor = conn.execute(
                """
                INSERT INTO items(
                    tab_id, sort_order, content_type, text, note, image_blob, mime_type, width, height,
                    content_hash, created_at, last_used_at, use_count
                )
                VALUES (?, ?, 'image', '', '', ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    tab_id,
                    sort_order,
                    image_bytes,
                    mime_type,
                    width,
                    height,
                    content_hash,
                    now,
                    now,
                ),
            )
            inserted = conn.execute("SELECT * FROM items WHERE id = ?", (cursor.lastrowid,)).fetchone()
            self._enforce_capacity(conn, tab_id)
            return self._to_item(inserted)

    def upsert_raw_snapshot_item(
        self,
        tab_id: int,
        mime_parts: list[dict[str, Any]],
        preview_text: str,
        note: str = "",
        captured_at_ms: int | None = None,
    ) -> Optional[ClipItem]:
        prepared = self._prepare_mime_parts(mime_parts)
        if not prepared:
            return None
        clean_preview = (preview_text or "").strip()
        clean_note = (note or "").strip()
        base_hash = self._hash_raw_snapshot(prepared)
        captured_ms = int(captured_at_ms) if captured_at_ms is not None else self._to_epoch_ms(self._now())
        mime_types = [str(part["mime_type"]) for part in prepared]
        now = datetime.fromtimestamp(captured_ms / 1000.0, tz=timezone.utc).isoformat()
        content_hash = f"{base_hash}#{captured_ms}"
        with self._connect() as conn:
            # Backward compatible lookup:
            # old rows use content_hash == base_hash
            # new rows use content_hash like f"{base_hash}#<epoch_ms>"
            latest_same_payload = conn.execute(
                """
                SELECT
                    i.*,
                    (SELECT COUNT(*) FROM item_images bi WHERE bi.item_id = i.id) AS image_count,
                    (SELECT COUNT(*) FROM item_mime_parts mp WHERE mp.item_id = i.id) AS mime_part_count
                FROM items i
                WHERE i.tab_id = ?
                  AND i.content_type = 'raw_snapshot'
                  AND (i.content_hash = ? OR i.content_hash LIKE ?)
                ORDER BY i.created_at DESC, i.id DESC
                LIMIT 1
                """,
                (tab_id, base_hash, f"{base_hash}#%"),
            ).fetchone()
            if latest_same_payload:
                latest_ms = self._to_epoch_ms(latest_same_payload["created_at"])
                if 0 <= captured_ms - latest_ms <= self.RAW_SNAPSHOT_DEDUPE_WINDOW_MS:
                    return self._to_item(latest_same_payload)

            sort_order = self._next_item_sort_order(conn, tab_id)
            cursor = conn.execute(
                """
                INSERT INTO items(
                    tab_id, sort_order, content_type, text, note, image_blob, mime_type, width, height,
                    content_hash, created_at, last_used_at, use_count
                )
                VALUES (?, ?, 'raw_snapshot', ?, ?, NULL, ?, NULL, NULL, ?, ?, ?, 0)
                """,
                (
                    tab_id,
                    sort_order,
                    clean_preview,
                    clean_note,
                    "|".join(mime_types),
                    content_hash,
                    now,
                    now,
                ),
            )
            item_id = int(cursor.lastrowid)
            self._replace_mime_parts(conn, item_id, prepared)
            self._enforce_capacity(conn, tab_id)
            row = conn.execute(
                """
                SELECT
                    i.*,
                    (SELECT COUNT(*) FROM item_images bi WHERE bi.item_id = i.id) AS image_count,
                    (SELECT COUNT(*) FROM item_mime_parts mp WHERE mp.item_id = i.id) AS mime_part_count
                FROM items i
                WHERE i.id = ?
                """,
                (item_id,),
            ).fetchone()
            return self._to_item(row)

    def insert_parsed_item(
        self,
        tab_id: int,
        parsed: ParsedClipboardItem,
        captured_at_ms: int | None = None,
        note: str = "",
    ) -> Optional[ClipItem]:
        prepared_parts = self._prepare_mime_parts(parsed.raw_parts)
        if not prepared_parts:
            return None

        captured_ms = int(captured_at_ms) if captured_at_ms is not None else self._to_epoch_ms(self._now())
        now = datetime.fromtimestamp(captured_ms / 1000.0, tz=timezone.utc).isoformat()
        clean_note = (note or "").strip()
        item_type = str(parsed.item_type)
        base_hash = f"{item_type}:{self._hash_raw_snapshot(prepared_parts)}"
        content_hash = f"{base_hash}#{captured_ms}"
        mime_formats_json = json.dumps(parsed.mime_formats or [], ensure_ascii=False)
        file_paths_json = json.dumps(parsed.file_paths or [], ensure_ascii=False)
        text_value = (parsed.plain_text or parsed.display_text or "").strip()
        display_text = (parsed.display_text or "").strip()
        plain_text = (parsed.plain_text or "").strip()
        html_text = parsed.html_text or ""
        mime_type = (parsed.mime_formats or [None])[0]

        with self._connect() as conn:
            latest_same_payload = conn.execute(
                """
                SELECT
                    i.*,
                    (SELECT COUNT(*) FROM item_images bi WHERE bi.item_id = i.id) AS image_count,
                    (SELECT COUNT(*) FROM item_mime_parts mp WHERE mp.item_id = i.id) AS mime_part_count
                FROM items i
                WHERE i.tab_id = ?
                  AND i.content_type = ?
                  AND (i.content_hash = ? OR i.content_hash LIKE ?)
                ORDER BY i.created_at DESC, i.id DESC
                LIMIT 1
                """,
                (tab_id, item_type, base_hash, f"{base_hash}#%"),
            ).fetchone()
            if latest_same_payload:
                latest_ms = self._to_epoch_ms(latest_same_payload["created_at"])
                if 0 <= captured_ms - latest_ms <= self.RAW_SNAPSHOT_DEDUPE_WINDOW_MS:
                    return self._to_item(latest_same_payload)

            sort_order = self._next_item_sort_order(conn, tab_id)
            cursor = conn.execute(
                """
                INSERT INTO items(
                    tab_id, sort_order, content_type, text, note, image_blob, mime_type, width, height,
                    content_hash, created_at, last_used_at, use_count, display_text, plain_text,
                    html_text, file_paths_json, mime_formats_json, pinned, source_app, thumb_blob
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, 0, ?, ?,
                    ?, ?, ?, 0, ?, ?
                )
                """,
                (
                    tab_id,
                    sort_order,
                    item_type,
                    text_value,
                    clean_note,
                    parsed.image_blob,
                    mime_type,
                    parsed.width,
                    parsed.height,
                    content_hash,
                    now,
                    now,
                    display_text,
                    plain_text,
                    html_text,
                    file_paths_json,
                    mime_formats_json,
                    parsed.source_app,
                    parsed.thumb_blob,
                ),
            )
            item_id = int(cursor.lastrowid)
            self._replace_mime_parts(conn, item_id, prepared_parts)
            self._enforce_capacity(conn, tab_id)
            row = conn.execute(
                """
                SELECT
                    i.*,
                    (SELECT COUNT(*) FROM item_images bi WHERE bi.item_id = i.id) AS image_count,
                    (SELECT COUNT(*) FROM item_mime_parts mp WHERE mp.item_id = i.id) AS mime_part_count
                FROM items i
                WHERE i.id = ?
                """,
                (item_id,),
            ).fetchone()
            return self._to_item(row)

    def create_bundle_item(
        self,
        tab_id: int,
        text: str,
        images: list[dict[str, Any]],
        note: str = "",
    ) -> Optional[ClipItem]:
        clean_text = (text or "").strip()
        clean_note = (note or "").strip()
        prepared = self._prepare_bundle_images(images)
        if not prepared:
            return None
        thumb_blob = self._bundle_thumb_blob(prepared)

        content_hash = self._hash_bundle(clean_text, [img["image_hash"] for img in prepared])
        now = self._now()
        with self._connect() as conn:
            existing_row = conn.execute(
                """
                SELECT
                    i.*,
                    (SELECT COUNT(*) FROM item_images bi WHERE bi.item_id = i.id) AS image_count
                FROM items i
                WHERE i.tab_id = ? AND i.content_type = 'bundle' AND i.content_hash = ?
                """,
                (tab_id, content_hash),
            ).fetchone()
            if existing_row:
                return self._to_item(existing_row)

            sort_order = self._next_item_sort_order(conn, tab_id)
            cursor = conn.execute(
                """
                INSERT INTO items(
                    tab_id, sort_order, content_type, text, note, image_blob, mime_type, width, height,
                    content_hash, created_at, last_used_at, use_count, thumb_blob
                )
                VALUES (?, ?, 'bundle', ?, ?, NULL, NULL, NULL, NULL, ?, ?, ?, 0, ?)
                """,
                (tab_id, sort_order, clean_text, clean_note, content_hash, now, now, thumb_blob),
            )
            item_id = int(cursor.lastrowid)
            self._replace_bundle_images(conn, item_id, prepared)
            self._enforce_capacity(conn, tab_id)
            row = conn.execute(
                """
                SELECT
                    i.*,
                    (SELECT COUNT(*) FROM item_images bi WHERE bi.item_id = i.id) AS image_count
                FROM items i
                WHERE i.id = ?
                """,
                (item_id,),
            ).fetchone()
            return self._to_item(row)

    def update_bundle_item(
        self,
        item_id: int,
        text: str,
        images: list[dict[str, Any]],
        note: str = "",
    ) -> ClipItem:
        clean_text = (text or "").strip()
        clean_note = (note or "").strip()
        prepared = self._prepare_bundle_images(images)
        if not prepared:
            raise ValueError("复合条目至少需要一张图片。")
        thumb_blob = self._bundle_thumb_blob(prepared)
        with self._connect() as conn:
            current = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
            if not current:
                raise ValueError("未找到条目。")
            if current["content_type"] != "bundle":
                raise ValueError("仅支持通过此方法更新复合条目。")

            content_hash = self._hash_bundle(clean_text, [img["image_hash"] for img in prepared])
            duplicate = conn.execute(
                """
                SELECT id FROM items
                WHERE tab_id = ? AND content_type = 'bundle' AND content_hash = ? AND id != ?
                """,
                (current["tab_id"], content_hash, item_id),
            ).fetchone()
            if duplicate:
                raise ValueError("当前标签页已存在相同复合条目。")

            conn.execute(
                """
                UPDATE items
                SET text = ?, note = ?, content_hash = ?, last_used_at = ?, thumb_blob = ?
                WHERE id = ?
                """,
                (clean_text, clean_note, content_hash, self._now(), thumb_blob, item_id),
            )
            self._replace_bundle_images(conn, item_id, prepared)
            row = conn.execute(
                """
                SELECT
                    i.*,
                    (SELECT COUNT(*) FROM item_images bi WHERE bi.item_id = i.id) AS image_count
                FROM items i
                WHERE i.id = ?
                """,
                (item_id,),
            ).fetchone()
            return self._to_item(row)

    def get_bundle_item(self, item_id: int) -> Optional[tuple[ClipItem, list[BundleImage]]]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    i.*,
                    (SELECT COUNT(*) FROM item_images bi WHERE bi.item_id = i.id) AS image_count
                FROM items i
                WHERE i.id = ?
                """,
                (item_id,),
            ).fetchone()
            if not row:
                return None
            item = self._to_item(row)
            if item.content_type != "bundle":
                return None
            image_rows = conn.execute(
                """
                SELECT * FROM item_images
                WHERE item_id = ?
                ORDER BY sort_order, id
                """,
                (item_id,),
            ).fetchall()
        return item, [self._to_bundle_image(img_row) for img_row in image_rows]

    def get_raw_snapshot_parts(self, item_id: int) -> list[MimePart]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM item_mime_parts
                WHERE item_id = ?
                ORDER BY sort_order, id
                """,
                (item_id,),
            ).fetchall()
        return [self._to_mime_part(row) for row in rows]

    def get_item_payload(self, item_id: int) -> Optional[bytes]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT content_type, image_blob FROM items WHERE id = ?",
                (item_id,),
            ).fetchone()
        if not row:
            return None
        if row["content_type"] != "image":
            return None
        return row["image_blob"]

    def get_item_payload_typed(self, item_id: int) -> Optional[dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    id, content_type, text, plain_text, html_text,
                    image_blob, mime_type, width, height,
                    file_paths_json, mime_formats_json
                FROM items
                WHERE id = ?
                """,
                (item_id,),
            ).fetchone()
            if not row:
                return None
            parts_rows = conn.execute(
                """
                SELECT mime_type, payload_blob
                FROM item_mime_parts
                WHERE item_id = ?
                ORDER BY sort_order, id
                """,
                (item_id,),
            ).fetchall()

        file_paths: list[str] = []
        mime_formats: list[str] = []
        try:
            file_paths = json.loads(row["file_paths_json"] or "[]")
        except Exception:
            file_paths = []
        try:
            mime_formats = json.loads(row["mime_formats_json"] or "[]")
        except Exception:
            mime_formats = []

        raw_parts = [
            {"mime_type": str(part_row["mime_type"]), "payload_blob": bytes(part_row["payload_blob"])}
            for part_row in parts_rows
        ]
        return {
            "content_type": str(row["content_type"]),
            "text": str(row["text"] or ""),
            "plain_text": str(row["plain_text"] or row["text"] or ""),
            "html_text": str(row["html_text"] or ""),
            "image_blob": bytes(row["image_blob"]) if row["image_blob"] is not None else None,
            "mime_type": row["mime_type"],
            "width": row["width"],
            "height": row["height"],
            "file_paths": file_paths,
            "mime_formats": mime_formats,
            "raw_parts": raw_parts,
        }

    def update_item_text(self, item_id: int, new_text: str, note: Optional[str] = None) -> ClipItem:
        if new_text.strip() == "":
            raise ValueError("条目文本不能为空。")
        with self._connect() as conn:
            current = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
            if not current:
                raise ValueError("未找到条目。")
            content_type = str(current["content_type"])
            if content_type not in {"text", "html", "url"}:
                raise ValueError("仅支持编辑文本/富文本/链接条目。")
            if content_type == "text":
                content_hash = self._hash_text(new_text)
            else:
                content_hash = f"{content_type}:" + hashlib.sha256(new_text.encode("utf-8")).hexdigest()
            duplicate = conn.execute(
                """
                SELECT id FROM items
                WHERE tab_id = ? AND content_type = ? AND content_hash = ? AND id != ?
                """,
                (current["tab_id"], content_type, content_hash, item_id),
            ).fetchone()
            if duplicate:
                raise ValueError("当前标签页已存在相同内容。")
            now = self._now()
            next_note = current["note"] if note is None else (note or "").strip()
            display_text = " ".join(new_text.split())
            if len(display_text) > 180:
                display_text = display_text[:177] + "..."
            conn.execute(
                """
                UPDATE items
                SET text = ?, note = ?, content_hash = ?, last_used_at = ?,
                    plain_text = ?, display_text = ?
                WHERE id = ?
                """,
                (new_text, next_note, content_hash, now, new_text, display_text, item_id),
            )
            row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
            return self._to_item(row)

    def update_item_image(
        self,
        item_id: int,
        image_bytes: bytes,
        mime_type: str = "image/png",
        width: int | None = None,
        height: int | None = None,
        note: Optional[str] = None,
    ) -> ClipItem:
        if not image_bytes:
            raise ValueError("图片数据不能为空。")
        with self._connect() as conn:
            current = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
            if not current:
                raise ValueError("未找到条目。")
            content_hash = self._hash_image(image_bytes)
            duplicate = conn.execute(
                """
                SELECT id FROM items
                WHERE tab_id = ? AND content_type = 'image' AND content_hash = ? AND id != ?
                """,
                (current["tab_id"], content_hash, item_id),
            ).fetchone()
            if duplicate:
                raise ValueError("当前标签页已存在相同图片。")
            now = self._now()
            next_note = current["note"] if note is None else (note or "").strip()
            conn.execute(
                """
                UPDATE items
                SET content_type = 'image',
                    text = '',
                    note = ?,
                    image_blob = ?,
                    mime_type = ?,
                    width = ?,
                    height = ?,
                    content_hash = ?,
                    last_used_at = ?
                WHERE id = ?
                """,
                (next_note, image_bytes, mime_type, width, height, content_hash, now, item_id),
            )
            row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
            return self._to_item(row)

    def update_item_note(self, item_id: int, note: str) -> ClipItem:
        clean_note = (note or "").strip()
        with self._connect() as conn:
            current = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
            if not current:
                raise ValueError("未找到条目。")
            now = self._now()
            conn.execute(
                """
                UPDATE items
                SET note = ?, last_used_at = ?
                WHERE id = ?
                """,
                (clean_note, now, item_id),
            )
            row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
            return self._to_item(row)

    def get_item_rich_segments(self, item_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT content_type, text FROM items WHERE id = ?",
                (item_id,),
            ).fetchone()
        if not row:
            return []
        if str(row["content_type"] or "") != "rich":
            return []
        return self._deserialize_mixed_segments(str(row["text"] or ""))

    def create_mixed_item(
        self,
        tab_id: int,
        segments: list[dict[str, Any]],
        note: str = "",
    ) -> ClipItem:
        prepared = self._normalize_mixed_segments(segments)
        if not prepared:
            raise ValueError("请至少输入文字或添加图片。")

        plain_text = self._mixed_segments_to_plain_text(prepared)
        has_images = any(seg["type"] == "image" for seg in prepared)
        if not has_images:
            return self.upsert_text_item(tab_id, plain_text)

        serialized = self._serialize_mixed_segments(prepared)
        html_text = self._mixed_segments_to_html(prepared)
        display_text = self._mixed_segments_to_display_text(prepared, plain_text)
        content_hash = "rich:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        thumb_blob = self._first_image_thumb_blob(prepared)
        now = self._now()

        with self._connect() as conn:
            existing_row = conn.execute(
                """
                SELECT
                    i.*,
                    (SELECT COUNT(*) FROM item_images bi WHERE bi.item_id = i.id) AS image_count,
                    (SELECT COUNT(*) FROM item_mime_parts mp WHERE mp.item_id = i.id) AS mime_part_count
                FROM items i
                WHERE i.tab_id = ? AND i.content_type = 'rich' AND i.content_hash = ?
                """,
                (tab_id, content_hash),
            ).fetchone()
            if existing_row:
                return self._to_item(existing_row)

            sort_order = self._next_item_sort_order(conn, tab_id)
            cursor = conn.execute(
                """
                INSERT INTO items(
                    tab_id, sort_order, content_type, text, note, image_blob, mime_type, width, height,
                    content_hash, created_at, last_used_at, use_count, display_text, plain_text,
                    html_text, file_paths_json, mime_formats_json, pinned, source_app, thumb_blob
                )
                VALUES (?, ?, 'rich', ?, ?, NULL, 'text/html', NULL, NULL,
                        ?, ?, ?, 0, ?, ?, ?, '[]', ?, 0, NULL, ?)
                """,
                (
                    tab_id,
                    sort_order,
                    serialized,
                    (note or "").strip(),
                    content_hash,
                    now,
                    now,
                    display_text,
                    plain_text,
                    html_text,
                    json.dumps(["text/html", "text/plain"], ensure_ascii=False),
                    thumb_blob,
                ),
            )
            item_id = int(cursor.lastrowid)
            self._enforce_capacity(conn, tab_id)
            row = conn.execute(
                """
                SELECT
                    i.*,
                    (SELECT COUNT(*) FROM item_images bi WHERE bi.item_id = i.id) AS image_count,
                    (SELECT COUNT(*) FROM item_mime_parts mp WHERE mp.item_id = i.id) AS mime_part_count
                FROM items i
                WHERE i.id = ?
                """,
                (item_id,),
            ).fetchone()
            return self._to_item(row)

    def update_item_mixed(
        self,
        item_id: int,
        segments: list[dict[str, Any]],
        note: Optional[str] = None,
    ) -> ClipItem:
        prepared = self._normalize_mixed_segments(segments)
        if not prepared:
            raise ValueError("请至少输入文字或添加图片。")

        plain_text = self._mixed_segments_to_plain_text(prepared)
        has_images = any(seg["type"] == "image" for seg in prepared)
        display_text = self._mixed_segments_to_display_text(prepared, plain_text)
        now = self._now()

        with self._connect() as conn:
            current = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
            if not current:
                raise ValueError("未找到条目。")
            next_note = current["note"] if note is None else (note or "").strip()
            tab_id = int(current["tab_id"])

            if has_images:
                serialized = self._serialize_mixed_segments(prepared)
                html_text = self._mixed_segments_to_html(prepared)
                content_hash = "rich:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()
                duplicate = conn.execute(
                    """
                    SELECT id FROM items
                    WHERE tab_id = ? AND content_type = 'rich' AND content_hash = ? AND id != ?
                    """,
                    (tab_id, content_hash, item_id),
                ).fetchone()
                if duplicate:
                    raise ValueError("当前标签页已存在相同图文条目。")

                thumb_blob = self._first_image_thumb_blob(prepared)
                conn.execute(
                    """
                    UPDATE items
                    SET content_type = 'rich',
                        text = ?,
                        note = ?,
                        image_blob = NULL,
                        mime_type = 'text/html',
                        width = NULL,
                        height = NULL,
                        content_hash = ?,
                        last_used_at = ?,
                        display_text = ?,
                        plain_text = ?,
                        html_text = ?,
                        file_paths_json = '[]',
                        mime_formats_json = ?,
                        source_app = NULL,
                        thumb_blob = ?
                    WHERE id = ?
                    """,
                    (
                        serialized,
                        next_note,
                        content_hash,
                        now,
                        display_text,
                        plain_text,
                        html_text,
                        json.dumps(["text/html", "text/plain"], ensure_ascii=False),
                        thumb_blob,
                        item_id,
                    ),
                )
            else:
                final_text = plain_text.strip()
                if final_text == "":
                    raise ValueError("文本内容不能为空。")
                content_hash = self._hash_text(final_text)
                duplicate = conn.execute(
                    """
                    SELECT id FROM items
                    WHERE tab_id = ? AND content_type = 'text' AND content_hash = ? AND id != ?
                    """,
                    (tab_id, content_hash, item_id),
                ).fetchone()
                if duplicate:
                    raise ValueError("当前标签页已存在相同文本条目。")

                text_display = " ".join(final_text.split())
                if len(text_display) > 180:
                    text_display = text_display[:177] + "..."
                conn.execute(
                    """
                    UPDATE items
                    SET content_type = 'text',
                        text = ?,
                        note = ?,
                        image_blob = NULL,
                        mime_type = NULL,
                        width = NULL,
                        height = NULL,
                        content_hash = ?,
                        last_used_at = ?,
                        display_text = ?,
                        plain_text = ?,
                        html_text = '',
                        file_paths_json = '[]',
                        mime_formats_json = '[]',
                        source_app = NULL,
                        thumb_blob = NULL
                    WHERE id = ?
                    """,
                    (
                        final_text,
                        next_note,
                        content_hash,
                        now,
                        text_display,
                        final_text,
                        item_id,
                    ),
                )

            # Mixed editing replaces prior specialized payload records.
            conn.execute("DELETE FROM item_images WHERE item_id = ?", (item_id,))
            conn.execute("DELETE FROM item_mime_parts WHERE item_id = ?", (item_id,))
            row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
            return self._to_item(row)

    def delete_item(self, item_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM items WHERE id = ?", (item_id,))

    def clear_items(self, tab_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM items WHERE tab_id = ?", (tab_id,))

    def mark_item_used(self, item_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE items SET use_count = use_count + 1, last_used_at = ? WHERE id = ?",
                (self._now(), item_id),
            )

    def get_setting(self, key: str, conn: Optional[sqlite3.Connection] = None) -> Optional[str]:
        owns_conn = conn is None
        if owns_conn:
            conn = self._open_connection()
        try:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            return None if row is None else row["value"]
        finally:
            if owns_conn:
                conn.close()

    def set_setting(self, key: str, value: str, conn: Optional[sqlite3.Connection] = None) -> None:
        owns_conn = conn is None
        if owns_conn:
            conn = self._open_connection()
        try:
            conn.execute(
                """
                INSERT INTO settings(key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )
            if owns_conn:
                conn.commit()
        finally:
            if owns_conn:
                conn.close()

    def set_tab_capacity(self, tab_id: int, max_items: Optional[int]) -> None:
        """Set a per-tab capacity override; None restores the global default."""
        tab_id = int(tab_id)
        if max_items is None:
            self._tab_capacity_overrides.pop(tab_id, None)
            return
        self._tab_capacity_overrides[tab_id] = max(1, int(max_items))

    def get_tab_capacity(self, tab_id: int) -> int:
        return self._tab_capacity_overrides.get(int(tab_id), self.max_items_per_tab)

    def enforce_tab_capacity_now(self, tab_id: int) -> int:
        """Trim the tab down to its capacity; returns number of deleted items."""
        with self._connect() as conn:
            return self._enforce_capacity(conn, int(tab_id))

    def _enforce_capacity(self, conn: sqlite3.Connection, tab_id: int) -> int:
        limit = self.get_tab_capacity(tab_id)
        count_row = conn.execute("SELECT COUNT(*) AS c FROM items WHERE tab_id = ?", (tab_id,)).fetchone()
        count = int(count_row["c"])
        overflow = count - limit
        if overflow <= 0:
            return 0
        rows = conn.execute(
            """
            SELECT id FROM items
            WHERE tab_id = ? AND pinned = 0
            ORDER BY created_at ASC, id ASC
            LIMIT ?
            """,
            (tab_id, overflow),
        ).fetchall()
        if not rows:
            return 0
        ids = [str(row["id"]) for row in rows]
        conn.execute(f"DELETE FROM items WHERE id IN ({','.join(ids)})")
        return len(ids)

    def _prepare_bundle_images(self, images: list[dict[str, Any]]) -> list[dict[str, Any]]:
        prepared: list[dict[str, Any]] = []
        for idx, image in enumerate(images):
            blob = image.get("image_blob")
            if not isinstance(blob, (bytes, bytearray)) or len(blob) == 0:
                continue
            image_bytes = bytes(blob)
            prepared.append(
                {
                    "sort_order": idx,
                    "image_blob": image_bytes,
                    "mime_type": str(image.get("mime_type") or "image/png"),
                    "width": int(image.get("width") or 0),
                    "height": int(image.get("height") or 0),
                    "image_hash": self._hash_image(image_bytes),
                }
            )
        return prepared

    @staticmethod
    def _prepare_mime_parts(mime_parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        prepared: list[dict[str, Any]] = []
        for idx, part in enumerate(mime_parts):
            mime_type = str(part.get("mime_type") or "").strip()
            payload = part.get("payload_blob")
            if mime_type == "":
                continue
            if not isinstance(payload, (bytes, bytearray)):
                continue
            payload_bytes = bytes(payload)
            prepared.append(
                {
                    "sort_order": idx,
                    "mime_type": mime_type,
                    "payload_blob": payload_bytes,
                    "payload_hash": hashlib.sha256(payload_bytes).hexdigest(),
                }
            )
        return prepared

    @staticmethod
    def _normalize_mixed_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        if not isinstance(segments, list):
            return normalized
        for seg in segments:
            if not isinstance(seg, dict):
                continue
            seg_type = str(seg.get("type") or "").strip().lower()
            if seg_type == "text":
                content = str(seg.get("content") or "")
                if content == "":
                    continue
                normalized.append({"type": "text", "content": content})
                continue
            if seg_type == "image":
                blob = seg.get("image_blob")
                if not isinstance(blob, (bytes, bytearray)) or len(blob) == 0:
                    continue
                image_bytes = bytes(blob)
                normalized.append(
                    {
                        "type": "image",
                        "image_blob": image_bytes,
                        "mime_type": str(seg.get("mime_type") or "image/png"),
                        "width": int(seg.get("width") or 0),
                        "height": int(seg.get("height") or 0),
                        "image_hash": "image:" + hashlib.sha256(image_bytes).hexdigest(),
                    }
                )
        merged: list[dict[str, Any]] = []
        for seg in normalized:
            if (
                merged
                and seg["type"] == "text"
                and merged[-1]["type"] == "text"
            ):
                merged[-1]["content"] = str(merged[-1]["content"]) + str(seg["content"])
            else:
                merged.append(seg)
        return merged

    @staticmethod
    def _mixed_segments_to_plain_text(segments: list[dict[str, Any]]) -> str:
        return "".join(
            str(seg.get("content") or "")
            for seg in segments
            if seg.get("type") == "text"
        )

    @staticmethod
    def _mixed_segments_to_display_text(segments: list[dict[str, Any]], plain_text: str) -> str:
        compact = " ".join((plain_text or "").split()).strip()
        if compact:
            return compact[:177] + "..." if len(compact) > 180 else compact
        for seg in segments:
            if seg.get("type") == "image":
                width = int(seg.get("width") or 0)
                height = int(seg.get("height") or 0)
                return f"[图片] {width}x{height}"
        return "[图文内容]"

    @staticmethod
    def _serialize_mixed_segments(segments: list[dict[str, Any]]) -> str:
        payload: list[dict[str, Any]] = []
        for seg in segments:
            if seg.get("type") == "text":
                payload.append(
                    {
                        "type": "text",
                        "content": str(seg.get("content") or ""),
                    }
                )
                continue
            if seg.get("type") == "image":
                blob = seg.get("image_blob")
                if not isinstance(blob, (bytes, bytearray)):
                    continue
                payload.append(
                    {
                        "type": "image",
                        "mime_type": str(seg.get("mime_type") or "image/png"),
                        "width": int(seg.get("width") or 0),
                        "height": int(seg.get("height") or 0),
                        "data_base64": base64.b64encode(bytes(blob)).decode("ascii"),
                    }
                )
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _deserialize_mixed_segments(serialized: str) -> list[dict[str, Any]]:
        text = (serialized or "").strip()
        if text == "":
            return []
        try:
            raw = json.loads(text)
        except Exception:
            return []
        if not isinstance(raw, list):
            return []
        segments: list[dict[str, Any]] = []
        for seg in raw:
            if not isinstance(seg, dict):
                continue
            seg_type = str(seg.get("type") or "").strip().lower()
            if seg_type == "text":
                content = str(seg.get("content") or "")
                if content:
                    segments.append({"type": "text", "content": content})
                continue
            if seg_type == "image":
                encoded = str(seg.get("data_base64") or "")
                if encoded == "":
                    continue
                try:
                    blob = base64.b64decode(encoded, validate=False)
                except Exception:
                    continue
                if not blob:
                    continue
                segments.append(
                    {
                        "type": "image",
                        "image_blob": blob,
                        "mime_type": str(seg.get("mime_type") or "image/png"),
                        "width": int(seg.get("width") or 0),
                        "height": int(seg.get("height") or 0),
                    }
                )
        return segments

    @staticmethod
    def _mixed_segments_to_html(segments: list[dict[str, Any]]) -> str:
        parts: list[str] = []
        for seg in segments:
            if seg.get("type") == "text":
                content = str(seg.get("content") or "")
                if content:
                    parts.append(html_lib.escape(content).replace("\n", "<br/>"))
                continue
            if seg.get("type") == "image":
                blob = seg.get("image_blob")
                if not isinstance(blob, (bytes, bytearray)):
                    continue
                mime_type = str(seg.get("mime_type") or "image/png")
                encoded = base64.b64encode(bytes(blob)).decode("ascii")
                parts.append(
                    f'<img src="data:{mime_type};base64,{encoded}" style="max-width:100%;"/>'
                )
        body = "".join(parts)
        return f"<html><body>{body}</body></html>"

    def _first_image_thumb_blob(self, segments: list[dict[str, Any]]) -> bytes | None:
        for seg in segments:
            if seg.get("type") != "image":
                continue
            blob = seg.get("image_blob")
            if not isinstance(blob, (bytes, bytearray)):
                continue
            raw = bytes(blob)
            thumb = self._make_thumbnail_blob(raw)
            return thumb or raw
        return None

    def _replace_bundle_images(
        self,
        conn: sqlite3.Connection,
        item_id: int,
        images: list[dict[str, Any]],
    ) -> None:
        conn.execute("DELETE FROM item_images WHERE item_id = ?", (item_id,))
        for img in images:
            conn.execute(
                """
                INSERT INTO item_images(
                    item_id, sort_order, image_blob, mime_type, width, height, image_hash
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    int(img["sort_order"]),
                    img["image_blob"],
                    img["mime_type"],
                    int(img["width"]) if img["width"] is not None else None,
                    int(img["height"]) if img["height"] is not None else None,
                    img["image_hash"],
                ),
            )

    def _replace_mime_parts(
        self,
        conn: sqlite3.Connection,
        item_id: int,
        mime_parts: list[dict[str, Any]],
    ) -> None:
        conn.execute("DELETE FROM item_mime_parts WHERE item_id = ?", (item_id,))
        for part in mime_parts:
            conn.execute(
                """
                INSERT INTO item_mime_parts(
                    item_id, sort_order, mime_type, payload_blob, payload_hash
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    int(part["sort_order"]),
                    part["mime_type"],
                    part["payload_blob"],
                    part["payload_hash"],
                ),
            )

    def _serialize_item_for_export(
        self,
        conn: sqlite3.Connection,
        zf: zipfile.ZipFile,
        binary_refs: dict[str, str],
        item_row: sqlite3.Row,
    ) -> dict[str, Any]:
        item_id = int(item_row["id"])
        file_paths = self._json_to_list(item_row["file_paths_json"] if "file_paths_json" in item_row.keys() else "[]")
        mime_formats = self._json_to_list(
            item_row["mime_formats_json"] if "mime_formats_json" in item_row.keys() else "[]"
        )
        payload: dict[str, Any] = {
            "content_type": str(item_row["content_type"]),
            "text": str(item_row["text"] or ""),
            "note": str(item_row["note"] or ""),
            "mime_type": item_row["mime_type"],
            "width": item_row["width"],
            "height": item_row["height"],
            "content_hash": str(item_row["content_hash"] or ""),
            "created_at": str(item_row["created_at"] or ""),
            "last_used_at": str(item_row["last_used_at"] or ""),
            "use_count": int(item_row["use_count"] or 0),
            "display_text": str(item_row["display_text"] or ""),
            "plain_text": str(item_row["plain_text"] or ""),
            "html_text": str(item_row["html_text"] or ""),
            "file_paths": file_paths,
            "mime_formats": mime_formats,
            "pinned": bool(item_row["pinned"] if "pinned" in item_row.keys() else 0),
            "source_app": item_row["source_app"] if "source_app" in item_row.keys() else None,
            "bundle_images": [],
            "raw_parts": [],
        }

        image_blob = item_row["image_blob"] if "image_blob" in item_row.keys() else None
        if image_blob is not None:
            payload["image_blob_ref"] = self._write_blob_to_zip(
                zf, binary_refs, bytes(image_blob), "image"
            )
        thumb_blob = item_row["thumb_blob"] if "thumb_blob" in item_row.keys() else None
        if thumb_blob is not None:
            payload["thumb_blob_ref"] = self._write_blob_to_zip(
                zf, binary_refs, bytes(thumb_blob), "thumb"
            )

        bundle_rows = conn.execute(
            """
            SELECT sort_order, image_blob, mime_type, width, height, image_hash
            FROM item_images
            WHERE item_id = ?
            ORDER BY sort_order, id
            """,
            (item_id,),
        ).fetchall()
        for bundle_row in bundle_rows:
            blob_ref = self._write_blob_to_zip(
                zf, binary_refs, bytes(bundle_row["image_blob"]), "bundle_image"
            )
            payload["bundle_images"].append(
                {
                    "sort_order": int(bundle_row["sort_order"]),
                    "blob_ref": blob_ref,
                    "mime_type": bundle_row["mime_type"],
                    "width": bundle_row["width"],
                    "height": bundle_row["height"],
                    "image_hash": str(bundle_row["image_hash"] or ""),
                }
            )

        mime_rows = conn.execute(
            """
            SELECT sort_order, mime_type, payload_blob, payload_hash
            FROM item_mime_parts
            WHERE item_id = ?
            ORDER BY sort_order, id
            """,
            (item_id,),
        ).fetchall()
        for mime_row in mime_rows:
            blob_ref = self._write_blob_to_zip(
                zf, binary_refs, bytes(mime_row["payload_blob"]), "mime_part"
            )
            payload["raw_parts"].append(
                {
                    "sort_order": int(mime_row["sort_order"]),
                    "mime_type": str(mime_row["mime_type"]),
                    "blob_ref": blob_ref,
                    "payload_hash": str(mime_row["payload_hash"] or ""),
                }
            )
        return payload

    def _read_package_manifest(self, path: str) -> dict[str, Any]:
        package_path = Path(path).expanduser()
        if not package_path.exists():
            raise ValueError("导入包不存在。")
        try:
            with zipfile.ZipFile(package_path, "r") as zf:
                manifest_bytes = zf.read("manifest.json")
        except KeyError as exc:
            raise ValueError("导入包缺少 manifest.json。") from exc
        except zipfile.BadZipFile as exc:
            raise ValueError("导入包不是有效的压缩文件。") from exc

        try:
            manifest = json.loads(manifest_bytes.decode("utf-8"))
        except Exception as exc:
            raise ValueError("导入清单文件解析失败。") from exc
        if not isinstance(manifest, dict):
            raise ValueError("导入清单文件格式错误。")
        if manifest.get("format") not in {"clipnest-package", "fluxclip-package"}:
            raise ValueError("不支持的导入包格式。")
        if int(manifest.get("version") or 0) > self.PACKAGE_VERSION:
            raise ValueError("导入包版本过高，请升级程序后重试。")
        return manifest

    @staticmethod
    def _write_blob_to_zip(
        zf: zipfile.ZipFile,
        binary_refs: dict[str, str],
        payload: bytes,
        prefix: str,
    ) -> str:
        payload_hash = hashlib.sha256(payload).hexdigest()
        existing = binary_refs.get(payload_hash)
        if existing:
            return existing
        ref = f"binaries/{prefix}_{payload_hash}.bin"
        zf.writestr(ref, payload)
        binary_refs[payload_hash] = ref
        return ref

    @staticmethod
    def _read_blob_from_zip(zf: zipfile.ZipFile, ref: Any) -> bytes | None:
        ref_text = str(ref or "").strip()
        if ref_text == "":
            return None
        try:
            return bytes(zf.read(ref_text))
        except KeyError:
            return None

    def _import_item_from_package(
        self,
        conn: sqlite3.Connection,
        zf: zipfile.ZipFile,
        target_tab_id: int,
        item_payload: Any,
    ) -> bool:
        if not isinstance(item_payload, dict):
            return False
        content_type = str(item_payload.get("content_type") or "text")
        text = str(item_payload.get("text") or "")
        note = str(item_payload.get("note") or "").strip()
        created_at = self._normalize_timestamp(item_payload.get("created_at"))
        last_used_at = self._normalize_timestamp(item_payload.get("last_used_at"), default=created_at)
        use_count = max(0, int(item_payload.get("use_count") or 0))
        mime_type = str(item_payload.get("mime_type") or "") or None
        width = self._to_optional_int(item_payload.get("width"))
        height = self._to_optional_int(item_payload.get("height"))
        display_text = str(item_payload.get("display_text") or "")
        plain_text = str(item_payload.get("plain_text") or text)
        html_text = str(item_payload.get("html_text") or "")
        file_paths = item_payload.get("file_paths") if isinstance(item_payload.get("file_paths"), list) else []
        mime_formats = item_payload.get("mime_formats") if isinstance(item_payload.get("mime_formats"), list) else []
        pinned = 1 if bool(item_payload.get("pinned")) else 0
        source_app = item_payload.get("source_app")
        source_app_text = str(source_app) if source_app is not None else None

        if content_type == "text":
            text_value = plain_text if plain_text.strip() else text
            if text_value.strip() == "":
                return False
            content_hash = self._hash_text(text_value)
            existing = conn.execute(
                "SELECT id, note FROM items WHERE tab_id = ? AND content_type = 'text' AND content_hash = ?",
                (target_tab_id, content_hash),
            ).fetchone()
            if existing:
                self._merge_note_if_empty(conn, int(existing["id"]), str(existing["note"] or ""), note)
                return False
            sort_order = self._next_item_sort_order(conn, target_tab_id)
            conn.execute(
                """
                INSERT INTO items(
                    tab_id, sort_order, content_type, text, note, image_blob, mime_type, width, height,
                    content_hash, created_at, last_used_at, use_count,
                    display_text, plain_text, html_text, file_paths_json, mime_formats_json,
                    pinned, source_app, thumb_blob
                )
                VALUES (?, ?, 'text', ?, ?, NULL, NULL, NULL, NULL, ?, ?, ?, ?, ?, ?, '', '[]', '[]', ?, ?, NULL)
                """,
                (
                    target_tab_id,
                    sort_order,
                    text_value,
                    note,
                    content_hash,
                    created_at,
                    last_used_at,
                    use_count,
                    display_text or " ".join(text_value.split()),
                    text_value,
                    pinned,
                    source_app_text,
                ),
            )
            return True

        if content_type == "image":
            image_blob = self._read_blob_from_zip(zf, item_payload.get("image_blob_ref"))
            if not image_blob:
                return False
            content_hash = self._hash_image(image_blob)
            existing = conn.execute(
                "SELECT id, note FROM items WHERE tab_id = ? AND content_type = 'image' AND content_hash = ?",
                (target_tab_id, content_hash),
            ).fetchone()
            if existing:
                self._merge_note_if_empty(conn, int(existing["id"]), str(existing["note"] or ""), note)
                return False
            thumb_blob = self._read_blob_from_zip(zf, item_payload.get("thumb_blob_ref"))
            sort_order = self._next_item_sort_order(conn, target_tab_id)
            conn.execute(
                """
                INSERT INTO items(
                    tab_id, sort_order, content_type, text, note, image_blob, mime_type, width, height,
                    content_hash, created_at, last_used_at, use_count,
                    display_text, plain_text, html_text, file_paths_json, mime_formats_json,
                    pinned, source_app, thumb_blob
                )
                VALUES (?, ?, 'image', '', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', '', '[]', '[]', ?, ?, ?)
                """,
                (
                    target_tab_id,
                    sort_order,
                    note,
                    image_blob,
                    mime_type or "image/png",
                    width,
                    height,
                    content_hash,
                    created_at,
                    last_used_at,
                    use_count,
                    display_text or (f"[图片] {int(width or 0)}x{int(height or 0)}"),
                    pinned,
                    source_app_text,
                    thumb_blob,
                ),
            )
            return True

        if content_type == "bundle":
            bundle_text = text.strip()
            bundle_images_payload = (
                item_payload.get("bundle_images") if isinstance(item_payload.get("bundle_images"), list) else []
            )
            prepared_images: list[dict[str, Any]] = []
            for idx, image_payload in enumerate(bundle_images_payload):
                if not isinstance(image_payload, dict):
                    continue
                image_blob = self._read_blob_from_zip(zf, image_payload.get("blob_ref"))
                if not image_blob:
                    continue
                prepared_images.append(
                    {
                        "sort_order": idx,
                        "image_blob": image_blob,
                        "mime_type": str(image_payload.get("mime_type") or "image/png"),
                        "width": self._to_optional_int(image_payload.get("width")),
                        "height": self._to_optional_int(image_payload.get("height")),
                        "image_hash": str(image_payload.get("image_hash") or self._hash_image(image_blob)),
                    }
                )
            if not prepared_images:
                return False
            content_hash = self._hash_bundle(bundle_text, [img["image_hash"] for img in prepared_images])
            existing = conn.execute(
                "SELECT id, note FROM items WHERE tab_id = ? AND content_type = 'bundle' AND content_hash = ?",
                (target_tab_id, content_hash),
            ).fetchone()
            if existing:
                self._merge_note_if_empty(conn, int(existing["id"]), str(existing["note"] or ""), note)
                return False
            sort_order = self._next_item_sort_order(conn, target_tab_id)
            thumb_blob = self._bundle_thumb_blob(prepared_images)
            cursor = conn.execute(
                """
                INSERT INTO items(
                    tab_id, sort_order, content_type, text, note, image_blob, mime_type, width, height,
                    content_hash, created_at, last_used_at, use_count,
                    display_text, plain_text, html_text, file_paths_json, mime_formats_json,
                    pinned, source_app, thumb_blob
                )
                VALUES (?, ?, 'bundle', ?, ?, NULL, NULL, NULL, NULL, ?, ?, ?, ?, ?, ?, '', '[]', '[]', ?, ?, ?)
                """,
                (
                    target_tab_id,
                    sort_order,
                    bundle_text,
                    note,
                    content_hash,
                    created_at,
                    last_used_at,
                    use_count,
                    display_text or " ".join(bundle_text.split()),
                    plain_text or bundle_text,
                    pinned,
                    source_app_text,
                    thumb_blob,
                ),
            )
            self._replace_bundle_images(conn, int(cursor.lastrowid), prepared_images)
            return True

        raw_parts_payload = item_payload.get("raw_parts") if isinstance(item_payload.get("raw_parts"), list) else []
        prepared_parts: list[dict[str, Any]] = []
        for idx, raw_part in enumerate(raw_parts_payload):
            if not isinstance(raw_part, dict):
                continue
            mime_value = str(raw_part.get("mime_type") or "").strip()
            if mime_value == "":
                continue
            payload_blob = self._read_blob_from_zip(zf, raw_part.get("blob_ref"))
            if payload_blob is None:
                continue
            prepared_parts.append(
                {
                    "sort_order": idx,
                    "mime_type": mime_value,
                    "payload_blob": payload_blob,
                    "payload_hash": hashlib.sha256(payload_blob).hexdigest(),
                }
            )

        if not prepared_parts and content_type in {"html", "url", "files"}:
            fallback = (plain_text or text).strip()
            if fallback:
                fallback_blob = fallback.encode("utf-8")
                prepared_parts.append(
                    {
                        "sort_order": 0,
                        "mime_type": "text/plain",
                        "payload_blob": fallback_blob,
                        "payload_hash": hashlib.sha256(fallback_blob).hexdigest(),
                    }
                )
        if not prepared_parts and content_type in {"special", "raw_snapshot"}:
            return False

        content_hash = str(item_payload.get("content_hash") or "").strip()
        if content_hash == "":
            if content_type in {"special", "raw_snapshot", "html", "url", "files"}:
                base_hash = f"{content_type}:{self._hash_raw_snapshot(prepared_parts)}"
                content_hash = f"{base_hash}#{self._to_epoch_ms(created_at)}"
            else:
                content_hash = f"{content_type}:{hashlib.sha256((plain_text or text).encode('utf-8')).hexdigest()}"
        existing = conn.execute(
            "SELECT id, note FROM items WHERE tab_id = ? AND content_type = ? AND content_hash = ?",
            (target_tab_id, content_type, content_hash),
        ).fetchone()
        if existing:
            self._merge_note_if_empty(conn, int(existing["id"]), str(existing["note"] or ""), note)
            return False

        sort_order = self._next_item_sort_order(conn, target_tab_id)
        cursor = conn.execute(
            """
            INSERT INTO items(
                tab_id, sort_order, content_type, text, note, image_blob, mime_type, width, height,
                content_hash, created_at, last_used_at, use_count,
                display_text, plain_text, html_text, file_paths_json, mime_formats_json,
                pinned, source_app, thumb_blob
            )
            VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                target_tab_id,
                sort_order,
                content_type,
                text,
                note,
                mime_type,
                width,
                height,
                content_hash,
                created_at,
                last_used_at,
                use_count,
                display_text,
                plain_text,
                html_text,
                json.dumps(file_paths, ensure_ascii=False),
                json.dumps(mime_formats, ensure_ascii=False),
                pinned,
                source_app_text,
            ),
        )
        item_id = int(cursor.lastrowid)
        if prepared_parts:
            self._replace_mime_parts(conn, item_id, prepared_parts)
        return True

    def _merge_note_if_empty(
        self,
        conn: sqlite3.Connection,
        item_id: int,
        current_note: str,
        incoming_note: str,
    ) -> None:
        if incoming_note == "" or current_note.strip() != "":
            return
        conn.execute("UPDATE items SET note = ? WHERE id = ?", (incoming_note, item_id))

    def _normalize_timestamp(self, raw_value: Any, default: Optional[str] = None) -> str:
        if isinstance(raw_value, str):
            text = raw_value.strip()
            if text:
                try:
                    datetime.fromisoformat(text)
                    return text
                except ValueError:
                    pass
        return default or self._now()

    @staticmethod
    def _to_optional_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _escape_like(value: str) -> str:
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    @staticmethod
    def _json_to_list(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(v) for v in value]
        if not isinstance(value, str):
            return []
        try:
            parsed = json.loads(value)
        except Exception:
            return []
        if not isinstance(parsed, list):
            return []
        return [str(v) for v in parsed]

    def _ensure_items_columns(self, conn: sqlite3.Connection) -> None:
        info_rows = conn.execute("PRAGMA table_info(items)").fetchall()
        existing_columns = {row["name"] for row in info_rows}
        migrations = [
            ("sort_order", "INTEGER NOT NULL DEFAULT 0"),
            ("content_type", "TEXT NOT NULL DEFAULT 'text'"),
            ("note", "TEXT NOT NULL DEFAULT ''"),
            ("image_blob", "BLOB"),
            ("mime_type", "TEXT"),
            ("width", "INTEGER"),
            ("height", "INTEGER"),
            ("display_text", "TEXT NOT NULL DEFAULT ''"),
            ("plain_text", "TEXT NOT NULL DEFAULT ''"),
            ("html_text", "TEXT NOT NULL DEFAULT ''"),
            ("file_paths_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("mime_formats_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("pinned", "INTEGER NOT NULL DEFAULT 0"),
            ("source_app", "TEXT"),
            ("thumb_blob", "BLOB"),
        ]
        for column_name, ddl in migrations:
            if column_name not in existing_columns:
                conn.execute(f"ALTER TABLE items ADD COLUMN {column_name} {ddl}")
