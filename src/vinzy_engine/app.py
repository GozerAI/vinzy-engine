"""FastAPI application factory for Vinzy-Engine."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response as StarletteResponse

from vinzy_engine.common.config import get_settings
from vinzy_engine.common.schemas import HealthResponse

logger = logging.getLogger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: StarletteRequest, call_next):
        response: StarletteResponse = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
        return response


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup
        from vinzy_engine.deps import get_db, get_audit_service
        db = get_db()
        await db.init()
        await db.create_all()

        # Start database health monitoring
        from vinzy_engine.common.health import get_health_monitor
        health_monitor = get_health_monitor()
        health_monitor.start(db)

        # Start batch audit writer
        from vinzy_engine.audit.batch import get_batch_audit_writer
        batch_writer = get_batch_audit_writer()
        batch_writer._audit_service = get_audit_service()
        batch_writer._db_manager = db
        batch_writer.start()

        # Start background processors
        from vinzy_engine.background import (
            get_hard_delete_processor,
            get_expiration_processor,
            get_webhook_delivery_processor,
            get_stripe_processor,
        )
        get_hard_delete_processor().start(db)
        get_expiration_processor().start(db)
        get_webhook_delivery_processor().start(db)
        get_stripe_processor().start()

        yield

        # Shutdown — stop background tasks
        await get_hard_delete_processor().stop()
        await get_expiration_processor().stop()
        await get_webhook_delivery_processor().stop()
        await get_stripe_processor().stop()
        await batch_writer.stop()
        await health_monitor.stop()
        await db.close()

    app = FastAPI(
        title=settings.api_title,
        version=settings.api_version,
        lifespan=lifespan,
    )

    # IP allowlist (must be outermost — evaluated first)
    if settings.ip_allowlist_enabled and settings.ip_allowlist:
        from vinzy_engine.common.ip_filter import IPAllowlistMiddleware
        app.add_middleware(IPAllowlistMiddleware, allowlist=settings.ip_allowlist)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Rate limiting
    if settings.rate_limit_enabled:
        from slowapi import _rate_limit_exceeded_handler
        from slowapi.errors import RateLimitExceeded
        from vinzy_engine.common.rate_limiting import limiter

        app.state.limiter = limiter
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # Response compression (gzip/brotli)
    from vinzy_engine.common.compression import CompressionMiddleware
    app.add_middleware(CompressionMiddleware)

    @app.get("/health", response_model=HealthResponse)
    async def health():
        return HealthResponse(version=settings.api_version)

    @app.get("/health/ready")
    async def health_ready():
        """Kubernetes readiness probe — returns 503 until DB is healthy."""
        from fastapi import Response
        from vinzy_engine.common.health import get_health_monitor
        monitor = get_health_monitor()
        if monitor.is_healthy:
            return {"status": "ready", "service": "vinzy"}
        return Response(status_code=503, content='{"status":"not_ready"}', media_type="application/json")

    @app.get("/health/db")
    async def health_db():
        """Database connection health with detailed metrics."""
        from vinzy_engine.common.health import get_health_monitor
        monitor = get_health_monitor()
        status = monitor.to_dict()
        status_code = 200 if monitor.is_healthy else 503
        return status

    # Mount routers
    from vinzy_engine.licensing.router import router as licensing_router
    from vinzy_engine.activation.router import router as activation_router
    from vinzy_engine.usage.router import router as usage_router
    from vinzy_engine.tenants.router import router as tenant_router
    from vinzy_engine.audit.router import router as audit_router
    from vinzy_engine.anomaly.router import router as anomaly_router
    from vinzy_engine.webhooks.router import router as webhook_router

    prefix = settings.api_prefix
    app.include_router(licensing_router, prefix=prefix, tags=["licensing"])
    app.include_router(activation_router, prefix=prefix, tags=["activation"])
    app.include_router(usage_router, prefix=prefix, tags=["usage"])
    app.include_router(tenant_router, prefix=prefix, tags=["tenants"])
    app.include_router(audit_router, prefix=prefix, tags=["audit"])
    app.include_router(anomaly_router, prefix=prefix, tags=["anomaly"])
    app.include_router(webhook_router, prefix=prefix, tags=["webhooks"])

    # Mount dashboard sub-application
    from vinzy_engine.dashboard.router import create_dashboard_app
    app.mount("/dashboard", create_dashboard_app())

    return app
