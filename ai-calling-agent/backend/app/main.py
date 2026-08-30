from __future__ import annotations

import time
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app import __version__
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger, request_id_ctx
from app.db.session import engine

configure_logging(level=settings.log_level, json_output=settings.log_json)
log = get_logger("app")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    log.info(
        "app.startup",
        app=settings.app_name,
        environment=settings.app_env,
        version=__version__,
    )
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        log.info("db.connected")
    except Exception as exc:
        # Don't refuse to boot: the API should come up and report degraded health
        # rather than crash-loop while Postgres is still starting.
        log.error("db.unavailable_at_startup", error=str(exc))

    yield

    await engine.dispose()
    log.info("app.shutdown")


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="Low-cost AI calling agent platform",
    openapi_url=None if settings.is_production else "/openapi.json",
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None,
    lifespan=lifespan,
)

# Behind Render/Railway/Fly the app sits behind a proxy, so the scheme and
# client IP arrive in X-Forwarded-* headers. Without this, generated URLs come
# out as http:// and rate limiting sees the proxy's address.
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)


@app.middleware("http")
async def request_context(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
    token = request_id_ctx.set(request_id)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    finally:
        request_id_ctx.reset(token)

    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    response.headers["X-Request-ID"] = request_id
    if request.url.path not in {"/api/v1/health", "/health"}:
        log.info(
            "http.request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=duration_ms,
            request_id=request_id,
        )
    return response


register_exception_handlers(app)
app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {"app": settings.app_name, "version": __version__, "docs": "/docs"}
