"""Where Sensei keeps things: one place, whatever it was started from."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag

from sensei import config as config_mod
from sensei.audit import AuditLog
from sensei.config import settings
from sensei.rag.store import DocumentStore
from sensei.security import users
from sensei.security.crypto import LocalCrypto
from sensei.security.local_secret import _read_or_create, local_secret
from sensei.security.sessions import SessionManager
from sensei.security.vault import KeyVault


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home" / ".sensei"
    monkeypatch.setattr(config_mod, "SENSEI_HOME", home)
    monkeypatch.setattr(config_mod, "_former_homes", list)
    cwd = tmp_path / "some-project"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    _read_or_create.cache_clear()
    yield home
    _read_or_create.cache_clear()


def test_nothing_is_written_to_the_working_directory(home: Path) -> None:
    KeyVault().set_key("openai", "sk-1")
    AuditLog().record("test")
    SessionManager().create_session()
    DocumentStore().add_document("doc", "some text worth indexing")
    users._save_users({"a@b.c": {}})
    _ = settings.memory_path
    assert list(Path.cwd().iterdir()) == []
    assert {p.name for p in home.iterdir()} >= {
        "vault.json",
        "audit.jsonl",
        "sessions",
        "rag.json",
        "users.json",
        "memory",
    }


def test_a_configured_path_is_used_as_written(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "vault_file", str(tmp_path / "mine.json"))
    KeyVault().set_key("openai", "sk-1")
    assert (tmp_path / "mine.json").exists()
    assert not (home / "vault.json").exists()


class TestTheBinary:
    """`Path(__file__).parents[2]` in the one-file build is the temp directory."""

    def test_settings_live_in_the_home_not_in_temp(
        self, home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(config_mod, "_ROOT", tmp_path / "Temp")
        assert config_mod.env_path() == home / ".env"

    def test_a_checkout_keeps_its_own(self, home: Path) -> None:
        assert config_mod.env_path() == Path(__file__).resolve().parents[2] / ".env"

    def test_a_pip_install_uses_the_home(
        self, home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(config_mod, "_ROOT", tmp_path / "venv" / "Lib")
        assert config_mod.env_path() == home / ".env"

    def test_what_the_settings_page_saved_is_carried_over(self, home: Path, tmp_path: Path) -> None:
        temp = tmp_path / "Temp"
        temp.mkdir()
        (temp / ".env").write_text(
            "SENSEI_API_PROVIDER=groq\n"
            "SENSEI_GROQ_API_MODEL=m\n"
            "SENSEI_ANTHROPIC_API_BASE_URL=http://evil.example\n"
            "SENSEI_AUTH_ENABLED=false\n"
            "OTHER=1\n",
            encoding="utf-8",
        )
        config_mod.carry_over_env(home / ".env", temp)
        kept = (home / ".env").read_text(encoding="utf-8").split()
        assert kept == ["SENSEI_API_PROVIDER=groq", "SENSEI_GROQ_API_MODEL=m"]

    def test_but_never_over_settings_that_exist(self, home: Path, tmp_path: Path) -> None:
        home.mkdir(parents=True)
        (home / ".env").write_text("SENSEI_API_PROVIDER=openai\n", encoding="utf-8")
        (tmp_path / ".env").write_text("SENSEI_API_PROVIDER=groq\n", encoding="utf-8")
        config_mod.carry_over_env(home / ".env", tmp_path)
        assert "openai" in (home / ".env").read_text(encoding="utf-8")


class TestWhatAnOlderVersionLeft:
    def test_it_is_brought_along_once_and_left_in_place(
        self, home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        old = tmp_path / "install"
        (old / ".sensei_memory").mkdir(parents=True)
        (old / ".sensei_memory" / "conversations.json").write_text("{}", encoding="utf-8")
        (old / ".sensei_rag.json").write_text("[]", encoding="utf-8")
        monkeypatch.setattr(config_mod, "_former_homes", lambda: [old])
        assert (settings.memory_path / "conversations.json").read_text(encoding="utf-8") == "{}"
        assert settings.rag_path.read_text(encoding="utf-8") == "[]"
        assert (old / ".sensei_rag.json").exists()
        (old / ".sensei_rag.json").write_text("[1]", encoding="utf-8")
        assert settings.rag_path.read_text(encoding="utf-8") == "[]"

    @pytest.mark.parametrize("frozen", [True, False])
    def test_not_from_the_directory_this_was_started_in(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, frozen: bool
    ) -> None:
        """A cloned repository could bring a user database with an admin in it."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(sys, "frozen", frozen, raising=False)
        assert tmp_path not in config_mod._former_homes()

    def test_a_planted_user_database_is_ignored(self, home: Path) -> None:
        Path(".sensei_users.json").write_text(json.dumps({"evil": {}}), encoding="utf-8")
        assert users._load_users() == {}


class TestSecrets:
    def test_the_key_is_random_and_stays(self, home: Path) -> None:
        blob = LocalCrypto().encrypt("secret")
        assert (home / "local-key").read_text(encoding="ascii") == local_secret("local-key")
        _read_or_create.cache_clear()
        assert LocalCrypto().decrypt(blob) == "secret"
        (home / "local-key").unlink()
        _read_or_create.cache_clear()
        with pytest.raises(InvalidTag):
            LocalCrypto().decrypt(blob)

    def test_the_hostname_is_no_longer_enough(self, home: Path) -> None:
        machine = LocalCrypto(key=LocalCrypto()._derive_machine_key())
        with pytest.raises(InvalidTag):
            machine.decrypt(LocalCrypto().encrypt("secret"))

    def test_what_the_old_key_wrote_is_still_readable(self, home: Path) -> None:
        old = LocalCrypto(key=LocalCrypto()._derive_machine_key())
        assert LocalCrypto().decrypt(old.encrypt("written by 0.3")) == "written by 0.3"

    def test_a_vault_from_0_3_opens_and_moves_to_the_new_key(self, home: Path) -> None:
        home.mkdir(parents=True, exist_ok=True)
        vault = KeyVault()
        vault._crypto = LocalCrypto(key=LocalCrypto()._derive_machine_key())
        vault.set_key("openai", "sk-old")
        reopened = KeyVault()
        assert reopened.get_key("openai") == "sk-old"
        reopened.set_key("groq", "gsk")
        assert KeyVault().get_key("openai") == "sk-old"

    def test_sign_ins_survive_a_restart(self, home: Path) -> None:
        token = users._create_token("1", "a@b.c")
        _read_or_create.cache_clear()
        assert users.verify_token(token)

    def test_a_secret_set_in_the_settings_is_used(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        token = users._create_token("1", "a@b.c")
        monkeypatch.setattr(settings, "jwt_secret", "another")
        assert users.verify_token(token) is None
        assert users.verify_token(users._create_token("1", "a@b.c"))
