from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from sensei.agents.runner import run_agent
from sensei.agents.toolbox import build_default_registry
from sensei.audit import get_audit_log

router = APIRouter(prefix="/agent", tags=["agent"])


class AgentRequest(BaseModel):
    task: str
    max_steps: int | None = None


@router.get("/tools")
async def list_tools() -> dict[str, Any]:
    reg = build_default_registry()
    return {"tools": [{"name": t.name, "description": t.description} for t in reg.list()]}


@router.post("/run")
async def agent_run(req: AgentRequest) -> dict[str, Any]:
    result = await run_agent(req.task, max_steps=req.max_steps)
    get_audit_log().record(
        "agent.run", steps=len(result["steps"]), stopped=result.get("stopped")
    )
    return result
