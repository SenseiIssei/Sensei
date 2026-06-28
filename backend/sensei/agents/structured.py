"""Structured extraction — pull schema'd data out of web pages.

Two modes:
- ``extract_tables`` / ``extract_tables_from_url``: deterministic, zero-dependency
  HTML ``<table>`` parsing into header-keyed row objects.
- ``extract_structured``: provider-backed extraction of an arbitrary list of
  fields from a page's main text into a JSON object (keys = requested fields).
"""
from __future__ import annotations

import html as _html
import re
from typing import Any

_TABLE = re.compile(r"<table\b[^>]*>(.*?)</table>", re.DOTALL | re.IGNORECASE)
_ROW = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
_CELL = re.compile(r"<(t[hd])\b[^>]*>(.*?)</\1>", re.DOTALL | re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")


def _cell_text(cell: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(_TAG.sub(" ", cell))).strip()


def extract_tables(html: str) -> list[dict[str, Any]]:
    """Parse HTML ``<table>`` elements into header-keyed rows (nested tables ignored)."""
    tables: list[dict[str, Any]] = []
    for body in _TABLE.findall(html):
        header: list[str] = []
        rows: list[Any] = []
        for cells in (_CELL.findall(row) for row in _ROW.findall(body)):
            if not cells:
                continue
            texts = [_cell_text(c) for _, c in cells]
            is_header = all(tag.lower() == "th" for tag, _ in cells)
            if is_header and not header:
                header = texts
            elif header:
                rows.append(dict(zip(header, texts)))
            else:
                rows.append(texts)
        if header or rows:
            tables.append({"headers": header, "rows": rows})
    return tables


async def extract_tables_from_url(url: str) -> dict[str, Any]:
    from sensei.agents.webtools import _fetch_core

    fetched = await _fetch_core(url, max_chars=1_000_000, extract=False)
    if "error" in fetched:
        return fetched
    return {"url": fetched["url"], "tables": extract_tables(fetched["content"])}


async def extract_structured(
    url: str, fields: list[str], provider: Any = None
) -> dict[str, Any]:
    """Fetch a page and have the model fill the requested fields as JSON."""
    from sensei.agents.runner import _extract_json
    from sensei.agents.webtools import _fetch_core
    from sensei.models.base import ChatMessage, Role
    from sensei.models.registry import get_provider

    fields = [f for f in (fields or []) if f]
    if not fields:
        return {"error": "No fields requested."}
    fetched = await _fetch_core(url, max_chars=40_000)
    if "error" in fetched:
        return fetched

    provider = provider or await get_provider()
    system = (
        "Extract the requested fields from the page text. Return ONLY a JSON object "
        "whose keys are exactly the requested field names; use null when a field is "
        "absent. No prose, no markdown fences."
    )
    user = f"Fields: {', '.join(fields)}\n\nPage text:\n{fetched['content'][:30_000]}"
    completion = await provider.chat(
        messages=[
            ChatMessage(role=Role.system, content=system),
            ChatMessage(role=Role.user, content=user),
        ],
        max_tokens=1024,
    )
    data = _extract_json(completion.content) or {}
    return {"url": fetched["url"], "fields": {f: data.get(f) for f in fields}}
