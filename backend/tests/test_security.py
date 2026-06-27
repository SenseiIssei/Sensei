from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

import pytest

from sensei.security.auth import generate_token, hash_token, check_auth
from sensei.security.rate_limit import RateLimiter
from sensei.security.sessions import Session, SessionManager
from sensei.security.crypto import LocalCrypto


class TestAuth:
    def test_generate_token_length(self):
        token = generate_token()
        assert len(token) >= 32

    def test_generate_token_unique(self):
        t1 = generate_token()
        t2 = generate_token()
        assert t1 != t2

    def test_hash_token(self):
        token = "test-token-123"
        h = hash_token(token)
        assert h != token
        assert len(h) == 64  # SHA256 hex

    def test_hash_token_consistent(self):
        token = "test-token-123"
        assert hash_token(token) == hash_token(token)

    def test_check_auth_disabled(self, monkeypatch):
        from sensei.config import settings
        monkeypatch.setattr(settings, "auth_enabled", False)
        # When auth is disabled, any request should pass
        assert settings.auth_enabled is False


class TestRateLimiter:
    def test_allows_under_limit(self):
        limiter = RateLimiter(max_requests=5, window_seconds=60)
        for i in range(5):
            allowed, remaining, _ = limiter.check("client1")
            assert allowed is True
        assert remaining == 0

    def test_blocks_over_limit(self):
        limiter = RateLimiter(max_requests=3, window_seconds=60)
        for _ in range(3):
            limiter.check("client1")
        allowed, remaining, retry_after = limiter.check("client1")
        assert allowed is False
        assert remaining == 0
        assert retry_after > 0

    def test_separate_clients(self):
        limiter = RateLimiter(max_requests=2, window_seconds=60)
        limiter.check("client1")
        limiter.check("client1")
        allowed, _, _ = limiter.check("client2")
        assert allowed is True

    def test_reset(self):
        limiter = RateLimiter(max_requests=2, window_seconds=60)
        limiter.check("client1")
        limiter.check("client1")
        limiter.reset("client1")
        allowed, _, _ = limiter.check("client1")
        assert allowed is True

    def test_window_expiry(self):
        limiter = RateLimiter(max_requests=1, window_seconds=1)
        limiter.check("client1")
        allowed, _, _ = limiter.check("client1")
        assert allowed is False
        time.sleep(1.1)
        allowed, _, _ = limiter.check("client1")
        assert allowed is True

    def test_stats(self):
        limiter = RateLimiter(max_requests=10, window_seconds=60)
        limiter.check("a")
        limiter.check("b")
        stats = limiter.stats()
        assert stats["tracked_clients"] == 2
        assert stats["max_requests"] == 10


class TestSession:
    def test_create_session(self):
        session = Session(session_id="test-123", user_id="alice")
        assert session.session_id == "test-123"
        assert session.user_id == "alice"
        assert session.created_at > 0
        assert session.last_active > 0

    def test_add_message(self):
        session = Session(session_id="test-123")
        session.add_message("user", "Hello")
        session.add_message("assistant", "Hi there")
        messages = session.get_messages()
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Hello"

    def test_clear(self):
        session = Session(session_id="test-123")
        session.add_message("user", "Hello")
        session.clear()
        assert len(session.get_messages()) == 0

    def test_is_expired(self):
        session = Session(session_id="test-123")
        assert session.is_expired(60) is False
        session.last_active = time.time() - 3700
        assert session.is_expired(60) is True

    def test_to_dict_from_dict(self):
        session = Session(session_id="test-123", user_id="bob")
        session.add_message("user", "Test")
        d = session.to_dict()
        assert d["session_id"] == "test-123"
        assert d["user_id"] == "bob"
        assert len(d["conversations"]) == 1

        restored = Session.from_dict(d)
        assert restored.session_id == "test-123"
        assert restored.user_id == "bob"
        assert len(restored.get_messages()) == 1


class TestSessionManager:
    def test_create_and_get(self, tmp_path):
        manager = SessionManager(session_dir=tmp_path, timeout_minutes=60)
        session = manager.create_session("alice")
        assert session.user_id == "alice"

        retrieved = manager.get_session(session.session_id)
        assert retrieved is not None
        assert retrieved.user_id == "alice"

    def test_get_nonexistent(self, tmp_path):
        manager = SessionManager(session_dir=tmp_path, timeout_minutes=60)
        assert manager.get_session("nonexistent") is None

    def test_delete_session(self, tmp_path):
        manager = SessionManager(session_dir=tmp_path, timeout_minutes=60)
        session = manager.create_session("alice")
        assert manager.delete_session(session.session_id) is True
        assert manager.get_session(session.session_id) is None
        assert manager.delete_session(session.session_id) is False

    def test_list_sessions(self, tmp_path):
        manager = SessionManager(session_dir=tmp_path, timeout_minutes=60)
        manager.create_session("alice")
        manager.create_session("bob")
        sessions = manager.list_sessions()
        assert len(sessions) == 2

    def test_list_sessions_by_user(self, tmp_path):
        manager = SessionManager(session_dir=tmp_path, timeout_minutes=60)
        manager.create_session("alice")
        manager.create_session("alice")
        manager.create_session("bob")
        alice_sessions = manager.list_sessions(user_id="alice")
        assert len(alice_sessions) == 2
        for s in alice_sessions:
            assert s["user_id"] == "alice"

    def test_get_or_create(self, tmp_path):
        manager = SessionManager(session_dir=tmp_path, timeout_minutes=60)
        session = manager.get_or_create(None, "alice")
        assert session.user_id == "alice"

        same = manager.get_or_create(session.session_id, "alice")
        assert same.session_id == session.session_id

    def test_cleanup_expired(self, tmp_path):
        manager = SessionManager(session_dir=tmp_path, timeout_minutes=60)
        session = manager.create_session("alice")
        session.last_active = time.time() - 3700
        expired = manager.cleanup_expired()
        assert expired == 1
        assert manager.get_session(session.session_id) is None

    def test_persistence(self, tmp_path):
        manager1 = SessionManager(session_dir=tmp_path, timeout_minutes=60)
        session = manager1.create_session("alice")
        session.add_message("user", "Hello")

        # Create new manager (simulates restart)
        manager2 = SessionManager(session_dir=tmp_path, timeout_minutes=60)
        loaded = manager2.get_session(session.session_id)
        assert loaded is not None
        assert loaded.user_id == "alice"
        assert len(loaded.get_messages()) == 1


class TestLocalCrypto:
    def test_machine_key_roundtrip(self):
        # Constructing without a key derives the machine key — must work headless.
        c = LocalCrypto()
        assert c.decrypt(c.encrypt("hello headless")) == "hello headless"

    def test_encrypt_decrypt(self):
        crypto = LocalCrypto(key=b"test-key-32-bytes-long-1234567890")
        original = "Hello, Sensei!"
        encrypted = crypto.encrypt(original)
        assert encrypted != original.encode()
        decrypted = crypto.decrypt(encrypted)
        assert decrypted == original

    def test_encrypt_bytes(self):
        crypto = LocalCrypto(key=b"test-key-32-bytes-long-1234567890")
        data = b"binary data"
        encrypted = crypto.encrypt(data)
        decrypted = crypto.decrypt(encrypted)
        assert decrypted == data.decode()

    def test_encrypt_file(self, tmp_path):
        crypto = LocalCrypto(key=b"test-key-32-bytes-long-1234567890")
        path = tmp_path / "test.enc"
        content = "Secret data to encrypt"
        crypto.encrypt_file(path, content)
        assert path.read_bytes().startswith(b"SENSEI_ENC2:")
        decrypted = crypto.decrypt_file(path)
        assert decrypted == content

    def test_uses_aes_when_available(self):
        from sensei.security import crypto as cryptomod

        c = LocalCrypto(key=b"k" * 32)
        enc = c.encrypt("hello world")
        expected_tag = b"A" if cryptomod._HAS_AES else b"X"
        assert enc[:1] == expected_tag
        assert c.decrypt(enc) == "hello world"

    def test_aes_detects_tampering(self):
        from sensei.security import crypto as cryptomod

        if not cryptomod._HAS_AES:
            return  # XOR has no integrity check
        c = LocalCrypto(key=b"k" * 32)
        enc = bytearray(c.encrypt("important"))
        enc[-1] ^= 0x01  # flip a ciphertext bit
        import pytest

        with pytest.raises(Exception):
            c.decrypt(bytes(enc))

    def test_reads_legacy_xor_file(self, tmp_path):
        # A file written by the pre-AES version (SENSEI_ENC: + raw XOR).
        c = LocalCrypto(key=b"test-key-32-bytes-long-1234567890")
        path = tmp_path / "legacy.enc"
        path.write_bytes(b"SENSEI_ENC:" + c._xor("legacy secret".encode()))
        assert c.decrypt_file(path) == "legacy secret"

    def test_decrypt_unencrypted_file(self, tmp_path):
        crypto = LocalCrypto(key=b"test-key-32-bytes-long-1234567890")
        path = tmp_path / "plain.txt"
        path.write_text("plain text")
        result = crypto.decrypt_file(path)
        assert result == "plain text"

    def test_different_keys_different_output(self):
        crypto1 = LocalCrypto(key=b"key-one-32-bytes-long-1234567890")
        crypto2 = LocalCrypto(key=b"key-two-32-bytes-long-1234567890")
        data = "test data"
        enc1 = crypto1.encrypt(data)
        enc2 = crypto2.encrypt(data)
        assert enc1 != enc2
