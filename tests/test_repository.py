from __future__ import annotations

import json
import unittest
from pathlib import Path
import uuid
import zipfile

from clipboard_manager.models import ParsedClipboardItem
from clipboard_manager.repository import ClipRepository


def _tab_ids(repo: ClipRepository) -> list[int]:
    return [tab.id for tab in repo.list_tabs()]


class ClipRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        base_dir = Path(__file__).resolve().parent / ".tmp"
        base_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = base_dir / f"repo_{uuid.uuid4().hex}.db"

    def tearDown(self) -> None:
        if self.db_path.exists():
            try:
                self.db_path.unlink(missing_ok=True)
            except PermissionError:
                pass

    def test_dedupe_within_same_tab(self) -> None:
        repo = ClipRepository(self.db_path, max_items_per_tab=500)
        tab_id = _tab_ids(repo)[0]

        first = repo.upsert_item(tab_id, "hello world")
        second = repo.upsert_item(tab_id, "hello world")

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(first.id, second.id)
        self.assertEqual(len(repo.list_items(tab_id)), 1)

    def test_cross_tab_allows_duplicate_text(self) -> None:
        repo = ClipRepository(self.db_path, max_items_per_tab=500)
        tab_ids = _tab_ids(repo)
        first_tab = tab_ids[0]
        second_tab = tab_ids[1]

        one = repo.upsert_item(first_tab, "same-content")
        two = repo.upsert_item(second_tab, "same-content")

        self.assertIsNotNone(one)
        self.assertIsNotNone(two)
        self.assertNotEqual(one.id, two.id)
        self.assertEqual(len(repo.list_items(first_tab)), 1)
        self.assertEqual(len(repo.list_items(second_tab)), 1)

    def test_capacity_evicts_oldest(self) -> None:
        repo = ClipRepository(self.db_path, max_items_per_tab=3)
        tab_id = _tab_ids(repo)[0]

        repo.upsert_item(tab_id, "1")
        repo.upsert_item(tab_id, "2")
        repo.upsert_item(tab_id, "3")
        repo.upsert_item(tab_id, "4")

        texts = [item.text for item in repo.list_items(tab_id)]
        self.assertEqual(texts, ["4", "3", "2"])

    def test_delete_tab_cascades_items(self) -> None:
        repo = ClipRepository(self.db_path, max_items_per_tab=500)
        target_tab = _tab_ids(repo)[0]

        repo.upsert_item(target_tab, "to-be-deleted")
        self.assertEqual(repo.tab_item_count(target_tab), 1)

        repo.delete_tab(target_tab)
        self.assertTrue(all(tab.id != target_tab for tab in repo.list_tabs()))

    def test_reorder_tabs_persists_new_order(self) -> None:
        repo = ClipRepository(self.db_path, max_items_per_tab=500)
        original_ids = _tab_ids(repo)
        new_order = list(reversed(original_ids))

        repo.reorder_tabs(new_order)
        tabs = repo.list_tabs()

        self.assertEqual([tab.id for tab in tabs], new_order)
        self.assertEqual([tab.sort_order for tab in tabs], list(range(len(new_order))))

    def test_reorder_tabs_rejects_missing_id_without_mutation(self) -> None:
        repo = ClipRepository(self.db_path, max_items_per_tab=500)
        original_ids = _tab_ids(repo)

        with self.assertRaises(ValueError):
            repo.reorder_tabs(original_ids[:-1])

        self.assertEqual(_tab_ids(repo), original_ids)

    def test_reorder_tabs_rejects_duplicate_or_unknown_id(self) -> None:
        repo = ClipRepository(self.db_path, max_items_per_tab=500)
        original_ids = _tab_ids(repo)
        duplicate_order = list(original_ids)
        duplicate_order[-1] = duplicate_order[0]

        with self.assertRaises(ValueError):
            repo.reorder_tabs(duplicate_order)
        self.assertEqual(_tab_ids(repo), original_ids)

        unknown_order = list(original_ids)
        unknown_order[-1] = 99999999
        with self.assertRaises(ValueError):
            repo.reorder_tabs(unknown_order)
        self.assertEqual(_tab_ids(repo), original_ids)

    def test_reorder_items_persists_new_order(self) -> None:
        repo = ClipRepository(self.db_path, max_items_per_tab=500)
        tab_id = _tab_ids(repo)[0]
        first = repo.upsert_text_item(tab_id, "A")
        second = repo.upsert_text_item(tab_id, "B")
        third = repo.upsert_text_item(tab_id, "C")
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertIsNotNone(third)
        assert first is not None and second is not None and third is not None

        original_order = [item.id for item in repo.list_items(tab_id)]
        self.assertEqual(original_order, [third.id, second.id, first.id])

        new_order = [second.id, first.id, third.id]
        repo.reorder_items(tab_id, new_order)
        reloaded = [item.id for item in repo.list_items(tab_id)]
        self.assertEqual(reloaded, new_order)
        self.assertEqual(
            [item.sort_order for item in repo.list_items(tab_id)],
            list(range(len(new_order))),
        )

    def test_reorder_items_rejects_invalid_order_without_mutation(self) -> None:
        repo = ClipRepository(self.db_path, max_items_per_tab=500)
        tab_ids = _tab_ids(repo)
        tab_a, tab_b = tab_ids[0], tab_ids[1]
        a1 = repo.upsert_text_item(tab_a, "A1")
        a2 = repo.upsert_text_item(tab_a, "A2")
        b1 = repo.upsert_text_item(tab_b, "B1")
        self.assertIsNotNone(a1)
        self.assertIsNotNone(a2)
        self.assertIsNotNone(b1)
        assert a1 is not None and a2 is not None and b1 is not None

        original_order = [item.id for item in repo.list_items(tab_a)]
        with self.assertRaises(ValueError):
            repo.reorder_items(tab_a, [a1.id, a1.id])
        self.assertEqual([item.id for item in repo.list_items(tab_a)], original_order)

        with self.assertRaises(ValueError):
            repo.reorder_items(tab_a, [a1.id])
        self.assertEqual([item.id for item in repo.list_items(tab_a)], original_order)

        with self.assertRaises(ValueError):
            repo.reorder_items(tab_a, [a1.id, b1.id])
        self.assertEqual([item.id for item in repo.list_items(tab_a)], original_order)

    def test_new_item_stays_on_top_after_manual_reorder(self) -> None:
        repo = ClipRepository(self.db_path, max_items_per_tab=500)
        tab_id = _tab_ids(repo)[0]
        one = repo.upsert_text_item(tab_id, "one")
        two = repo.upsert_text_item(tab_id, "two")
        three = repo.upsert_text_item(tab_id, "three")
        self.assertIsNotNone(one)
        self.assertIsNotNone(two)
        self.assertIsNotNone(three)
        assert one is not None and two is not None and three is not None

        repo.reorder_items(tab_id, [one.id, two.id, three.id])
        newest = repo.upsert_text_item(tab_id, "new-top")
        self.assertIsNotNone(newest)
        assert newest is not None
        items = repo.list_items(tab_id)
        self.assertEqual(items[0].id, newest.id)

    def test_move_items_to_other_tab_persists(self) -> None:
        repo = ClipRepository(self.db_path, max_items_per_tab=500)
        tab_a, tab_b = _tab_ids(repo)[:2]
        item = repo.upsert_text_item(tab_a, "move-me")
        self.assertIsNotNone(item)
        assert item is not None

        result = repo.move_items_to_tab([item.id], tab_b)
        self.assertEqual(result.moved_count, 1)
        self.assertEqual(result.already_in_target_count, 0)
        self.assertEqual(len(repo.list_items(tab_a)), 0)
        moved_items = repo.list_items(tab_b)
        self.assertTrue(any(it.id == item.id for it in moved_items))

    def test_move_items_to_same_tab_only_counts_already(self) -> None:
        repo = ClipRepository(self.db_path, max_items_per_tab=500)
        tab_a = _tab_ids(repo)[0]
        item = repo.upsert_text_item(tab_a, "same-tab")
        self.assertIsNotNone(item)
        assert item is not None

        result = repo.move_items_to_tab([item.id], tab_a)
        self.assertEqual(result.moved_count, 0)
        self.assertEqual(result.already_in_target_count, 1)
        self.assertEqual(len(repo.list_items(tab_a)), 1)

    def test_move_items_rejects_unknown_target_tab(self) -> None:
        repo = ClipRepository(self.db_path, max_items_per_tab=500)
        tab_a = _tab_ids(repo)[0]
        item = repo.upsert_text_item(tab_a, "unknown-target")
        self.assertIsNotNone(item)
        assert item is not None

        with self.assertRaises(ValueError):
            repo.move_items_to_tab([item.id], 99999999)

    def test_move_items_handles_content_hash_conflict_without_loss(self) -> None:
        repo = ClipRepository(self.db_path, max_items_per_tab=500)
        tab_a, tab_b = _tab_ids(repo)[:2]
        source_item = repo.upsert_text_item(tab_a, "dup-content")
        target_item = repo.upsert_text_item(tab_b, "dup-content")
        self.assertIsNotNone(source_item)
        self.assertIsNotNone(target_item)
        assert source_item is not None and target_item is not None

        result = repo.move_items_to_tab([source_item.id], tab_b)
        self.assertEqual(result.moved_count, 1)
        items_in_target = repo.list_items(tab_b)
        self.assertEqual(len(items_in_target), 2)
        moved = next(it for it in items_in_target if it.id == source_item.id)
        self.assertTrue(moved.content_hash.startswith(target_item.content_hash))

    def test_export_tabs_and_inspect_import_package(self) -> None:
        repo = ClipRepository(self.db_path, max_items_per_tab=500)
        tab_id = _tab_ids(repo)[0]
        repo.upsert_text_item(tab_id, "导出测试文本")
        repo.upsert_image_item(tab_id, b"fake-image-bytes", "image/png", 16, 16)

        pkg_path = self.db_path.with_suffix(".fluxpkg")
        result = repo.export_tabs([tab_id], str(pkg_path))
        self.assertTrue(pkg_path.exists())
        self.assertEqual(result.tab_count, 1)
        self.assertGreaterEqual(result.item_count, 2)

        with zipfile.ZipFile(pkg_path, "r") as zf:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        self.assertEqual(manifest.get("format"), "clipnest-package")

        summary = repo.inspect_import_package(str(pkg_path))
        self.assertEqual(summary.version, ClipRepository.PACKAGE_VERSION)
        self.assertEqual(len(summary.tab_summaries), 1)
        self.assertEqual(summary.tab_summaries[0].item_count, result.item_count)

        pkg_path.unlink(missing_ok=True)

    def test_import_tabs_merge_same_name_and_dedupe(self) -> None:
        source_repo = ClipRepository(self.db_path, max_items_per_tab=500)
        source_tab_id = _tab_ids(source_repo)[0]
        source_tab_name = source_repo.list_tabs()[0].name
        source_repo.upsert_text_item(source_tab_id, "同名合并文本")
        source_repo.upsert_image_item(source_tab_id, b"img-import-1", "image/png", 32, 32)
        pkg_path = self.db_path.with_suffix(".fluxpkg")
        source_repo.export_tabs([source_tab_id], str(pkg_path))

        target_db_path = self.db_path.with_name(f"repo_target_{uuid.uuid4().hex}.db")
        target_repo = ClipRepository(target_db_path, max_items_per_tab=500)
        target_tab_id = next(tab.id for tab in target_repo.list_tabs() if tab.name == source_tab_name)
        baseline_count = len(target_repo.list_items(target_tab_id))

        summary = target_repo.inspect_import_package(str(pkg_path))
        selected_ids = [summary.tab_summaries[0].package_tab_id]
        first = target_repo.import_tabs(str(pkg_path), selected_ids, conflict_mode="merge")
        after_first = len(target_repo.list_items(target_tab_id))
        self.assertGreaterEqual(first.imported_items, 2)
        self.assertEqual(after_first, baseline_count + first.imported_items)

        second = target_repo.import_tabs(str(pkg_path), selected_ids, conflict_mode="merge")
        after_second = len(target_repo.list_items(target_tab_id))
        self.assertEqual(after_second, after_first)
        self.assertGreaterEqual(second.skipped_items, 2)

        pkg_path.unlink(missing_ok=True)
        target_db_path.unlink(missing_ok=True)

    def test_legacy_package_format_still_imports(self) -> None:
        source_repo = ClipRepository(self.db_path, max_items_per_tab=500)
        source_tab_id = _tab_ids(source_repo)[0]
        source_repo.upsert_text_item(source_tab_id, "旧格式导入兼容")
        pkg_path = self.db_path.with_suffix(".fluxpkg")
        legacy_pkg_path = self.db_path.with_name(f"{self.db_path.stem}_legacy.fluxpkg")
        source_repo.export_tabs([source_tab_id], str(pkg_path))

        with zipfile.ZipFile(pkg_path, "r") as source_zf:
            entries = [(info.filename, source_zf.read(info.filename)) for info in source_zf.infolist()]
        manifest = json.loads(dict(entries)["manifest.json"].decode("utf-8"))
        manifest["format"] = "fluxclip-package"
        with zipfile.ZipFile(legacy_pkg_path, "w", compression=zipfile.ZIP_DEFLATED) as legacy_zf:
            for name, data in entries:
                if name == "manifest.json":
                    data = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
                legacy_zf.writestr(name, data)

        summary = source_repo.inspect_import_package(str(legacy_pkg_path))
        self.assertEqual(summary.version, ClipRepository.PACKAGE_VERSION)
        self.assertEqual(len(summary.tab_summaries), 1)

        pkg_path.unlink(missing_ok=True)
        legacy_pkg_path.unlink(missing_ok=True)

    def test_image_dedupe_within_same_tab(self) -> None:
        repo = ClipRepository(self.db_path, max_items_per_tab=500)
        tab_id = _tab_ids(repo)[0]
        image_payload = b"fake-png-image-data-123"

        first = repo.upsert_image_item(tab_id, image_payload, "image/png", 32, 32)
        second = repo.upsert_image_item(tab_id, image_payload, "image/png", 32, 32)

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(first.id, second.id)
        self.assertEqual(first.content_type, "image")
        self.assertEqual(len(repo.list_items(tab_id)), 1)

    def test_image_and_text_recorded_together(self) -> None:
        repo = ClipRepository(self.db_path, max_items_per_tab=500)
        tab_id = _tab_ids(repo)[0]
        image_payload = b"fake-png-image-data-456"

        img_item = repo.upsert_image_item(tab_id, image_payload, "image/png", 64, 64)
        txt_item = repo.upsert_text_item(tab_id, "https://example.com/image.png")

        self.assertIsNotNone(img_item)
        self.assertIsNotNone(txt_item)
        self.assertNotEqual(img_item.id, txt_item.id)
        item_types = {it.content_type for it in repo.list_items(tab_id)}
        self.assertIn("image", item_types)
        self.assertIn("text", item_types)

    def test_get_item_payload_for_image(self) -> None:
        repo = ClipRepository(self.db_path, max_items_per_tab=500)
        tab_id = _tab_ids(repo)[0]
        image_payload = b"fake-png-image-data-789"

        item = repo.upsert_image_item(tab_id, image_payload, "image/png", 128, 72)
        self.assertIsNotNone(item)
        payload = repo.get_item_payload(item.id)
        self.assertEqual(payload, image_payload)

    def test_update_text_item_to_image(self) -> None:
        repo = ClipRepository(self.db_path, max_items_per_tab=500)
        tab_id = _tab_ids(repo)[0]
        text_item = repo.upsert_text_item(tab_id, "old text")
        self.assertIsNotNone(text_item)

        payload = b"fake-png-image-data-999"
        updated = repo.update_item_image(text_item.id, payload, "image/png", 40, 20)
        self.assertEqual(updated.content_type, "image")
        self.assertEqual(repo.get_item_payload(updated.id), payload)

    def test_create_and_read_bundle_item(self) -> None:
        repo = ClipRepository(self.db_path, max_items_per_tab=500)
        tab_id = _tab_ids(repo)[0]
        images = [
            {"image_blob": b"img-a", "mime_type": "image/png", "width": 10, "height": 20},
            {"image_blob": b"img-b", "mime_type": "image/png", "width": 30, "height": 40},
        ]
        item = repo.create_bundle_item(tab_id, "bundle-text", images)
        self.assertIsNotNone(item)
        self.assertEqual(item.content_type, "bundle")
        self.assertEqual(item.image_count, 2)
        self.assertIsNotNone(item.thumb_blob)

        loaded = repo.get_bundle_item(item.id)
        self.assertIsNotNone(loaded)
        loaded_item, loaded_images = loaded
        self.assertEqual(loaded_item.text, "bundle-text")
        self.assertEqual(len(loaded_images), 2)
        self.assertEqual(loaded_images[0].image_blob, b"img-a")
        self.assertEqual(loaded_images[1].image_blob, b"img-b")

    def test_bundle_dedupe_same_content(self) -> None:
        repo = ClipRepository(self.db_path, max_items_per_tab=500)
        tab_id = _tab_ids(repo)[0]
        images = [{"image_blob": b"same", "mime_type": "image/png", "width": 1, "height": 1}]
        first = repo.create_bundle_item(tab_id, "same-text", images)
        second = repo.create_bundle_item(tab_id, "same-text", images)
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(first.id, second.id)

    def test_update_bundle_item(self) -> None:
        repo = ClipRepository(self.db_path, max_items_per_tab=500)
        tab_id = _tab_ids(repo)[0]
        item = repo.create_bundle_item(
            tab_id,
            "old",
            [{"image_blob": b"old-img", "mime_type": "image/png", "width": 10, "height": 10}],
        )
        self.assertIsNotNone(item)
        updated = repo.update_bundle_item(
            item.id,
            "new-text",
            [{"image_blob": b"new-img", "mime_type": "image/png", "width": 20, "height": 30}],
        )
        self.assertEqual(updated.content_type, "bundle")
        self.assertEqual(updated.image_count, 1)
        self.assertIsNotNone(updated.thumb_blob)
        loaded = repo.get_bundle_item(item.id)
        self.assertIsNotNone(loaded)
        loaded_item, loaded_images = loaded
        self.assertEqual(loaded_item.text, "new-text")
        self.assertEqual(loaded_images[0].image_blob, b"new-img")

    def test_capture_tab_setting_initialized(self) -> None:
        repo = ClipRepository(self.db_path, max_items_per_tab=500)
        first_tab_id = _tab_ids(repo)[0]
        capture_tab_id = repo.get_setting("capture_tab_id")
        self.assertEqual(capture_tab_id, str(first_tab_id))

    def test_note_is_persisted_and_editable(self) -> None:
        repo = ClipRepository(self.db_path, max_items_per_tab=500)
        tab_id = _tab_ids(repo)[0]
        text_item = repo.upsert_text_item(tab_id, "hello")
        self.assertIsNotNone(text_item)

        edited = repo.update_item_text(text_item.id, "hello edited", note="我的备注")
        self.assertEqual(edited.note, "我的备注")

        bundle_item = repo.create_bundle_item(
            tab_id,
            "bundle",
            [{"image_blob": b"img", "mime_type": "image/png", "width": 1, "height": 1}],
            note="图文备注",
        )
        self.assertIsNotNone(bundle_item)
        self.assertEqual(bundle_item.note, "图文备注")

        loaded = repo.get_bundle_item(bundle_item.id)
        self.assertIsNotNone(loaded)
        loaded_item, _ = loaded
        self.assertEqual(loaded_item.note, "图文备注")

    def test_bundle_dedupe_ignores_note(self) -> None:
        repo = ClipRepository(self.db_path, max_items_per_tab=500)
        tab_id = _tab_ids(repo)[0]
        images = [{"image_blob": b"same", "mime_type": "image/png", "width": 1, "height": 1}]
        first = repo.create_bundle_item(tab_id, "same-text", images, note="备注A")
        second = repo.create_bundle_item(tab_id, "same-text", images, note="备注B")
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(first.id, second.id)
        self.assertEqual(second.note, "备注A")

    def test_raw_snapshot_upsert_and_parts(self) -> None:
        repo = ClipRepository(self.db_path, max_items_per_tab=500)
        tab_id = _tab_ids(repo)[0]
        parts = [
            {"mime_type": "text/plain", "payload_blob": b"hello"},
            {"mime_type": "text/html", "payload_blob": b"<b>hello</b>"},
        ]
        item = repo.upsert_raw_snapshot_item(tab_id, parts, "hello")
        self.assertIsNotNone(item)
        self.assertEqual(item.content_type, "raw_snapshot")
        loaded_parts = repo.get_raw_snapshot_parts(item.id)
        self.assertEqual(len(loaded_parts), 2)
        self.assertEqual(loaded_parts[0].mime_type, "text/plain")
        self.assertEqual(loaded_parts[1].mime_type, "text/html")

    def test_raw_snapshot_dedupe_same_payload(self) -> None:
        repo = ClipRepository(self.db_path, max_items_per_tab=500)
        tab_id = _tab_ids(repo)[0]
        parts_a = [
            {"mime_type": "text/plain", "payload_blob": b"abc"},
            {"mime_type": "text/html", "payload_blob": b"<p>abc</p>"},
        ]
        parts_b = [
            {"mime_type": "text/html", "payload_blob": b"<p>abc</p>"},
            {"mime_type": "text/plain", "payload_blob": b"abc"},
        ]
        first = repo.upsert_raw_snapshot_item(tab_id, parts_a, "abc", captured_at_ms=1000)
        second = repo.upsert_raw_snapshot_item(tab_id, parts_b, "abc", captured_at_ms=1500)
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(first.id, second.id)

    def test_raw_snapshot_within_one_second_keeps_single_item(self) -> None:
        repo = ClipRepository(self.db_path, max_items_per_tab=500)
        tab_id = _tab_ids(repo)[0]
        parts = [{"mime_type": "text/plain", "payload_blob": b"same"}]

        first = repo.upsert_raw_snapshot_item(tab_id, parts, "same", captured_at_ms=1000)
        second = repo.upsert_raw_snapshot_item(tab_id, parts, "same", captured_at_ms=1800)

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(first.id, second.id)
        self.assertEqual(len(repo.list_items(tab_id)), 1)

    def test_raw_snapshot_after_one_second_creates_new_item(self) -> None:
        repo = ClipRepository(self.db_path, max_items_per_tab=500)
        tab_id = _tab_ids(repo)[0]
        parts = [{"mime_type": "text/plain", "payload_blob": b"same"}]

        first = repo.upsert_raw_snapshot_item(tab_id, parts, "same", captured_at_ms=1000)
        second = repo.upsert_raw_snapshot_item(tab_id, parts, "same", captured_at_ms=2201)

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(len(repo.list_items(tab_id)), 2)

    def test_insert_parsed_item_files(self) -> None:
        repo = ClipRepository(self.db_path, max_items_per_tab=500)
        tab_id = _tab_ids(repo)[0]
        parsed = ParsedClipboardItem(
            item_type="files",
            display_text="a.txt 等 2 个文件",
            plain_text=r"C:\tmp\a.txt\nC:\tmp\b.txt",
            html_text="",
            image_blob=None,
            thumb_blob=None,
            width=None,
            height=None,
            file_paths=[r"C:\tmp\a.txt", r"C:\tmp\b.txt"],
            mime_formats=["text/uri-list"],
            raw_parts=[{"mime_type": "text/uri-list", "payload_blob": b"file:///C:/tmp/a.txt"}],
        )
        item = repo.insert_parsed_item(tab_id, parsed, captured_at_ms=1000)
        self.assertIsNotNone(item)
        assert item is not None
        self.assertEqual(item.content_type, "files")
        self.assertEqual(item.file_paths, [r"C:\tmp\a.txt", r"C:\tmp\b.txt"])
        typed_payload = repo.get_item_payload_typed(item.id)
        self.assertIsNotNone(typed_payload)
        assert typed_payload is not None
        self.assertEqual(typed_payload["content_type"], "files")
        self.assertEqual(len(typed_payload["file_paths"]), 2)

    def test_insert_parsed_item_special_window_dedupe(self) -> None:
        repo = ClipRepository(self.db_path, max_items_per_tab=500)
        tab_id = _tab_ids(repo)[0]
        parsed = ParsedClipboardItem(
            item_type="special",
            display_text="[特殊内容]",
            plain_text="",
            html_text="",
            image_blob=None,
            thumb_blob=None,
            width=None,
            height=None,
            file_paths=[],
            mime_formats=["application/x-qt-windows-mime;value=\"PixPinData\""],
            raw_parts=[{"mime_type": "application/x-qt-windows-mime;value=\"PixPinData\"", "payload_blob": b"\x01\x02"}],
        )
        first = repo.insert_parsed_item(tab_id, parsed, captured_at_ms=1000)
        second = repo.insert_parsed_item(tab_id, parsed, captured_at_ms=1800)
        third = repo.insert_parsed_item(tab_id, parsed, captured_at_ms=2201)
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertIsNotNone(third)
        assert first is not None and second is not None and third is not None
        self.assertEqual(first.id, second.id)
        self.assertNotEqual(first.id, third.id)

    def test_search_items_all_tabs_hits_multiple_tabs(self) -> None:
        repo = ClipRepository(self.db_path, max_items_per_tab=500)
        tab_ids = _tab_ids(repo)
        repo.upsert_text_item(tab_ids[0], "alpha-全局检索")
        repo.upsert_text_item(tab_ids[1], "beta-全局检索")

        rows = repo.search_items_all_tabs("全局检索")
        hit_tabs = {item.tab_id for item in rows}
        self.assertIn(tab_ids[0], hit_tabs)
        self.assertIn(tab_ids[1], hit_tabs)

    def test_search_items_all_tabs_hits_note_and_body(self) -> None:
        repo = ClipRepository(self.db_path, max_items_per_tab=500)
        tab_id = _tab_ids(repo)[0]
        item = repo.upsert_text_item(tab_id, "正文关键字")
        self.assertIsNotNone(item)
        assert item is not None
        repo.update_item_note(item.id, "备注关键字")

        body_hits = repo.search_items_all_tabs("正文关键字")
        note_hits = repo.search_items_all_tabs("备注关键字")
        self.assertTrue(any(row.id == item.id for row in body_hits))
        self.assertTrue(any(row.id == item.id for row in note_hits))

    def test_search_items_all_tabs_empty_query_returns_empty(self) -> None:
        repo = ClipRepository(self.db_path, max_items_per_tab=500)
        tab_id = _tab_ids(repo)[0]
        repo.upsert_text_item(tab_id, "anything")

        self.assertEqual(repo.search_items_all_tabs(""), [])
        self.assertEqual(repo.search_items_all_tabs("   "), [])

    def test_search_items_all_tabs_escapes_like_wildcards(self) -> None:
        repo = ClipRepository(self.db_path, max_items_per_tab=500)
        tab_id = _tab_ids(repo)[0]
        exact = repo.upsert_text_item(tab_id, "100%_done")
        fuzzy = repo.upsert_text_item(tab_id, "100XXdone")
        self.assertIsNotNone(exact)
        self.assertIsNotNone(fuzzy)

        rows = repo.search_items_all_tabs("100%_done")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].text, "100%_done")
