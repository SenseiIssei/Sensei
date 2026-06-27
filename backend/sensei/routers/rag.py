from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from sensei.audit import get_audit_log
from sensei.rag.store import get_store

router = APIRouter(prefix="/rag", tags=["rag"])


class DocIn(BaseModel):
    name: str
    content: str


class QueryIn(BaseModel):
    query: str
    k: int = 4


class RagChatIn(BaseModel):
    message: str
    k: int = 4
    model: str | None = None


class CrawlIn(BaseModel):
    url: str
    max_pages: int = 10
    max_depth: int = 2


@router.post("/documents")
async def add_document(doc: DocIn) -> dict[str, Any]:
    chunks = get_store().add_document(doc.name, doc.content)
    get_audit_log().record("rag.add", document=doc.name, chunks=chunks)
    return {"document": doc.name, "chunks": chunks}


@router.get("/documents")
async def list_documents() -> dict[str, Any]:
    return {"documents": get_store().list_documents()}


@router.delete("/documents/{name}")
async def delete_document(name: str) -> dict[str, Any]:
    removed = get_store().delete_document(name)
    return {"document": name, "removed_chunks": removed}


@router.post("/query")
async def query(q: QueryIn) -> dict[str, Any]:
    return {"results": get_store().search(q.query, q.k)}


@router.post("/crawl")
async def crawl(req: CrawlIn) -> dict[str, Any]:
    """Crawl a site (same-domain, capped) and index it into the knowledge base."""
    from sensei.agents.crawler import crawl_to_rag

    result = await crawl_to_rag(req.url, min(req.max_pages, 50), min(req.max_depth, 3))
    get_audit_log().record("rag.crawl", url=req.url, pages=result.get("pages_indexed", 0))
    return result


@router.post("/chat")
async def rag_chat(req: RagChatIn) -> dict[str, Any]:
    """Retrieve the most relevant chunks and answer grounded in them."""
    chunks = get_store().search(req.message, req.k)
    if not chunks:
        raise HTTPException(status_code=404, detail="No relevant documents — upload some first.")

    context = "\n\n".join(f"[{c['doc']}] {c['text']}" for c in chunks)
    system = (
        "Answer using ONLY the provided context. Cite the [document] name for "
        "facts you use. If the answer is not in the context, say you don't know."
    )
    # Reuse the chat handler — the (large) context prompt gets compressed too.
    from sensei.routers.chat import ChatRequest
    from sensei.routers.chat import chat as chat_handler

    full = f"Context:\n{context}\n\nQuestion: {req.message}"
    resp = await chat_handler(ChatRequest(message=full, model=req.model, system_prompt=system))
    get_audit_log().record("rag.chat", sources=[c["doc"] for c in chunks], tokens_saved=resp.tokens_saved)
    return {
        "answer": resp.message,
        "model": resp.model,
        "tokens_saved": resp.tokens_saved,
        "sources": [{"doc": c["doc"], "score": c["score"]} for c in chunks],
    }
