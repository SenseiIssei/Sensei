"""Notice tools that appear while Sensei is running, and wire them up.

`sensei setup-tools` looks at the machine once, at install time. That is the
wrong moment for almost everything: the installer runs before the user has
installed Cursor, before they have signed into Claude Code for the first time
and so before its config file exists, and before whatever they install next
month. Every one of those is a tool that silently never routes through the
gateway, and the symptom is not an error — it is a savings figure that stays
lower than it should with nothing anywhere saying why.

So the check runs on a timer for as long as the server is up. It is cheap: a
handful of `shutil.which` calls and `Path.exists` checks, a few milliseconds,
against a poll interval measured in tens of seconds.

Three rules keep it from being intrusive:

* It only ever *adds*. Removing a tool's configuration is a decision, and
  decisions belong to the person, not to a timer.
* It respects `integrations.declined()`, so a tool disconnected by hand stays
  disconnected.
* Nothing is written when the configuration would not change, so a tool already
  pointing at the gateway is not rewritten sixty times an hour, and its file's
  mtime does not churn.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field

from . import integrations
from .config import settings

logger = logging.getLogger(__name__)


@dataclass
class Watcher:
    """State of the background scan, and the record the dashboard reads."""

    interval: float
    connected: list[str] = field(default_factory=list)
    scans: int = 0
    last_error: str | None = None
    _task: asyncio.Task[None] | None = None
    # Tools already seen installed. A tool moving from absent to present is the
    # event worth acting on and worth telling the user about; a tool that was
    # there at startup is just the status quo.
    _known: set[str] = field(default_factory=set)

    async def scan(self, *, first: bool = False) -> list[str]:
        """One pass. Returns the ids wired by this pass."""
        # Detection touches the filesystem, and applying it writes files. Both
        # are blocking, and the event loop here is also serving the gateway.
        current = await asyncio.to_thread(integrations.status)
        pending = {
            integration.id for integration, installed, wired in current if installed and not wired
        }
        appeared = pending - self._known if not first else pending
        self._known |= {i.id for i, installed, _ in current if installed}

        if not appeared:
            return []

        outcomes = await asyncio.to_thread(integrations.apply_all, only=appeared, automatic=True)
        wired = [o.tool_id for o in outcomes if o.status == "applied"]
        for tool_id in wired:
            if tool_id not in self.connected:
                self.connected.append(tool_id)
        if wired:
            logger.info("Connected to %s", ", ".join(sorted(set(wired))))
        return wired

    async def run(self) -> None:
        first = True
        while True:
            try:
                await self.scan(first=first)
                self.last_error = None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # A watcher is a convenience; the gateway is the product. An
                # unreadable config file or a permissions error must never be
                # able to take the server down with it, so this catches broadly
                # and keeps going.
                self.last_error = str(exc)
                logger.warning("Auto-connect scan failed: %s", exc)
            first = False
            self.scans += 1
            await asyncio.sleep(self.interval)


_watcher: Watcher | None = None


def current() -> Watcher | None:
    return _watcher


def start() -> Watcher | None:
    """Begin watching, if the setting allows it. Idempotent."""
    global _watcher
    if not settings.auto_connect:
        return None
    if _watcher is not None and _watcher._task is not None and not _watcher._task.done():
        return _watcher
    _watcher = _watcher or Watcher(interval=float(settings.auto_connect_interval_seconds))
    _watcher._task = asyncio.create_task(_watcher.run(), name="sensei-autowire")
    return _watcher


async def stop() -> None:
    if _watcher is None or _watcher._task is None:
        return
    _watcher._task.cancel()
    # Both arms are deliberate. CancelledError is the expected answer to the
    # cancel above; anything else is a scan that was already failing, and the
    # loop has logged it once. Neither is worth raising out of shutdown, where
    # it would replace whatever real reason the server is stopping for.
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await _watcher._task
    _watcher._task = None
