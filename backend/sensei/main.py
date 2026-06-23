from __future__ import annotations

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
from sensei.routers.stats import init_stats_deps
from sensei.security.auth import AuthMiddleware
from sensei.security.rate_limit import rate_limiter
from sensei.security.sessions import SessionManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Sensei",
    description="Self-hosted AI workspace with token compression, powered by GLM-5.2",
    version="0.1.0",
    license_info={"name": "MIT"},
)

# Global session manager
session_manager: SessionManager | None = None


@app.on_event("startup")
async def startup() -> None:
    """Initialize shared components on startup."""
    global session_manager
    logger.info("Starting Sensei v0.1.0...")

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
    init_stats_deps(ccr_store=ccr_store)

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
from sensei.routers.chat import router as chat_router  # noqa: E402
from sensei.routers.models import router as models_router  # noqa: E402
from sensei.routers.stats import router as stats_router  # noqa: E402

app.include_router(chat_router, prefix="/api")
app.include_router(models_router, prefix="/api")
app.include_router(stats_router, prefix="/api")


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "name": "Sensei",
        "version": "0.1.0",
        "description": "Self-hosted AI workspace with token compression, powered by GLM-5.2",
        "docs": "/docs",
        "health": "/health",
    }
