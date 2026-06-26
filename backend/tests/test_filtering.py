from __future__ import annotations

from sensei.config import settings
from sensei.security.filtering import blocked_model, check_policy


def test_blocked_model(monkeypatch):
    monkeypatch.setattr(settings, "blocked_models", "gpt-4, o1")
    assert blocked_model("gpt-4o") == "gpt-4"
    assert blocked_model("claude-3-5-sonnet") is None
    assert blocked_model(None) is None


def test_check_policy_model(monkeypatch):
    monkeypatch.setattr(settings, "blocked_models", "o1")
    monkeypatch.setattr(settings, "blocked_patterns", "")
    assert check_policy({"model": "o1-preview"}) is not None
    assert check_policy({"model": "gpt-4o"}) is None


def test_check_policy_content(monkeypatch):
    monkeypatch.setattr(settings, "blocked_models", "")
    monkeypatch.setattr(settings, "blocked_patterns", r"confidential|secret-project")
    blocked = {"model": "x", "messages": [{"role": "user", "content": "about secret-project alpha"}]}
    assert check_policy(blocked) is not None
    ok = {"model": "x", "messages": [{"role": "user", "content": "hello world"}]}
    assert check_policy(ok) is None


def test_check_policy_allows_by_default(monkeypatch):
    monkeypatch.setattr(settings, "blocked_models", "")
    monkeypatch.setattr(settings, "blocked_patterns", "")
    assert check_policy({"model": "anything", "messages": [{"role": "user", "content": "x"}]}) is None
