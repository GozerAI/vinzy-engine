"""Async database manager for Vinzy-Engine (single-DB)."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from vinzy_engine.common.config import VinzySettings, get_settings
from vinzy_engine.common.models import Base

# Import all model modules so Base.metadata is complete for create_all().
import vinzy_engine.tenants.models  # noqa: F401
import vinzy_engine.licensing.models  # noqa: F401
import vinzy_engine.activation.models  # noqa: F401
import vinzy_engine.usage.models  # noqa: F401
import vinzy_engine.audit.models  # noqa: F401
import vinzy_engine.anomaly.models  # noqa: F401
import vinzy_engine.webhooks.models  # noqa: F401


class DatabaseManager:
    """Manages a single async database engine."""

    def __init__(self, settings: VinzySettings | None = None):
        self._settings = settings or get_settings()
        self.engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    async def init(self) -> None:
        url = self._settings.db_url
        self.engine = create_async_engine(url, echo=False)
        self._session_factory = async_sessionmaker(
            self.engine, expire_on_commit=False
        )

    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        if self._session_factory is None:
            raise RuntimeError("DatabaseManager not initialized — call init() first")
        async with self._session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def create_all(self) -> None:
        if self.engine is None:
            raise RuntimeError("DatabaseManager not initialized — call init() first")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        if self.engine:
            await self.engine.dispose()
            self.engine = None
            self._session_factory = None
