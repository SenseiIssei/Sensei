"""Append-only audit log — records *metadata* about model calls and config
changes (never prompt contents). One JSON object per line.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from sensei.config import settings


class AuditLog:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path is not None else Path(settings.audit_file)
        self._lock = threading.Lock()

    def record(self, event: str, **fields: Any) -> None:
        if not settings.audit_enabled:
            return
        entry = {"ts": time.time(), "event": event, **fields}
        line = json.dumps(entry, ensure_ascii=False, default=str)
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError:
                pass  # auditing must never break the request path

    def tail(self, limit: int = 100) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out: list[dict[str, Any]] = []
        for line in lines[-limit:]:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out


_audit: AuditLog | None = None


def get_audit_log() -> AuditLog:
    global _audit
    if _audit is None:
        _audit = AuditLog()
    return _audit
