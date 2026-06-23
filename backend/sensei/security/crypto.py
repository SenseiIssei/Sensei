from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

from sensei.config import settings

logger = logging.getLogger(__name__)

# XOR-based simple encryption for local data at rest.
# For production use, consider using cryptography library's Fernet.
# This keeps zero external dependencies while providing basic obfuscation.


class LocalCrypto:
    """Simple local data encryption for at-rest protection.

    Uses XOR-based stream cipher with a machine-specific key derived
    from the machine's hostname + user + app salt. This ensures data
    is obfuscated on disk and tied to the local machine.

    For stronger encryption, install the cryptography package and
    set SENSEI_DATA_ENCRYPTION_ENABLED=true.
    """

    SALT = b"sensei_local_data_protection_v1"

    def __init__(self, key: bytes | None = None):
        if key is not None:
            self._key = key
        else:
            self._key = self._derive_machine_key()

    def _derive_machine_key(self) -> bytes:
        """Derive a machine-specific key from environment."""
        machine_id = f"{os.getlogin()}@{os.uname().nodename if hasattr(os, 'uname') else 'localhost'}"
        return hashlib.sha256(machine_id.encode() + self.SALT).digest()

    def encrypt(self, data: str | bytes) -> bytes:
        """Encrypt data using XOR stream cipher."""
        if isinstance(data, str):
            data = data.encode("utf-8")
        return self._xor(data)

    def decrypt(self, data: bytes) -> str:
        """Decrypt data and return as string."""
        return self._xor(data).decode("utf-8")

    def encrypt_file(self, path: Path, content: str) -> None:
        """Encrypt content and write to file."""
        encrypted = self.encrypt(content)
        # Write with a magic header to identify encrypted files
        path.write_bytes(b"SENSEI_ENC:" + encrypted)

    def decrypt_file(self, path: Path) -> str | None:
        """Read and decrypt a file. Returns None if not encrypted."""
        data = path.read_bytes()
        if data.startswith(b"SENSEI_ENC:"):
            return self.decrypt(data[len(b"SENSEI_ENC:"):])
        # Fallback: return as plain text
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return None

    def _xor(self, data: bytes) -> bytes:
        """XOR data with the key (repeating)."""
        key_len = len(self._key)
        return bytes(b ^ self._key[i % key_len] for i, b in enumerate(data))


# Global instance
_crypto: LocalCrypto | None = None


def get_crypto() -> LocalCrypto:
    global _crypto
    if _crypto is None:
        _crypto = LocalCrypto()
    return _crypto
