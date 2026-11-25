from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import threading
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any

from sensei.config import settings

logger = logging.getLogger(__name__)

# Ids become file names. Ours are hex hashes or UUIDs; one that comes from a
# model can be anything.
_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")

# Recently used entries kept in memory, per process. Also what keeps a marker
# working when the disk refused the write.
_HOT_BYTES = 8 * 1024 * 1024

# The directory is swept for expired entries on the first write of a process
# and then once per this many: an editor that only runs `sensei mcp` has no
# server, and so no purge loop, to do it.
_SWEEP_EVERY = 200


class CCRStore:
    """Compressed Cache & Retrieve — stores originals for on-demand retrieval.

    When content is compressed, the original is kept here under an id. If the
    model needs the full text, it asks for it by that id.

    One JSON file per entry in a directory every Sensei process on the machine
    shares: the gateway, the hooks and each editor's `sensei mcp`. The files are
    the store. Nothing is read when it is opened, an entry written by another
    process is there at once, and memory holds a few megabytes of recent
    entries however many there are on disk. It used to load every entry of the
    last day into every process and never let go of it.
    """

    def __init__(self, cache_dir: Path | str | None = None, ttl_hours: int | None = None):
        self.cache_dir = Path(cache_dir) if cache_dir is not None else settings.ccr_cache_path
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        ttl = ttl_hours if ttl_hours is not None else settings.ccr_ttl_hours
        self.ttl_seconds = ttl * 3600
        self._lock = threading.Lock()
        self._hot: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._hot_bytes = 0
        # id -> (original size, compressed size) of what this process stored.
        self._sizes: dict[str, tuple[int, int]] = {}
        self._writes = 0

    # ---- storing ------------------------------------------------------------

    def store(
        self,
        original: str,
        compressed: str,
        content_type: str = "text",
        metadata: dict[str, Any] | None = None,
        ccr_id: str | None = None,
    ) -> str:
        """Store an original and return a CCR ID for retrieval.

        ``ccr_id`` is the id a marker in ``compressed`` already points at (the
        router derives it from the original's hash, so the same input always
        compresses to the same bytes). Storing the same original again under
        the same id just refreshes the entry.
        """
        ccr_id = ccr_id or str(uuid.uuid4())
        entry = {
            "id": ccr_id,
            "original": original,
            "compressed": compressed,
            "content_type": content_type,
            "stored_at": time.time(),
            "metadata": metadata or {},
        }
        with self._lock:
            sweep = self._writes % _SWEEP_EVERY == 0
            self._writes += 1
            self._sizes[ccr_id] = (len(original), len(compressed))
        if sweep:
            self.cleanup()
        self._keep_hot(entry)
        self._persist_entry(entry)
        return ccr_id

    # ---- reading ------------------------------------------------------------

    def retrieve(self, ccr_id: str) -> str | None:
        """Retrieve the original content by CCR ID."""
        entry = self._live(ccr_id)
        return entry["original"] if entry else None

    def retrieve_compressed(self, ccr_id: str) -> str | None:
        """The compressed form, for paging through a view too long to send whole."""
        entry = self._live(ccr_id)
        return entry["compressed"] if entry else None

    def get_info(self, ccr_id: str) -> dict[str, Any] | None:
        """Get metadata about a CCR entry."""
        entry = self._get(ccr_id)
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
        """Return cache statistics.

        Counts and disk use are the whole store's. The byte sums are for what
        this process stored: knowing the others would mean reading every file.
        """
        now = time.time()
        files = self._files()
        present = {ccr_id for ccr_id, _ in files}
        with self._lock:
            self._sizes = {k: v for k, v in self._sizes.items() if k in present}
            original = sum(o for o, _ in self._sizes.values())
            compressed = sum(c for _, c in self._sizes.values())
        return {
            "total_entries": len(files),
            "active_entries": sum(1 for _, st in files if now - st.st_mtime <= self.ttl_seconds),
            "disk_bytes": sum(st.st_size for _, st in files),
            "total_original_bytes": original,
            "total_compressed_bytes": compressed,
            "space_saved_bytes": original - compressed,
        }

    # ---- housekeeping -------------------------------------------------------

    def cleanup(self) -> int:
        """Remove expired entries, then the oldest until the store fits its limit."""
        now = time.time()
        evicted = 0
        kept: list[tuple[float, int, str]] = []
        for ccr_id, stat in self._files():
            if now - stat.st_mtime > self.ttl_seconds:
                self._evict(ccr_id)
                evicted += 1
            else:
                kept.append((stat.st_mtime, stat.st_size, ccr_id))
        limit = max(1, settings.ccr_max_mb) * 1024 * 1024
        total = sum(size for _, size, _ in kept)
        for _, size, ccr_id in sorted(kept):
            if total <= limit:
                break
            self._evict(ccr_id)
            total -= size
            evicted += 1
        return evicted

    # ---- internals ----------------------------------------------------------

    def _live(self, ccr_id: str) -> dict[str, Any] | None:
        entry = self._get(ccr_id)
        if entry is None:
            return None
        if time.time() - entry["stored_at"] > self.ttl_seconds:
            self._evict(ccr_id)
            return None
        return entry

    def _get(self, ccr_id: str) -> dict[str, Any] | None:
        with self._lock:
            entry = self._hot.get(ccr_id)
            if entry is not None:
                self._hot.move_to_end(ccr_id)
                return entry
        return self._read(ccr_id)

    def _read(self, ccr_id: str) -> dict[str, Any] | None:
        if not isinstance(ccr_id, str) or not _ID.fullmatch(ccr_id):
            return None
        try:
            entry = json.loads((self.cache_dir / f"{ccr_id}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(entry, dict) or not {"original", "compressed", "stored_at"} <= set(entry):
            return None
        return {"id": ccr_id, "content_type": "text", **entry}

    def _files(self) -> list[tuple[str, os.stat_result]]:
        out = []
        with contextlib.suppress(OSError), os.scandir(self.cache_dir) as found:
            for item in found:
                if item.name.endswith(".json"):
                    with contextlib.suppress(OSError):
                        out.append((item.name[:-5], item.stat()))
        return out

    def _keep_hot(self, entry: dict[str, Any]) -> None:
        size = len(entry["original"]) + len(entry["compressed"])
        with self._lock:
            self._drop_hot(entry["id"])
            self._hot[entry["id"]] = entry
            self._hot_bytes += size
            while self._hot_bytes > _HOT_BYTES and len(self._hot) > 1:
                self._drop_hot(next(iter(self._hot)))

    def _drop_hot(self, ccr_id: str) -> None:
        entry = self._hot.pop(ccr_id, None)
        if entry is not None:
            self._hot_bytes -= len(entry["original"]) + len(entry["compressed"])

    def _persist_entry(self, entry: dict[str, Any]) -> None:
        """Write an entry so that another process sees all of it or none of it."""
        if not _ID.fullmatch(entry["id"]):
            logger.warning("Not persisting a CCR entry with an unusable id")
            return
        try:
            data = json.dumps(entry, ensure_ascii=False).encode("utf-8")
        except UnicodeEncodeError:  # half a surrogate pair: keep it as an escape
            data = json.dumps(entry).encode("ascii")
        path = self.cache_dir / f"{entry['id']}.json"
        partial = self.cache_dir / f"{entry['id']}.{os.getpid()}-{threading.get_ident()}.tmp"
        try:
            # Originals are tool output: source, logs, whatever a command said.
            fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.replace(partial, path)
        except OSError as e:
            # On Windows the rename fails while a reader has the file open. The
            # entry under that id is the same original, so there is no loss.
            with contextlib.suppress(OSError):
                partial.unlink(missing_ok=True)
            if not path.exists():
                logger.warning("Failed to persist CCR entry %s: %s", entry["id"], e)

    def _evict(self, ccr_id: str) -> None:
        """Remove an entry from memory and disk."""
        with self._lock:
            self._drop_hot(ccr_id)
        if _ID.fullmatch(ccr_id):
            with contextlib.suppress(OSError):
                (self.cache_dir / f"{ccr_id}.json").unlink(missing_ok=True)
