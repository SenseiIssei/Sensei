from __future__ import annotations

from fastapi.testclient import TestClient

from sensei.config import settings
from sensei.main import app


def test_webhook_disabled_by_default():
    client = TestClient(app)
    resp = client.post("/api/webhook", json={"message": "hi"})
    assert resp.status_code == 404


def test_webhook_rejects_wrong_token(monkeypatch):
    monkeypatch.setattr(settings, "webhook_enabled", True)
    monkeypatch.setattr(settings, "webhook_token", "s3cret")
    client = TestClient(app)
    resp = client.post(
        "/api/webhook",
        json={"message": "hi"},
        headers={"X-Sensei-Webhook-Token": "wrong"},
    )
    assert resp.status_code == 401


def test_webhook_rejects_missing_token(monkeypatch):
    monkeypatch.setattr(settings, "webhook_enabled", True)
    monkeypatch.setattr(settings, "webhook_token", "s3cret")
    client = TestClient(app)
    resp = client.post("/api/webhook", json={"message": "hi"})
    assert resp.status_code == 401
