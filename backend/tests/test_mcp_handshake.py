"""The stdio handshake, driven over a real pipe against the installed SDK.

`pyproject.toml` caps the MCP SDK because GitHub Copilot CLI 1.0.98 could not
start the server under 2.3.0. The rest of the suite never opens a connection,
so it is green with any version, which makes a bump look safe when it is not.
These tests pin what a client needs: a plain `initialize`, and `initialize`
after a probe the server did not understand.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any

import pytest

pytest.importorskip("mcp")


def _converse(requests: list[dict[str, Any]], tmp_path) -> dict[int, dict[str, Any]]:
    """Run `sensei mcp`, send the requests one after the other, collect replies."""
    env = {
        **os.environ,
        "USERPROFILE": str(tmp_path),
        "HOME": str(tmp_path),
        "PYTHONUTF8": "1",
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "sensei.cli", "mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=env,
        cwd=tmp_path,
        text=True,
        encoding="utf-8",
    )
    replies: dict[int, dict[str, Any]] = {}
    try:
        assert proc.stdin is not None
        assert proc.stdout is not None
        for request in requests:
            proc.stdin.write(json.dumps({"jsonrpc": "2.0", **request}) + "\n")
            proc.stdin.flush()
            while "id" in request:
                line = proc.stdout.readline()
                assert line, "the server closed the connection"
                message = json.loads(line)
                if "id" in message:
                    replies[message["id"]] = message
                    break
    finally:
        proc.kill()
        proc.wait(timeout=10)
        proc.stdin.close()
        proc.stdout.close()
    return replies


_INITIALIZE = {
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-11-25",
        "capabilities": {},
        "clientInfo": {"name": "probe", "version": "1"},
    },
}


def test_initialize_works(tmp_path) -> None:
    replies = _converse(
        [
            {"id": 1, **_INITIALIZE},
            {"method": "notifications/initialized"},
            {"id": 2, "method": "tools/list"},
        ],
        tmp_path,
    )
    assert replies[1]["result"]["serverInfo"]["name"] == "sensei"
    names = {t["name"] for t in replies[2]["result"]["tools"]}
    assert {"sensei_compress", "sensei_retrieve", "sensei_stats"} <= names


def test_initialize_after_an_unknown_probe_works(tmp_path) -> None:
    """A client that tries something newer first must still get a session."""
    replies = _converse(
        [{"id": 1, "method": "server/discover", "params": {}}, {"id": 2, **_INITIALIZE}],
        tmp_path,
    )
    assert "error" in replies[1]
    assert "result" in replies[2], replies[2]
