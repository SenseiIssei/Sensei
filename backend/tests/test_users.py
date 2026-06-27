from __future__ import annotations

import sensei.security.users as users


def test_register_login_and_token_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(users, "USERS_FILE", tmp_path / "users.json")

    tok, err = users.register_user("Alice@Example.com", "password123", "Alice")
    assert err is None and tok is not None
    assert tok.user.email == "alice@example.com"  # normalized

    # Duplicate registration is rejected.
    dup, dup_err = users.register_user("alice@example.com", "password123", "Alice")
    assert dup is None and dup_err is not None

    # Login works with the right password, fails with the wrong one.
    good, gerr = users.login_user("alice@example.com", "password123")
    assert gerr is None and good is not None
    bad, berr = users.login_user("alice@example.com", "wrong")
    assert bad is None and berr is not None

    # Token verifies and resolves back to the user.
    payload = users.verify_token(good.access_token)
    assert payload and payload["email"] == "alice@example.com"
    resolved = users.get_user_from_token(good.access_token)
    assert resolved and resolved["name"] == "Alice"


def test_invalid_tokens_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(users, "USERS_FILE", tmp_path / "users.json")
    assert users.verify_token("garbage") is None
    assert users.verify_token("a.b.c") is None  # wrong segment count
    assert users.get_user_from_token("nope.sig") is None
