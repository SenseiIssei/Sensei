from __future__ import annotations

import json

from fastapi.testclient import TestClient

import sensei.agents.runner as runner
import sensei.agents.toolbox as toolbox
from sensei.agents.runner import run_agent
from sensei.config import settings
from sensei.main import app
from sensei.models.base import ChatCompletion, Role, UsageStats


class _ScriptedProvider:
    def __init__(self, responses):
        self._responses = list(responses)

    async def chat(self, messages, model=None, temperature=0.7, max_tokens=4096, stream=False):
        content = self._responses.pop(0)
        return ChatCompletion(id="x", model="fake", content=content, role=Role.assistant, usage=UsageStats())


# ─── toolbox sandboxing ───

async def test_read_file_within_sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "agent_root", str(tmp_path))
    (tmp_path / "hello.txt").write_text("hi there", encoding="utf-8")
    res = await toolbox.read_file("hello.txt")
    assert res["content"] == "hi there"


async def test_read_file_rejects_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "agent_root", str(tmp_path))
    assert "error" in await toolbox.read_file("../../etc/passwd")
    assert "error" in await toolbox.read_file("/etc/passwd")


async def test_list_and_search(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "agent_root", str(tmp_path))
    (tmp_path / "a.txt").write_text("alpha beta\ngamma line", encoding="utf-8")
    (tmp_path / "b.txt").write_text("delta", encoding="utf-8")
    listed = await toolbox.list_files(".")
    assert "a.txt" in listed["entries"] and "b.txt" in listed["entries"]
    found = await toolbox.search_files("gamma")
    assert any(m["file"] == "a.txt" for m in found["matches"])


# ─── ReAct loop ───

async def test_run_agent_uses_tool_then_answers(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "agent_root", str(tmp_path))
    (tmp_path / "data.txt").write_text("the secret is 42", encoding="utf-8")
    provider = _ScriptedProvider([
        json.dumps({"thought": "read it", "tool": "read_file", "args": {"path": "data.txt"}}),
        json.dumps({"thought": "done", "answer": "The secret is 42."}),
    ])
    result = await run_agent("what is the secret", provider=provider, max_steps=4)
    assert result["stopped"] == "done"
    assert result["answer"] == "The secret is 42."
    assert len(result["steps"]) == 1
    assert result["steps"][0]["tool"] == "read_file"
    assert "42" in str(result["steps"][0]["result"])


async def test_run_agent_hits_step_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "agent_root", str(tmp_path))
    provider = _ScriptedProvider([json.dumps({"tool": "list_files", "args": {}})] * 5)
    result = await run_agent("loop forever", provider=provider, max_steps=2)
    assert result["stopped"] == "max_steps"
    assert len(result["steps"]) == 2


# ─── endpoints ───

def test_agent_tools_endpoint():
    client = TestClient(app)
    names = {t["name"] for t in client.get("/api/agent/tools").json()["tools"]}
    assert {"read_file", "list_files", "search_files", "rag_search"} <= names


def test_agent_run_endpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "agent_root", str(tmp_path))
    (tmp_path / "f.txt").write_text("contents here", encoding="utf-8")

    async def _fake_get_provider():
        return _ScriptedProvider([
            json.dumps({"tool": "list_files", "args": {}}),
            json.dumps({"answer": "I listed the files."}),
        ])

    monkeypatch.setattr(runner, "get_provider", _fake_get_provider)
    client = TestClient(app)
    data = client.post("/api/agent/run", json={"task": "list files"}).json()
    assert data["stopped"] == "done"
    assert data["answer"] == "I listed the files."
    assert data["steps"][0]["tool"] == "list_files"
