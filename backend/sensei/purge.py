"""Data auto-purge — drop expired sessions / CCR entries and old audit lines.

Run periodically by a background loop (see main.py) and exposed manually via
``POST /api/maintenance/purge``. Each step is best-effort and isolated so one
failure doesn't block the others.
"""
from __future__ import annotations

import logging
from typing import Any

from sensei.audit import get_audit_log
from sensei.config import settings

logger = logging.getLogger(__name__)


def purge_expired() -> dict[str, Any]:
    result: dict[str, Any] = {"ccr": 0, "sessions": 0, "audit": 0}

    try:
        from sensei.compression.ccr import CCRStore

        result["ccr"] = CCRStore().cleanup()
    except Exception as exc:  # noqa: BLE001
        logger.debug("CCR purge skipped: %s", exc)

    try:
        from sensei.security.sessions import SessionManager

        result["sessions"] = SessionManager().cleanup_expired()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Session purge skipped: %s", exc)

    try:
        result["audit"] = get_audit_log().trim(settings.audit_max_days)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Audit purge skipped: %s", exc)

    logger.info(
        "Data purge: %d CCR, %d sessions, %d audit entries removed",
        result["ccr"], result["sessions"], result["audit"],
    )
    return result
