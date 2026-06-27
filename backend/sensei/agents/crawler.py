"""Crawl-to-RAG — BFS a site, extract text, and index it into the RAG store.

Same-domain only, depth- and page-capped, robots.txt respected, SSRF-guarded on
every URL. Each page becomes a RAG document keyed by its URL (so answers can
cite live links). Built on the same guards as ``webtools.fetch_url``.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from sensei.agents.extract import extract_main_text
from sensei.agents.webtools import _is_public_host
from sensei.rag.store import get_store

_HREF = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
_UA = {"User-Agent": "SenseiBot/1.0"}


async def _robots_disallow(client: httpx.AsyncClient, base: str) -> list[str]:
    """Very small robots.txt parser — Disallow paths for '*' or SenseiBot."""
    try:
        resp = await client.get(base + "/robots.txt", timeout=10.0)
        if resp.status_code != 200:
            return []
    except httpx.HTTPError:
        return []
    disallow: list[str] = []
    applies = False
    for line in resp.text.splitlines():
        line = line.strip()
        if line.lower().startswith("user-agent:"):
            ua = line.split(":", 1)[1].strip().lower()
            applies = ua == "*" or "sensei" in ua
        elif applies and line.lower().startswith("disallow:"):
            path = line.split(":", 1)[1].strip()
            if path:
                disallow.append(path)
    return disallow


async def _fetch(client: httpx.AsyncClient, url: str) -> tuple[str, str] | None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    if not _is_public_host(parsed.hostname):
        return None
    try:
        resp = await client.get(url, headers=_UA, follow_redirects=True, timeout=15.0)
    except httpx.HTTPError:
        return None
    if "html" not in resp.headers.get("content-type", ""):
        return None
    return resp.text[:500_000], str(resp.url)


def _links(html: str, base: str, domain: str) -> list[str]:
    out: list[str] = []
    for href in _HREF.findall(html):
        u = urljoin(base, href).split("#")[0]
        p = urlparse(u)
        if p.scheme in ("http", "https") and p.netloc == domain:
            out.append(u)
    return out


async def crawl_to_rag(start_url: str, max_pages: int = 10, max_depth: int = 2) -> dict[str, Any]:
    parsed = urlparse(start_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return {"error": "Only http(s) URLs are allowed."}
    if not _is_public_host(parsed.hostname):
        return {"error": "Refusing to crawl a private/local address (SSRF guard)."}

    domain = parsed.netloc
    visited: set[str] = set()
    queue: list[tuple[str, int]] = [(start_url.split("#")[0], 0)]
    indexed: list[str] = []
    store = get_store()

    async with httpx.AsyncClient() as client:
        disallow = await _robots_disallow(client, f"{parsed.scheme}://{domain}")
        while queue and len(indexed) < max_pages:
            url, depth = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)
            if any(urlparse(url).path.startswith(d) for d in disallow):
                continue
            fetched = await _fetch(client, url)
            if fetched is None:
                continue
            html, final = fetched
            text = extract_main_text(html)
            if len(text) > 50:
                store.add_document(url, text)
                indexed.append(url)
            if depth < max_depth:
                for link in _links(html, final, domain):
                    if link not in visited:
                        queue.append((link, depth + 1))

    return {"start": start_url, "pages_indexed": len(indexed), "urls": indexed[:50]}
