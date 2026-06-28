from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from sensei.agents.runner import run_agent
from sensei.agents.toolbox import build_default_registry
from sensei.audit import get_audit_log
from sensei.config import settings

router = APIRouter(prefix="/agent", tags=["agent"])


class AgentRequest(BaseModel):
    task: str
    max_steps: int | None = None
    deep: bool = False


@router.get("/tools")
async def list_tools() -> dict[str, Any]:
    reg = build_default_registry()
    return {"tools": [{"name": t.name, "description": t.description} for t in reg.list()]}


@router.post("/run")
async def agent_run(req: AgentRequest) -> dict[str, Any]:
    cap = req.max_steps or (settings.agent_max_steps_deep if req.deep else settings.agent_max_steps)
    result = await run_agent(req.task, max_steps=cap)
    get_audit_log().record(
        "agent.run", steps=len(result["steps"]), stopped=result.get("stopped"), deep=req.deep
    )
    return result
