"""Batch audit log inserts with periodic flush.

Accumulates audit entries in memory and flushes every 500ms or 100 entries
(whichever comes first). This reduces per-event database round trips during
high-throughput validation bursts.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Flush thresholds
FLUSH_INTERVAL_SECONDS = 0.5  # 500ms
FLUSH_BATCH_SIZE = 100


@dataclass
class PendingAuditEntry:
    """An audit event waiting to be flushed to the database."""
    license_id: str
    event_type: str
    actor: str = "system"
    detail: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.monotonic)


class BatchAuditWriter:
    """Batches audit log inserts and flushes periodically.

    Instead of inserting one audit row per event, entries are accumulated
    in an in-memory buffer. A background task flushes the buffer either
    when it reaches FLUSH_BATCH_SIZE or every FLUSH_INTERVAL_SECONDS.

    Usage:
        writer = BatchAuditWriter(audit_service, db_manager)
        writer.start()
        await writer.enqueue("license-123", "license.validated", "system", {})
        # ... entries are auto-flushed in background
        await writer.stop()  # flush remaining on shutdown
    """

    def __init__(
        self,
        audit_service=None,
        db_manager=None,
        flush_interval: float = FLUSH_INTERVAL_SECONDS,
        batch_size: int = FLUSH_BATCH_SIZE,
    ):
        self._audit_service = audit_service
        self._db_manager = db_manager
        self._flush_interval = flush_interval
        self._batch_size = batch_size
        self._buffer: list[PendingAuditEntry] = []
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self._running = False
        self._total_flushed = 0
        self._total_enqueued = 0
        self._flush_count = 0

    @property
    def pending_count(self) -> int:
        return len(self._buffer)

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "pending": self.pending_count,
            "total_enqueued": self._total_enqueued,
            "total_flushed": self._total_flushed,
            "flush_count": self._flush_count,
            "running": self._running,
        }

    def start(self) -> None:
        """Start the background flush loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._flush_loop())

    async def stop(self) -> None:
        """Stop the flush loop and flush remaining entries."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        # Final flush
        await self.flush()

    async def enqueue(
        self,
        license_id: str,
        event_type: str,
        actor: str = "system",
        detail: dict[str, Any] | None = None,
    ) -> None:
        """Add an audit entry to the batch buffer.

        If the buffer reaches batch_size, triggers an immediate flush.
        """
        entry = PendingAuditEntry(
            license_id=license_id,
            event_type=event_type,
            actor=actor,
            detail=detail or {},
        )
        async with self._lock:
            self._buffer.append(entry)
            self._total_enqueued += 1

        if len(self._buffer) >= self._batch_size:
            await self.flush()

    async def flush(self) -> int:
        """Flush all pending entries to the database. Returns count flushed."""
        async with self._lock:
            if not self._buffer:
                return 0
            batch = self._buffer[:]
            self._buffer.clear()

        if not self._audit_service or not self._db_manager:
            logger.warning("BatchAuditWriter has no audit_service/db_manager; dropping %d entries", len(batch))
            return 0

        flushed = 0
        try:
            async with self._db_manager.get_session() as session:
                for entry in batch:
                    try:
                        await self._audit_service.record_event(
                            session,
                            entry.license_id,
                            entry.event_type,
                            entry.actor,
                            entry.detail,
                        )
                        flushed += 1
                    except Exception:
                        logger.exception(
                            "Failed to flush audit entry: license_id=%s event=%s",
                            entry.license_id, entry.event_type,
                        )
        except Exception:
            logger.exception("Failed to flush audit batch of %d entries", len(batch))

        self._total_flushed += flushed
        self._flush_count += 1
        return flushed

    async def _flush_loop(self) -> None:
        """Background loop that flushes at regular intervals."""
        while self._running:
            try:
                await asyncio.sleep(self._flush_interval)
                if self._buffer:
                    await self.flush()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in batch audit flush loop")


# Singleton
_batch_writer: BatchAuditWriter | None = None


def get_batch_audit_writer() -> BatchAuditWriter:
    """Get the singleton batch audit writer."""
    global _batch_writer
    if _batch_writer is None:
        _batch_writer = BatchAuditWriter()
    return _batch_writer


def reset_batch_audit_writer() -> None:
    """Reset the singleton (for testing)."""
    global _batch_writer
    _batch_writer = None
