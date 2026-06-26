from __future__ import annotations

from fastapi.testclient import TestClient

from sensei.audit import AuditLog
from sensei.main import app


def test_record_and_tail(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    log.record("test.event", foo="bar", n=1)
    log.record("test.other", x=2)
    events = log.tail(10)
    assert len(events) == 2
    assert events[0]["event"] == "test.event"
    assert events[0]["foo"] == "bar"
    assert "ts" in events[0]


def test_tail_limit(tmp_path):
    log = AuditLog(tmp_path / "a.jsonl")
    for i in range(10):
        log.record("e", i=i)
    assert len(log.tail(3)) == 3


def test_audit_endpoint():
    client = TestClient(app)
    resp = client.get("/api/audit?limit=5")
    assert resp.status_code == 200
    assert "events" in resp.json()
