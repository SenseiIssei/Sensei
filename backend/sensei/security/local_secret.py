"""Random secrets this machine makes for itself, kept in ``~/.sensei``."""

from __future__ import annotations

import logging
import secrets
from functools import lru_cache
from pathlib import Path

from sensei import config as config_mod
from sensei.atomic import publish_new

logger = logging.getLogger(__name__)


@lru_cache(maxsize=16)
def _read_or_create(path: Path) -> str | None:
    try:
        if not path.exists():
            publish_new(secrets.token_hex(32).encode("ascii"), path)
        value = path.read_text(encoding="ascii").strip()
        bytes.fromhex(value)
    except (OSError, ValueError) as exc:
        logger.warning("Cannot use %s (%s)", path, exc)
        return None
    if len(value) < 64:
        logger.warning("%s is not a key this program made; delete it to get a new one", path)
        return None
    return value


def local_secret(name: str) -> str | None:
    """The secret called ``name``, made on first use and readable only by its owner.

    None when it cannot be kept. The caller decides what that means: nothing may
    be encrypted with a key that is gone after a restart.
    """
    return _read_or_create(config_mod.SENSEI_HOME / name)
