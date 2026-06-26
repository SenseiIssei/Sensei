from __future__ import annotations

from fastapi.testclient import TestClient

from sensei.main import app
from sensei.savings import SavingsTracker


class TestSavingsTracker:
    def test_record_and_snapshot(self):
        t = SavingsTracker()
        t.record({
            "prompt_tokens_before": 1000,
            "prompt_tokens_after": 300,
            "tokens_saved": 700,
            "blocks_compressed": 2,
        })
        t.record({
            "prompt_tokens_before": 500,
            "prompt_tokens_after": 200,
            "tokens_saved": 300,
            "blocks_compressed": 1,
        })
        snap = t.snapshot()
        assert snap["requests"] == 2
        assert snap["tokens_saved"] == 1000
        assert snap["tokens_before"] == 1500
        assert snap["percent_saved"] > 60  # 1000/1500 saved == 66.7%
        assert snap["estimated_cost_saved_usd"] >= 0

    def test_reset(self):
        t = SavingsTracker()
        t.record({"tokens_saved": 50, "prompt_tokens_before": 100, "prompt_tokens_after": 50})
        t.reset()
        assert t.snapshot()["requests"] == 0


class TestStatsSavingsBlock:
    def test_stats_includes_savings(self):
        client = TestClient(app)
        resp = client.get("/api/stats")
        assert resp.status_code == 200
        savings = resp.json()["savings"]
        for key in ("requests", "tokens_saved", "percent_saved", "estimated_cost_saved_usd"):
            assert key in savings
