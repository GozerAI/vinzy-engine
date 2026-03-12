"""Shared test fixtures for Vinzy-Engine."""

import os
import pytest
from httpx import ASGITransport, AsyncClient


HMAC_KEY = "test-hmac-key-for-unit-tests"
API_KEY = "test-admin-api-key"
SUPER_ADMIN_KEY = "test-super-admin-key"


@pytest.fixture
def hmac_key():
    return HMAC_KEY


@pytest.fixture
def api_key():
    return API_KEY


@pytest.fixture
def app():
    """Create a test app with in-memory DB."""
    os.environ["VINZY_DB_URL"] = "sqlite+aiosqlite://"
    os.environ["VINZY_HMAC_KEY"] = HMAC_KEY
    os.environ["VINZY_API_KEY"] = API_KEY
    os.environ["VINZY_SUPER_ADMIN_KEY"] = SUPER_ADMIN_KEY

    # Clear caches and singletons so new env vars take effect
    from vinzy_engine.common.config import get_settings
    get_settings.cache_clear()

    from vinzy_engine.deps import reset_singletons
    reset_singletons()

    # Reset rate limiter state so tests don't hit limits from previous runs
    from vinzy_engine.common.rate_limiting import limiter
    limiter.reset()

    from vinzy_engine.app import create_app
    return create_app()


@pytest.fixture
async def client(app):
    # Manually init DB since ASGITransport doesn't run lifespan
    from vinzy_engine.deps import get_db
    db = get_db()
    await db.init()
    await db.create_all()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    await db.close()


@pytest.fixture
def admin_headers():
    return {"X-Vinzy-Api-Key": API_KEY}


@pytest.fixture
def super_admin_headers():
    return {"X-Vinzy-Api-Key": SUPER_ADMIN_KEY}
