"""Database connection health monitoring for Vinzy-Engine.

Provides periodic health checks against the database connection pool,
tracks connection metrics, and exposes health status for the /health endpoint.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)


@dataclass
class ConnectionHealthStatus:
    """Snapshot of database connection health."""
    healthy: bool = True
    last_check_at: datetime | None = None
    last_latency_ms: float = 0.0
    avg_latency_ms: float = 0.0
    consecutive_failures: int = 0
    total_checks: int = 0
    total_failures: int = 0
    pool_size: int = 0
    pool_checked_out: int = 0


class DatabaseHealthMonitor:
    """Monitors database connection health with periodic probes.

    Runs a background task that periodically executes a lightweight query
    (SELECT 1) to verify the database is reachable. Tracks latency and
    failure counts for observability.
    """

    def __init__(
        self,
        check_interval_seconds: float = 30.0,
        unhealthy_threshold: int = 3,
        latency_window_size: int = 20,
    ):
        self._check_interval = check_interval_seconds
        self._unhealthy_threshold = unhealthy_threshold
        self._latency_window_size = latency_window_size

        self._status = ConnectionHealthStatus()
        self._latencies: list[float] = []
        self._task: asyncio.Task | None = None
        self._db_manager = None
        self._running = False

    @property
    def status(self) -> ConnectionHealthStatus:
        """Current health status snapshot."""
        return self._status

    @property
    def is_healthy(self) -> bool:
        return self._status.healthy

    def start(self, db_manager) -> None:
        """Start the background health check loop."""
        if self._running:
            return
        self._db_manager = db_manager
        self._running = True
        self._task = asyncio.create_task(self._check_loop())

    async def stop(self) -> None:
        """Stop the background health check loop."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def check_now(self) -> ConnectionHealthStatus:
        """Run an immediate health check and return the result."""
        if self._db_manager is None:
            return self._status
        await self._run_check()
        return self._status

    async def _check_loop(self) -> None:
        """Background loop that runs periodic checks."""
        while self._running:
            try:
                await self._run_check()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Unexpected error in health check loop")
            await asyncio.sleep(self._check_interval)

    async def _run_check(self) -> None:
        """Execute a single health probe."""
        if self._db_manager is None or self._db_manager.engine is None:
            self._status.healthy = False
            return

        self._status.total_checks += 1
        start = time.monotonic()

        try:
            async with self._db_manager.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            latency_ms = (time.monotonic() - start) * 1000

            self._latencies.append(latency_ms)
            if len(self._latencies) > self._latency_window_size:
                self._latencies = self._latencies[-self._latency_window_size:]

            self._status.last_latency_ms = round(latency_ms, 2)
            self._status.avg_latency_ms = round(
                sum(self._latencies) / len(self._latencies), 2
            )
            self._status.consecutive_failures = 0
            self._status.healthy = True
            self._status.last_check_at = datetime.now(timezone.utc)

            # Pool stats (if available)
            pool = self._db_manager.engine.pool
            if hasattr(pool, "size"):
                self._status.pool_size = pool.size()
            if hasattr(pool, "checkedout"):
                self._status.pool_checked_out = pool.checkedout()

        except Exception as exc:
            latency_ms = (time.monotonic() - start) * 1000
            self._status.last_latency_ms = round(latency_ms, 2)
            self._status.consecutive_failures += 1
            self._status.total_failures += 1
            self._status.last_check_at = datetime.now(timezone.utc)

            if self._status.consecutive_failures >= self._unhealthy_threshold:
                self._status.healthy = False

            logger.warning(
                "Database health check failed (attempt %d/%d): %s",
                self._status.consecutive_failures,
                self._unhealthy_threshold,
                exc,
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialize status to a JSON-friendly dict."""
        s = self._status
        return {
            "healthy": s.healthy,
            "last_check_at": s.last_check_at.isoformat() if s.last_check_at else None,
            "last_latency_ms": s.last_latency_ms,
            "avg_latency_ms": s.avg_latency_ms,
            "consecutive_failures": s.consecutive_failures,
            "total_checks": s.total_checks,
            "total_failures": s.total_failures,
            "pool_size": s.pool_size,
            "pool_checked_out": s.pool_checked_out,
        }


# Singleton
_health_monitor: DatabaseHealthMonitor | None = None


def get_health_monitor() -> DatabaseHealthMonitor:
    """Get the singleton database health monitor."""
    global _health_monitor
    if _health_monitor is None:
        _health_monitor = DatabaseHealthMonitor()
    return _health_monitor


def reset_health_monitor() -> None:
    """Reset the singleton (for testing)."""
    global _health_monitor
    _health_monitor = None
