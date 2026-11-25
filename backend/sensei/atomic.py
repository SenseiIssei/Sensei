"""Put a file or directory in place whole, or not at all.

Several Sensei processes start at once (a server, a hook, an MCP server per
editor) and look at the same files. Nothing may be visible half-written, and of
two that create the same thing one wins and the other uses the winner's.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
from pathlib import Path


def publish_new(data: bytes, target: Path) -> bool:
    """Create ``target`` with ``data``, readable by its owner only.

    False if it already exists. Raises OSError if it cannot be written.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    partial = Path(name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        return _take(partial, target)
    finally:
        with contextlib.suppress(OSError):
            partial.unlink(missing_ok=True)


def copy_new(source: Path, target: Path) -> bool:
    """Copy a file or directory to ``target`` unless something is there."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
        try:
            shutil.copytree(source, staging / "copy")
            if target.exists():
                return False
            # Renaming onto a directory fails on Windows, and on POSIX unless it
            # is empty, in which case there was nothing to lose.
            os.rename(staging / "copy", target)
            return True
        except FileExistsError:
            return False
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    return publish_new(source.read_bytes(), target)


def _take(partial: Path, target: Path) -> bool:
    try:
        os.link(partial, target)  # fails if it exists, everywhere
        return True
    except FileExistsError:
        return False
    except OSError:  # a file system without hard links (FAT, some shares)
        if target.exists():
            return False
        if os.name == "nt":
            try:
                os.rename(partial, target)  # refuses to overwrite on Windows
            except FileExistsError:
                return False
        else:
            os.replace(partial, target)
        return True
