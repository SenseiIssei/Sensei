from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

from sensei.security.local_secret import local_secret

logger = logging.getLogger(__name__)

# Authenticated AES-256-GCM for local data at rest, with a zero-dependency XOR
# fallback when the `cryptography` package isn't installed. The key is random and
# kept in ~/.sensei/local-key, readable by its owner only. That protects a copy of
# the data that travels without the key (a backup, a synced folder, a disk image
# of another directory), not a login that can read both.

try:  # pragma: no cover - depends on whether `cryptography` is installed
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    _HAS_AES = True
except ImportError:
    AESGCM = None  # type: ignore[assignment]
    _HAS_AES = False

# 1-byte mode tags so a blob can be decrypted without out-of-band metadata.
_TAG_AES = b"A"
_TAG_XOR = b"X"


class LocalCrypto:
    """Local data encryption for at-rest protection.

    Uses **AES-256-GCM** (authenticated) when ``cryptography`` is available.
    Falls back to an XOR stream cipher (obfuscation only) so installs without
    the optional dependency keep working.

    Up to 0.3 the key was a hash of ``user@hostname``: anybody who knew those two
    could decrypt the data, and a container with a new hostname could not. Data
    written that way is still readable, and is written with the new key next time.
    """

    SALT = b"sensei_local_data_protection_v1"

    def __init__(self, key: bytes | None = None):
        self._legacy_aes = None
        if key is None:
            machine = self._derive_machine_key()
            self._key = machine  # what XOR data was written with
            if _HAS_AES:
                self._legacy_aes = AESGCM(hashlib.sha256(machine).digest())
                key = bytes.fromhex(local_secret("local-key"))
        else:
            self._key = key
        # AES needs exactly 32 bytes; hash whatever we were given.
        self._aes = AESGCM(hashlib.sha256(key).digest()) if _HAS_AES and key else None

    def _derive_machine_key(self) -> bytes:
        """The key up to 0.3, for reading what it wrote (robust on headless hosts)."""
        node = (
            os.uname().nodename
            if hasattr(os, "uname")
            else os.environ.get("COMPUTERNAME", "localhost")
        )
        # os.getlogin() raises OSError without a controlling tty (CI, daemons),
        # so prefer getpass/env which work headless.
        try:
            import getpass

            user = getpass.getuser()
        except Exception:
            user = (
                os.environ.get("USER")
                or os.environ.get("USERNAME")
                or os.environ.get("LOGNAME")
                or "sensei"
            )
        machine_id = f"{user}@{node}"
        return hashlib.sha256(machine_id.encode() + self.SALT).digest()

    def encrypt(self, data: str | bytes) -> bytes:
        """Encrypt data, returning a self-describing blob (mode tag + payload)."""
        raw = data.encode("utf-8") if isinstance(data, str) else data
        if self._aes is not None:
            nonce = os.urandom(12)
            return _TAG_AES + nonce + self._aes.encrypt(nonce, raw, None)
        return _TAG_XOR + self._xor(raw)

    def decrypt(self, data: bytes) -> str:
        """Decrypt a blob produced by ``encrypt`` (or legacy untagged XOR)."""
        if data[:1] == _TAG_AES and self._aes is not None:
            nonce, ct = data[1:13], data[13:]
            try:
                return self._aes.decrypt(nonce, ct, None).decode("utf-8")
            except Exception:
                if self._legacy_aes is None:
                    raise
                return self._legacy_aes.decrypt(nonce, ct, None).decode("utf-8")
        if data[:1] == _TAG_XOR:
            return self._xor(data[1:]).decode("utf-8")
        # Legacy: untagged XOR payload (pre-AES versions).
        return self._xor(data).decode("utf-8")

    def encrypt_file(self, path: Path, content: str) -> None:
        """Encrypt content and write to file with a versioned magic header."""
        path.write_bytes(b"SENSEI_ENC2:" + self.encrypt(content))

    def decrypt_file(self, path: Path) -> str | None:
        """Read and decrypt a file. Returns None if it can't be decoded."""
        data = path.read_bytes()
        if data.startswith(b"SENSEI_ENC2:"):
            return self.decrypt(data[len(b"SENSEI_ENC2:") :])
        if data.startswith(b"SENSEI_ENC:"):  # legacy XOR container
            return self._xor(data[len(b"SENSEI_ENC:") :]).decode("utf-8")
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


def encryption_backend() -> str:
    """Return the active backend name for diagnostics ('aes-256-gcm' or 'xor')."""
    return "aes-256-gcm" if _HAS_AES else "xor"
