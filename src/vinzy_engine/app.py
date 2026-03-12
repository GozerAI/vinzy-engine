"""FastAPI application factory for Vinzy-Engine."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from vinzy_engine.common.config import get_settings
from vinzy_engine.common.schemas import HealthResponse


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup
        from vinzy_engine.deps import get_db
        db = get_db()
        await db.init()
        await db.create_all()
        yield
        # Shutdown
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

    @app.get("/health", response_model=HealthResponse)
    async def health():
        return HealthResponse(version=settings.api_version)

    # Mount routers
    from vinzy_engine.licensing.router import router as licensing_router
    from vinzy_engine.activation.router import router as activation_router
    from vinzy_engine.usage.router import router as usage_router
    from vinzy_engine.webhooks.router import router as webhook_router

    prefix = settings.api_prefix
    app.include_router(licensing_router, prefix=prefix, tags=["licensing"])
    app.include_router(activation_router, prefix=prefix, tags=["activation"])
    app.include_router(usage_router, prefix=prefix, tags=["usage"])
    app.include_router(webhook_router, prefix=prefix, tags=["webhooks"])


    return app
