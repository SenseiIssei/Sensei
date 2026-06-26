from __future__ import annotations

import json
import time

from fastapi.testclient import TestClient

from sensei.audit import AuditLog
from sensei.main import app
from sensei.purge import purge_expired


def test_audit_trim_drops_old_entries(tmp_path):
    p = tmp_path / "audit.jsonl"
    old = time.time() - 100 * 86400
    new = time.time()
    p.write_text(
        json.dumps({"ts": old, "event": "old"}) + "\n" + json.dumps({"ts": new, "event": "new"}) + "\n",
        encoding="utf-8",
    )
    log = AuditLog(p)
    assert log.trim(30) == 1
    remaining = log.tail(10)
    assert len(remaining) == 1 and remaining[0]["event"] == "new"


def test_audit_trim_disabled_when_zero(tmp_path):
    p = tmp_path / "audit.jsonl"
    p.write_text(json.dumps({"ts": 0, "event": "ancient"}) + "\n", encoding="utf-8")
    assert AuditLog(p).trim(0) == 0  # 0 days = keep everything


def test_purge_expired_returns_counts():
    result = purge_expired()
    assert {"ccr", "sessions", "audit"} <= set(result.keys())


def test_maintenance_purge_endpoint():
    client = TestClient(app)
    resp = client.post("/api/maintenance/purge")
    assert resp.status_code == 200
    assert "audit" in resp.json()
