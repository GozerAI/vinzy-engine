"""FastAPI application factory for Vinzy-Engine."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from vinzy_engine.common.config import get_settings
from vinzy_engine.common.schemas import HealthResponse

import logging

_log = logging.getLogger("vinzy_engine.app")


def _try_import_router(mod_path, attr="router"):
    """Attempt to import a router module, returning None if stubbed."""
    try:
        import importlib
        mod = importlib.import_module(mod_path)
        return getattr(mod, attr)
    except ImportError:
        _log.info("Router %s not available (requires commercial license)", mod_path)
        return None


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

    # IP allowlist (must be outermost)
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

    # Community routers (always available)
    from vinzy_engine.licensing.router import router as licensing_router
    from vinzy_engine.activation.router import router as activation_router
    from vinzy_engine.usage.router import router as usage_router

    prefix = settings.api_prefix
    app.include_router(licensing_router, prefix=prefix, tags=["licensing"])
    app.include_router(activation_router, prefix=prefix, tags=["activation"])
    app.include_router(usage_router, prefix=prefix, tags=["usage"])

    # Pro/Enterprise routers (graceful degradation if stubbed)
    _optional = [
        ("vinzy_engine.tenants.router", "router", "tenants"),
        ("vinzy_engine.audit.router", "router", "audit"),
        ("vinzy_engine.anomaly.router", "router", "anomaly"),
        ("vinzy_engine.webhooks.router", "router", "webhooks"),
        ("vinzy_engine.provisioning.router", "router", "provisioning"),
    ]
    for mod_path, attr, label in _optional:
        r = _try_import_router(mod_path, attr)
        if r is not None:
            app.include_router(r, prefix=prefix, tags=[label])

    # Provisioning checkout router (optional)
    checkout = _try_import_router("vinzy_engine.provisioning.router", "checkout_router")
    if checkout is not None:
        app.include_router(checkout, prefix=prefix, tags=["checkout"])

    # Dashboard sub-application (optional)
    try:
        from vinzy_engine.dashboard.router import create_dashboard_app
        app.mount("/dashboard", create_dashboard_app())
    except ImportError:
        _log.info("Dashboard not available (requires commercial license)")

    return app
