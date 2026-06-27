"""Web + code tools for the agent.

- ``fetch_url``: SSRF-guarded HTTP GET that returns extracted text. Every redirect
  hop is re-validated; private/loopback/link-local hosts are refused.
- ``web_search``: Brave Search API (needs ``SENSEI_BRAVE_API_KEY``).
- ``run_python``: runs Python in an isolated subprocess with a timeout. OFF by
  default and NOT sandboxed — it executes on the host. Only enable on a machine
  you control (``SENSEI_CODE_EXEC_ENABLED=true``). Real isolation (Docker) is a
  future item.
"""
from __future__ import annotations

import asyncio
import html
import ipaddress
import re
import socket
import sys
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from sensei.agents.extract import extract_main_text, extract_pdf_text
from sensei.config import settings

_SCRIPT_STYLE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_HTML_TAG = re.compile(r"<[^>]+>")
_MAX_TEXT = 20_000


def _is_public_host(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = info[4][0]
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_reserved
            or addr.is_multicast
            or addr.is_unspecified
        ):
            return False
    return True


def _html_to_text(body: str) -> str:
    body = _SCRIPT_STYLE.sub(" ", body)
    body = _HTML_TAG.sub(" ", body)
    return re.sub(r"\s+", " ", html.unescape(body)).strip()


async def _fetch_core(url: str, max_chars: int = 200_000) -> dict[str, Any]:
    if not settings.web_fetch_enabled:
        return {"error": "Web fetch is disabled (set SENSEI_WEB_FETCH_ENABLED=true)."}
    async with httpx.AsyncClient(timeout=15.0) as client:
        for _ in range(4):  # follow redirects manually, re-validating each hop
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https") or not parsed.hostname:
                return {"error": "Only http(s) URLs are allowed."}
            if not _is_public_host(parsed.hostname):
                return {"error": "Refusing to fetch a private/local address (SSRF guard)."}
            try:
                resp = await client.get(
                    url, headers={"User-Agent": "SenseiBot/1.0"}, follow_redirects=False
                )
            except httpx.HTTPError as e:
                return {"error": f"fetch failed: {e}"}
            if resp.is_redirect and resp.headers.get("location"):
                url = urljoin(str(resp.url), resp.headers["location"])
                continue
            break
        else:
            return {"error": "too many redirects"}

    ctype = resp.headers.get("content-type", "")
    final = str(resp.url)
    if "pdf" in ctype or final.split("?")[0].lower().endswith(".pdf"):
        text = extract_pdf_text(resp.content)
    elif "html" in ctype or "<html" in resp.text[:1024].lower():
        text = extract_main_text(resp.text[:1_000_000])
    else:
        text = resp.text[:max_chars]
    return {"url": final, "status": resp.status_code, "content": text[:max_chars]}


async def fetch_url(url: str) -> dict[str, Any]:
    """Agent tool view — extracted content, capped for prompt budgets."""
    return await _fetch_core(url, max_chars=_MAX_TEXT)


async def web_search(query: str) -> dict[str, Any]:
    if not settings.brave_api_key:
        return {"error": "Web search not configured (set SENSEI_BRAVE_API_KEY); use fetch_url for known pages."}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": 5},
                headers={"X-Subscription-Token": settings.brave_api_key, "Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as e:
        return {"error": f"search failed: {e}"}
    results = [
        {"title": r.get("title"), "url": r.get("url"), "snippet": _html_to_text(r.get("description", ""))}
        for r in (data.get("web", {}).get("results") or [])[:5]
    ]
    return {"query": query, "results": results}


async def run_python(code: str) -> dict[str, Any]:
    if not settings.code_exec_enabled:
        return {"error": "Code execution is disabled (SENSEI_CODE_EXEC_ENABLED). It is not sandboxed — runs on the host."}
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-I", "-c", code,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=settings.code_exec_timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return {"error": f"timed out after {settings.code_exec_timeout}s"}
    return {
        "stdout": out.decode("utf-8", "replace")[:8000],
        "stderr": err.decode("utf-8", "replace")[:4000],
        "exit_code": proc.returncode,
    }
