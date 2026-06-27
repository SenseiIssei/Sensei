from __future__ import annotations

from fastapi.testclient import TestClient

import sensei.security.users as users
from sensei.config import settings
from sensei.main import app


def test_rbac_off_allows_without_auth(monkeypatch):
    monkeypatch.setattr(settings, "rbac_enabled", False)
    client = TestClient(app)
    assert client.post("/api/maintenance/purge").status_code == 200


def test_rbac_on_requires_token(monkeypatch):
    monkeypatch.setattr(settings, "rbac_enabled", True)
    client = TestClient(app)
    assert client.post("/api/maintenance/purge").status_code == 401


def test_rbac_on_rejects_non_admin(tmp_path, monkeypatch):
    monkeypatch.setattr(users, "USERS_FILE", tmp_path / "u.json")
    monkeypatch.setattr(settings, "admin_emails", "")
    monkeypatch.setattr(settings, "rbac_enabled", True)
    tok, _ = users.register_user("user@example.com", "password123", "User")
    client = TestClient(app)
    resp = client.post(
        "/api/maintenance/purge", headers={"Authorization": f"Bearer {tok.access_token}"}
    )
    assert resp.status_code == 403


def test_rbac_on_allows_admin(tmp_path, monkeypatch):
    monkeypatch.setattr(users, "USERS_FILE", tmp_path / "u.json")
    monkeypatch.setattr(settings, "admin_emails", "admin@example.com")
    monkeypatch.setattr(settings, "rbac_enabled", True)
    tok, _ = users.register_user("admin@example.com", "password123", "Admin")
    client = TestClient(app)
    resp = client.post(
        "/api/maintenance/purge", headers={"Authorization": f"Bearer {tok.access_token}"}
    )
    assert resp.status_code == 200
