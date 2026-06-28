from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from sensei.audit import get_audit_log

router = APIRouter(prefix="/extract", tags=["extract"])


class ExtractIn(BaseModel):
    url: str
    fields: list[str] | None = None
    tables: bool = False


@router.post("")
async def extract(req: ExtractIn) -> dict[str, Any]:
    """Pull structured data from a page: HTML tables, or model-extracted fields."""
    if req.tables:
        from sensei.agents.structured import extract_tables_from_url

        res = await extract_tables_from_url(req.url)
        if "error" in res:
            raise HTTPException(status_code=400, detail=res["error"])
        get_audit_log().record("extract.tables", url=req.url, tables=len(res["tables"]))
        return res

    if not req.fields:
        raise HTTPException(status_code=400, detail="Provide 'fields' to extract, or set tables=true.")
    from sensei.agents.structured import extract_structured

    res = await extract_structured(req.url, req.fields)
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    get_audit_log().record("extract.fields", url=req.url, fields=req.fields)
    return res
