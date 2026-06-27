from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from sensei.agents.memory import MemoryStore
from sensei.agents.tools import ToolRegistry, retrieve_original_tool
from sensei.compression.ccr import CCRStore
from sensei.compression.router import ContentRouter
from sensei.config import settings
from sensei.routers.chat import init_chat_deps
from sensei.routers.conversations import init_conversations_deps
from sensei.routers.gateway import init_gateway_deps
from sensei.routers.stats import init_stats_deps
from sensei.security.auth import AuthMiddleware
from sensei.security.rate_limit import rate_limiter
from sensei.security.sessions import SessionManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

# Optional rotating file log for the background server.
if settings.log_file:
    from logging.handlers import RotatingFileHandler
    from pathlib import Path as _Path

    _Path(settings.log_file).expanduser().parent.mkdir(parents=True, exist_ok=True)
    _fh = RotatingFileHandler(
        settings.log_file, maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )
    _fh.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s"))
    for _name in ("", "uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(_name).addHandler(_fh)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Sensei",
    description="Self-hosted AI workspace with token compression, powered by GLM-5.2",
    version="0.1.0",
    license_info={"name": "MIT"},
)

# Global session manager
session_manager: SessionManager | None = None
_purge_task: asyncio.Task | None = None


@app.on_event("startup")
async def startup() -> None:
    """Initialize shared components on startup."""
    global session_manager
    logger.info("Starting Sensei v0.1.0...")

    # Load encrypted API keys from the vault into live settings.
    from sensei.security.vault import get_vault

    applied = get_vault().apply_to_settings()
    if applied:
        logger.info("Loaded %d API key(s) from the encrypted vault", applied)

    # Initialize CCR store
    ccr_store = CCRStore()

    # Initialize compression pipeline
    content_router = ContentRouter(ccr_store=ccr_store, enable_caching=True)

    # Initialize memory
    memory = MemoryStore()

    # Initialize session manager
    session_manager = SessionManager()

    # Initialize tool registry
    tools = ToolRegistry()
    tools.register(retrieve_original_tool(content_router))

    # Wire dependencies into routers
    init_chat_deps(memory=memory, tools=tools, router_c=content_router)
    init_conversations_deps(memory=memory)
    init_gateway_deps(content_router=content_router)
    init_stats_deps(ccr_store=ccr_store)

    # Data auto-purge background loop.
    global _purge_task
    if settings.purge_interval_minutes > 0:
        from sensei.purge import purge_expired

        async def _purge_loop() -> None:
            while True:
                try:
                    purge_expired()
                except Exception as exc:  # noqa: BLE001
                    logger.debug("purge loop error: %s", exc)
                await asyncio.sleep(max(60, settings.purge_interval_minutes * 60))

        _purge_task = asyncio.create_task(_purge_loop())

    logger.info(
        "Sensei initialized — compression: %s, memory: %s, auth: %s, rate_limit: %s",
        settings.compression_enabled,
        settings.memory_enabled,
        settings.auth_enabled,
        settings.rate_limit_enabled,
    )


@app.on_event("shutdown")
async def shutdown() -> None:
    if session_manager:
        expired = session_manager.cleanup_expired()
        logger.info("Cleaned up %d expired sessions", expired)
    if _purge_task:
        _purge_task.cancel()
    from sensei.routers.gateway import close_clients

    await close_clients()
    logger.info("Sensei shutting down...")


# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth middleware
app.add_middleware(AuthMiddleware)


# Rate limiting middleware
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if not settings.rate_limit_enabled:
        return await call_next(request)

    # Skip rate limiting for health checks and docs
    path = request.url.path
    if path in ("/", "/health", "/docs", "/openapi.json", "/redoc"):
        return await call_next(request)

    client_id = request.client.host if request.client else "unknown"
    allowed, remaining, retry_after = rate_limiter.check(client_id)

    if not allowed:
        return JSONResponse(
            status_code=429,
            content={"error": "Rate limit exceeded", "retry_after": retry_after},
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Limit": str(settings.rate_limit_requests),
            },
        )

    response = await call_next(request)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    response.headers["X-RateLimit-Limit"] = str(settings.rate_limit_requests)
    return response


# Health check
@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.1.0"}


# Register routers
from sensei.routers.audit import router as audit_router  # noqa: E402
from sensei.routers.auth import router as auth_router  # noqa: E402
from sensei.routers.chat import router as chat_router  # noqa: E402
from sensei.routers.conversations import router as conversations_router  # noqa: E402
from sensei.routers.gateway import router as gateway_router  # noqa: E402
from sensei.routers.maintenance import router as maintenance_router  # noqa: E402
from sensei.routers.models import router as models_router  # noqa: E402
from sensei.routers.rag import router as rag_router  # noqa: E402
from sensei.routers.settings import router as settings_router  # noqa: E402
from sensei.routers.stats import router as stats_router  # noqa: E402
from sensei.routers.webhook import router as webhook_router  # noqa: E402

app.include_router(audit_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(conversations_router, prefix="/api")
app.include_router(maintenance_router, prefix="/api")
app.include_router(models_router, prefix="/api")
app.include_router(rag_router, prefix="/api")
app.include_router(settings_router, prefix="/api")
app.include_router(stats_router, prefix="/api")
app.include_router(webhook_router, prefix="/api")

# OpenAI-compatible compression gateway — mounted at the root so clients can use
# http://<host>:<port>/v1 as a drop-in OpenAI base URL.
app.include_router(gateway_router)


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "name": "Sensei",
        "version": "0.1.0",
        "description": "Self-hosted AI workspace with token compression, powered by GLM-5.2",
        "docs": "/docs",
        "health": "/health",
    }
