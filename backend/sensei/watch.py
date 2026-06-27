"""Watched sources — monitor URLs for changes, re-index into RAG, alert.

Each watch re-fetches its URL when its interval elapses. On the first check the
content hash is recorded (baseline) and the page is indexed into RAG. On a later
change, the page is re-indexed and a change alert is POSTed to the watch's
notify_url (or the global ``watch_notify_url``). Fetches are SSRF-guarded
(via ``webtools.fetch_url``).
"""
from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from pathlib import Path
from typing import Any

import httpx

from sensei.agents.webtools import fetch_url
from sensei.audit import get_audit_log
from sensei.config import settings


class WatchStore:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path is not None else Path(settings.watch_file)
        self._lock = threading.Lock()
        self._watches: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            self._watches = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            self._watches = []

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._watches, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def add(self, url: str, interval_minutes: int = 60, notify_url: str = "") -> str:
        with self._lock:
            wid = secrets.token_hex(8)
            self._watches.append({
                "id": wid,
                "url": url,
                "interval_minutes": max(1, interval_minutes),
                "notify_url": notify_url,
                "last_hash": "",
                "last_checked": 0.0,
                "last_changed": 0.0,
            })
            self._save()
            return wid

    def remove(self, wid: str) -> bool:
        with self._lock:
            before = len(self._watches)
            self._watches = [w for w in self._watches if w["id"] != wid]
            removed = before != len(self._watches)
            if removed:
                self._save()
            return removed

    def list(self) -> list[dict[str, Any]]:
        return [dict(w) for w in self._watches]

    def due(self, now: float) -> list[dict[str, Any]]:
        return [
            dict(w)
            for w in self._watches
            if now - w["last_checked"] >= w["interval_minutes"] * 60
        ]

    def update(self, wid: str, **fields: Any) -> None:
        with self._lock:
            for w in self._watches:
                if w["id"] == wid:
                    w.update(fields)
                    break
            self._save()


_store: WatchStore | None = None


def get_watch_store() -> WatchStore:
    global _store
    if _store is None:
        _store = WatchStore()
    return _store


async def _notify(watch: dict[str, Any], text: str) -> None:
    url = watch.get("notify_url") or settings.watch_notify_url
    if not url:
        return
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                url,
                json={
                    "event": "page_changed",
                    "url": watch["url"],
                    "changed_at": time.time(),
                    "preview": text[:500],
                },
            )
    except httpx.HTTPError:
        pass


async def check_watches(force: bool = False) -> list[dict[str, Any]]:
    """Check due watches; return the list of detected changes."""
    store = get_watch_store()
    now = time.time()
    targets = store.list() if force else store.due(now)
    changes: list[dict[str, Any]] = []

    for w in targets:
        result = await fetch_url(w["url"])
        if "error" in result:
            store.update(w["id"], last_checked=now)
            continue
        text = result.get("content", "")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        first_seen = not w["last_hash"]
        changed = bool(w["last_hash"]) and digest != w["last_hash"]

        updates: dict[str, Any] = {"last_hash": digest, "last_checked": now}
        if changed:
            updates["last_changed"] = now
        store.update(w["id"], **updates)

        if first_seen or changed:
            from sensei.rag.store import get_store

            get_store().add_document(w["url"], text)
        if changed:
            changes.append({"url": w["url"], "changed_at": now})
            await _notify(w, text)
            get_audit_log().record("watch.change", url=w["url"])

    return changes
