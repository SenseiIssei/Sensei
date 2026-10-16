"""The tool-output hook endpoints.

What matters most here is not how much they save but what they never do: break
the tool that called them, touch a file the model may edit next, or hand back
an output Claude Code would reject for not matching the tool's shape.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from sensei.compression.ccr import CCRStore
from sensei.compression.router import ContentRouter
from sensei.main import app
from sensei.routers import hooks

LOG = "\n".join(
    f"2026-10-16 12:00:{i % 60:02d} INFO worker-{i % 4} processed batch {i} ok in 12ms"
    for i in range(400)
)


@pytest.fixture
def recorded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """A private CCR store and a ledger stand-in that just remembers calls."""
    store = CCRStore(cache_dir=tmp_path / "ccr")
    monkeypatch.setattr(hooks, "_router", ContentRouter(ccr_store=store, enable_caching=True))
    calls: list[dict[str, Any]] = []

    class Tracker:
        def record(self, savings: dict[str, Any], **kw: Any) -> None:
            calls.append({**savings, **kw})

    monkeypatch.setattr(hooks, "get_savings_tracker", Tracker)
    return calls


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _claude(tool: str, response: Any) -> dict[str, Any]:
    return {
        "session_id": "s",
        "hook_event_name": "PostToolUse",
        "tool_name": tool,
        "tool_input": {},
        "tool_response": response,
        "tool_use_id": "t1",
    }


class TestClaudeCode:
    def test_bash_stdout_is_compressed_and_the_shape_kept(
        self, client: TestClient, recorded: list[dict[str, Any]]
    ) -> None:
        response = {"stdout": LOG, "stderr": "", "interrupted": False, "isImage": False}
        r = client.post("/hooks/claude/post-tool-use", json=_claude("Bash", response))
        assert r.status_code == 200
        out = r.json()["hookSpecificOutput"]
        assert out["hookEventName"] == "PostToolUse"
        updated = out["updatedToolOutput"]
        assert set(updated) == set(response), "Claude Code rejects a rewrite of another shape"
        assert len(updated["stdout"]) < len(LOG) / 5
        assert "mcp__sensei__sensei_retrieve(ccr_id=" in updated["stdout"]
        assert updated["interrupted"] is False
        (call,) = recorded
        assert call["tool"] == "Claude Code (hook)"
        assert call["tokens_saved"] > 0

    def test_the_original_is_retrievable(
        self, client: TestClient, recorded: list[dict[str, Any]]
    ) -> None:
        r = client.post("/hooks/claude/post-tool-use", json=_claude("Bash", {"stdout": LOG}))
        stdout = r.json()["hookSpecificOutput"]["updatedToolOutput"]["stdout"]
        ccr_id = stdout.rsplit('ccr_id="', 1)[1].split('"', 1)[0]
        store = hooks._pipeline().ccr_store
        assert store is not None and store.retrieve(ccr_id) == LOG

    @pytest.mark.parametrize("tool", ["Read", "Edit", "Write", "NotebookEdit", "MultiEdit"])
    def test_file_tools_are_never_touched(
        self, client: TestClient, recorded: list[dict[str, Any]], tool: str
    ) -> None:
        payload = _claude(tool, {"file": {"content": LOG}, "content": LOG, "stdout": LOG})
        assert client.post("/hooks/claude/post-tool-use", json=payload).json() == {}
        assert recorded == []

    def test_small_output_passes_through(
        self, client: TestClient, recorded: list[dict[str, Any]]
    ) -> None:
        payload = _claude("Bash", {"stdout": "ok\n", "stderr": ""})
        assert client.post("/hooks/claude/post-tool-use", json=payload).json() == {}

    def test_mcp_text_blocks_are_compressed_but_never_senseis_own(
        self, client: TestClient, recorded: list[dict[str, Any]]
    ) -> None:
        blocks = [{"type": "text", "text": LOG}]
        r = client.post("/hooks/claude/post-tool-use", json=_claude("mcp__github__logs", blocks))
        (block,) = r.json()["hookSpecificOutput"]["updatedToolOutput"]
        assert block["type"] == "text" and len(block["text"]) < len(LOG)

        own = _claude("mcp__sensei__sensei_retrieve", blocks)
        assert client.post("/hooks/claude/post-tool-use", json=own).json() == {}

    def test_glob_keeps_its_shape_and_marks_the_cut(
        self, client: TestClient, recorded: list[dict[str, Any]]
    ) -> None:
        names = [f"src/module_{i}/file_{i}.py" for i in range(1000)]
        response = {"filenames": names, "durationMs": 3, "numFiles": 1000, "truncated": False}
        r = client.post("/hooks/claude/post-tool-use", json=_claude("Glob", response))
        updated = r.json()["hookSpecificOutput"]["updatedToolOutput"]
        assert updated["truncated"] is True
        assert updated["numFiles"] == 1000
        assert len(updated["filenames"]) < 1000
        assert "sensei_retrieve" in updated["filenames"][-1]

    def test_a_crash_inside_sensei_fails_open(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(*_a: Any, **_k: Any) -> None:
            raise RuntimeError("compressor exploded")

        monkeypatch.setattr(hooks, "shrink", boom)
        r = client.post("/hooks/claude/post-tool-use", json=_claude("Bash", {"stdout": LOG}))
        assert r.status_code == 200 and r.json() == {}

    def test_garbage_is_an_empty_answer_not_an_error(self, client: TestClient) -> None:
        r = client.post("/hooks/claude/post-tool-use", content=b"not json")
        assert r.status_code == 200 and r.json() == {}

    def test_a_web_page_cannot_use_it(self, client: TestClient) -> None:
        payload = _claude("Bash", {"stdout": LOG})
        r = client.post(
            "/hooks/claude/post-tool-use", json=payload, headers={"Origin": "https://evil.example"}
        )
        assert r.status_code == 403

    def test_switched_off_by_setting(
        self,
        client: TestClient,
        recorded: list[dict[str, Any]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(hooks.settings, "hook_compression", False)
        r = client.post("/hooks/claude/post-tool-use", json=_claude("Bash", {"stdout": LOG}))
        assert r.json() == {}


def test_copilot_gets_a_modified_result(client: TestClient, recorded: list[dict[str, Any]]) -> None:
    payload = {
        "toolName": "bash",
        "toolArgs": "{}",
        "toolResult": {"resultType": "success", "textResultForLlm": LOG},
    }
    out = client.post("/hooks/copilot/post-tool-use", json=payload).json()
    assert out["modifiedResult"]["resultType"] == "success"
    assert len(out["modifiedResult"]["textResultForLlm"]) < len(LOG)
    assert recorded[0]["tool"] == "Copilot CLI (hook)"

    payload["toolName"] = "view"
    assert client.post("/hooks/copilot/post-tool-use", json=payload).json() == {}


def test_gemini_replaces_through_the_deny_reason(
    client: TestClient, recorded: list[dict[str, Any]]
) -> None:
    payload = {
        "hook_event_name": "AfterTool",
        "tool_name": "run_shell_command",
        "tool_response": {"llmContent": LOG, "returnDisplay": "..."},
    }
    out = client.post("/hooks/gemini/after-tool", json=payload).json()
    assert out["decision"] == "deny"
    assert len(out["reason"]) < len(LOG)

    payload["tool_response"] = {"llmContent": LOG, "error": "exit 1"}
    assert client.post("/hooks/gemini/after-tool", json=payload).json() == {}


def test_cursor_only_rewrites_mcp_tools(client: TestClient, recorded: list[dict[str, Any]]) -> None:
    output = json.dumps({"content": [{"type": "text", "text": LOG}]})
    out = client.post(
        "/hooks/cursor/post-tool-use",
        json={"tool_name": "MCP:github-logs", "tool_output": output},
    ).json()
    text = out["updated_mcp_tool_output"]["content"][0]["text"]
    assert len(text) < len(LOG)

    shell = {"tool_name": "Shell", "tool_output": output}
    assert client.post("/hooks/cursor/post-tool-use", json=shell).json() == {}


def test_generic_endpoint_for_plugins(client: TestClient, recorded: list[dict[str, Any]]) -> None:
    out = client.post(
        "/hooks/compress",
        json={"tool": "bash", "text": LOG},
        headers={"X-Sensei-Client": "opencode (plugin)"},
    ).json()
    assert len(out["text"]) < len(LOG)
    assert recorded[0]["tool"] == "opencode (plugin)"
    assert client.post("/hooks/compress", json={"tool": "read", "text": LOG}).json() == {}
