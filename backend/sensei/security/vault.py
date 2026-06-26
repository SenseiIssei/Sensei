"""Encrypted API-key vault.

Stores provider API keys encrypted at rest with AES (via ``LocalCrypto``) so
keys never sit in plaintext on disk. Encryption key is derived from an optional
master password (``SENSEI_VAULT_PASSWORD``) or, by default, the machine key.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from sensei.config import settings
from sensei.security.crypto import LocalCrypto

logger = logging.getLogger(__name__)

_MAGIC = b"SENSEI_VAULT:"


class KeyVault:
    def __init__(self, path: Path | str | None = None, password: str | None = None):
        self.path = Path(path) if path is not None else Path(settings.vault_file)
        pw = settings.vault_password if password is None else password
        if pw:
            key = hashlib.sha256(b"sensei-vault:" + pw.encode("utf-8")).digest()
            self._crypto = LocalCrypto(key=key)
        else:
            self._crypto = LocalCrypto()  # machine-derived key
        self._data: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            blob = self.path.read_bytes()
            if blob.startswith(_MAGIC):
                self._data = json.loads(self._crypto.decrypt(blob[len(_MAGIC):]))
        except Exception as exc:  # wrong password / corrupt / tampered
            logger.warning("Could not read key vault (%s) — ignoring.", exc)
            self._data = {}

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_bytes(_MAGIC + self._crypto.encrypt(json.dumps(self._data)))
        except OSError as exc:
            logger.warning("Could not write key vault: %s", exc)

    def set_key(self, provider: str, key: str) -> None:
        self._data[provider] = key
        self._save()

    def get_key(self, provider: str) -> str:
        return self._data.get(provider, "")

    def providers(self) -> list[str]:
        return list(self._data.keys())

    def apply_to_settings(self) -> int:
        """Populate ``settings.<provider>_api_key`` from the vault. Returns count."""
        applied = 0
        for provider, key in self._data.items():
            attr = f"{provider}_api_key"
            if key and hasattr(settings, attr):
                setattr(settings, attr, key)
                applied += 1
        return applied


_vault: KeyVault | None = None


def get_vault() -> KeyVault:
    global _vault
    if _vault is None:
        _vault = KeyVault()
    return _vault
