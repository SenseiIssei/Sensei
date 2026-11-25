"""Random secrets this machine makes for itself, kept in ``~/.sensei``."""

from __future__ import annotations

import logging
import os
import secrets
from functools import lru_cache
from pathlib import Path

from sensei import config as config_mod

logger = logging.getLogger(__name__)


@lru_cache(maxsize=16)
def _read_or_create(path: Path) -> str:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive: of two processes starting at once, one makes it.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return path.read_text(encoding="ascii").strip()
    except OSError as exc:
        logger.warning("Cannot keep %s (%s): a new one is used until restart", path.name, exc)
        return secrets.token_hex(32)
    with os.fdopen(fd, "w", encoding="ascii") as fh:
        value = secrets.token_hex(32)
        fh.write(value)
    return value


def local_secret(name: str) -> str:
    """The secret called ``name``, made on first use and readable only by its owner."""
    value = _read_or_create(config_mod.SENSEI_HOME / name)
    if not value:  # cut off while it was being written
        _read_or_create.cache_clear()
        raise RuntimeError(f"{config_mod.SENSEI_HOME / name} is empty; delete it and start again")
    return value
