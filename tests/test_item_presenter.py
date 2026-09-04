from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from clipboard_manager.models import ClipItem
from clipboard_manager.ui.item_presenter import (
    _format_time,
    _parse_stored_time,
    present_item,
)


def _iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


class ParseStoredTimeTests(unittest.TestCase):
    def test_utc_iso_is_converted_to_local(self) -> None:
        stored = "2026-09-04T07:59:12+00:00"
        parsed = _parse_stored_time(stored)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertIsNotNone(parsed.tzinfo)
        # Same instant, expressed in the machine's local zone.
        self.assertEqual(
            parsed.astimezone(timezone.utc),
            datetime(2026, 9, 4, 7, 59, 12, tzinfo=timezone.utc),
        )

    def test_naive_legacy_value_is_kept_as_local(self) -> None:
        parsed = _parse_stored_time("2026-09-04 15:59:12")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertIsNone(parsed.tzinfo)
        self.assertEqual(parsed.hour, 15)

    def test_blank_and_garbage_return_none(self) -> None:
        self.assertIsNone(_parse_stored_time(""))
        self.assertIsNone(_parse_stored_time("   "))
        self.assertIsNone(_parse_stored_time("not-a-time"))


class FormatTimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 9, 4, 15, 59, 0, tzinfo=timezone(timedelta(hours=8)))

    def _fmt(self, dt: datetime) -> str:
        return _format_time(_iso_utc(dt), now=self.now)

    def test_just_now(self) -> None:
        self.assertEqual(self._fmt(self.now - timedelta(seconds=5)), "刚刚")

    def test_minutes_ago(self) -> None:
        self.assertEqual(self._fmt(self.now - timedelta(minutes=5)), "5 分钟前")
        self.assertEqual(self._fmt(self.now - timedelta(minutes=59)), "59 分钟前")

    def test_today_shows_clock(self) -> None:
        self.assertEqual(self._fmt(self.now - timedelta(hours=3)), "今天 12:59")

    def test_yesterday(self) -> None:
        self.assertEqual(self._fmt(self.now - timedelta(hours=26)), "昨天 13:59")

    def test_same_year_shows_month_day(self) -> None:
        self.assertEqual(self._fmt(self.now - timedelta(days=40)), "07-26 15:59")

    def test_previous_year_includes_year(self) -> None:
        self.assertEqual(self._fmt(self.now - timedelta(days=400)), "2025-07-31 15:59")

    def test_utc_stored_value_shows_local_clock(self) -> None:
        # Regression: stored UTC used to be printed verbatim, i.e. 8 hours behind.
        stored = "2026-09-04T07:59:00+00:00"  # == 15:59 in +08:00
        self.assertEqual(_format_time(stored, now=self.now), "刚刚")

    def test_future_timestamp_falls_back_to_absolute(self) -> None:
        result = _format_time(_iso_utc(self.now + timedelta(hours=2)), now=self.now)
        self.assertEqual(result, "09-04 17:59")

    def test_unparsable_value_is_passed_through(self) -> None:
        self.assertEqual(_format_time("garbage", now=self.now), "garbage")

    def test_naive_stored_value_with_aware_now(self) -> None:
        # Legacy naive rows must not raise when compared against an aware "now".
        result = _format_time("2026-09-04 15:00:00", now=self.now)
        self.assertIn(result, {"59 分钟前", "今天 15:00"}, result)

    def test_naive_now_with_aware_stored_value(self) -> None:
        naive_now = datetime(2026, 9, 4, 15, 59, 0)
        result = _format_time("2026-09-04T07:59:00+00:00", now=naive_now)
        self.assertIsInstance(result, str)
        self.assertNotEqual(result, "")


class PresentItemTimeTests(unittest.TestCase):
    def test_secondary_text_uses_relative_time(self) -> None:
        now = datetime.now(timezone.utc)
        item = ClipItem(
            id=1,
            tab_id=1,
            sort_order=0,
            content_type="text",
            text="hello",
            mime_type=None,
            width=None,
            height=None,
            content_hash="h1",
            created_at=now.isoformat(),
            last_used_at=now.isoformat(),
            use_count=0,
            display_text="hello",
            plain_text="hello",
        )
        row = present_item(item)
        self.assertTrue(
            row.secondary_text.startswith("刚刚"),
            f"unexpected secondary text: {row.secondary_text}",
        )


if __name__ == "__main__":
    unittest.main()
