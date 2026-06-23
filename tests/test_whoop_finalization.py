from __future__ import annotations

import unittest
from datetime import datetime, timezone

from whoop_policy_layer.whoop import select_stable_whoop_records


NOW = datetime(2026, 6, 23, 14, 0, tzinfo=timezone.utc)


def sleep(sleep_id: str, *, score_state: str = "SCORED", end: str = "2026-06-23T12:00:00.000Z", nap: bool = False) -> dict:
    return {"id": sleep_id, "score_state": score_state, "start": "2026-06-23T04:00:00.000Z", "end": end, "nap": nap}


def recovery(sleep_id: str, *, score_state: str = "SCORED") -> dict:
    return {"id": f"rec-{sleep_id}", "sleep_id": sleep_id, "score_state": score_state, "created_at": "2026-06-23T12:05:00.000Z"}


class WhoopFinalizationTests(unittest.TestCase):
    def test_rejects_pending_sleep(self) -> None:
        result = select_stable_whoop_records([recovery("sleep-1")], [sleep("sleep-1", score_state="PENDING_SCORE")], now=NOW)
        self.assertEqual(result["metadata"]["whoop_data_freshness"], "pending_score")
        self.assertIsNone(result["recovery"])

    def test_rejects_pending_recovery(self) -> None:
        result = select_stable_whoop_records([recovery("sleep-1", score_state="PENDING_SCORE")], [sleep("sleep-1")], now=NOW)
        self.assertEqual(result["metadata"]["whoop_data_freshness"], "pending_score")
        self.assertEqual(result["metadata"]["recovery_score_state"], "PENDING_SCORE")

    def test_requires_matching_recovery_sleep_id(self) -> None:
        result = select_stable_whoop_records([recovery("other")], [sleep("sleep-1")], now=NOW)
        self.assertEqual(result["metadata"]["whoop_data_freshness"], "missing")

    def test_prefers_non_nap_sleep(self) -> None:
        result = select_stable_whoop_records(
            [recovery("main")],
            [sleep("nap", end="2026-06-23T13:00:00.000Z", nap=True), sleep("main", end="2026-06-23T11:00:00.000Z")],
            now=NOW,
        )
        self.assertEqual(result["sleep"]["id"], "main")
        self.assertEqual(result["metadata"]["whoop_data_freshness"], "finalized_current")

    def test_recent_sleep_is_too_fresh(self) -> None:
        result = select_stable_whoop_records([recovery("sleep-1")], [sleep("sleep-1", end="2026-06-23T13:45:00.000Z")], now=NOW)
        self.assertEqual(result["metadata"]["whoop_data_freshness"], "too_fresh")


if __name__ == "__main__":
    unittest.main()
