from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

from sensei.config import settings

logger = logging.getLogger(__name__)


class CCRStore:
    """Compressed Cache & Retrieve — stores originals for on-demand retrieval.

    Inspired by Headroom's CCR — when content is compressed, the original
    is cached locally. If the model needs the full uncompressed content,
    it can request it via a tool call (headroom_retrieve equivalent).

    The store uses a simple file-based cache with TTL expiration.
    """

    def __init__(self, cache_dir: Path | None = None, ttl_hours: int | None = None):
        self.cache_dir = cache_dir or settings.ccr_cache_path
        self.ttl_seconds = (ttl_hours or settings.ccr_ttl_hours) * 3600
        self._index: dict[str, dict[str, Any]] = {}
        self._load_index()

    def store(
        self,
        original: str,
        compressed: str,
        content_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Store an original and return a CCR ID for retrieval."""
        ccr_id = str(uuid.uuid4())
        entry = {
            "id": ccr_id,
            "original": original,
            "compressed": compressed,
            "content_type": content_type,
            "stored_at": time.time(),
            "metadata": metadata or {},
        }

        self._index[ccr_id] = entry
        self._persist_entry(entry)
        return ccr_id

    def retrieve(self, ccr_id: str) -> str | None:
        """Retrieve the original content by CCR ID."""
        entry = self._index.get(ccr_id)
        if entry is None:
            return None

        # Check TTL
        if time.time() - entry["stored_at"] > self.ttl_seconds:
            self._evict(ccr_id)
            return None

        return entry["original"]

    def get_info(self, ccr_id: str) -> dict[str, Any] | None:
        """Get metadata about a CCR entry."""
        entry = self._index.get(ccr_id)
        if entry is None:
            return None
        return {
            "id": entry["id"],
            "content_type": entry["content_type"],
            "stored_at": entry["stored_at"],
            "original_size": len(entry["original"]),
            "compressed_size": len(entry["compressed"]),
            "metadata": entry.get("metadata", {}),
        }

    def stats(self) -> dict[str, Any]:
        """Return cache statistics."""
        now = time.time()
        active = sum(
            1 for e in self._index.values()
            if now - e["stored_at"] <= self.ttl_seconds
        )
        total_original = sum(len(e["original"]) for e in self._index.values())
        total_compressed = sum(len(e["compressed"]) for e in self._index.values())

        return {
            "total_entries": len(self._index),
            "active_entries": active,
            "total_original_bytes": total_original,
            "total_compressed_bytes": total_compressed,
            "space_saved_bytes": total_original - total_compressed,
        }

    def cleanup(self) -> int:
        """Remove expired entries. Returns count of evicted entries."""
        now = time.time()
        expired = [
            ccr_id for ccr_id, entry in self._index.items()
            if now - entry["stored_at"] > self.ttl_seconds
        ]
        for ccr_id in expired:
            self._evict(ccr_id)
        return len(expired)

    def _persist_entry(self, entry: dict[str, Any]) -> None:
        """Persist an entry to disk."""
        path = self.cache_dir / f"{entry['id']}.json"
        try:
            path.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
        except OSError as e:
            logger.warning("Failed to persist CCR entry %s: %s", entry["id"], e)

    def _evict(self, ccr_id: str) -> None:
        """Remove an entry from index and disk."""
        self._index.pop(ccr_id, None)
        path = self.cache_dir / f"{ccr_id}.json"
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    def _load_index(self) -> None:
        """Load existing entries from disk."""
        if not self.cache_dir.exists():
            return

        for path in self.cache_dir.glob("*.json"):
            try:
                entry = json.loads(path.read_text(encoding="utf-8"))
                ccr_id = entry.get("id", path.stem)
                self._index[ccr_id] = entry
            except (json.JSONDecodeError, OSError):
                continue

        logger.info("Loaded %d CCR entries from %s", len(self._index), self.cache_dir)
