"""Offline usage tracking with sync.

Records usage events locally when the database is unreachable, then
syncs them back once the connection is restored.
"""

import logging
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class SyncStatus(str, Enum):
    PENDING = "pending"
    SYNCING = "syncing"
    SYNCED = "synced"
    FAILED = "failed"


@dataclass
class OfflineUsageEvent:
    """A single usage event recorded while offline."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    license_id: str = ""
    metric: str = ""
    value: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    recorded_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    sync_status: SyncStatus = SyncStatus.PENDING
    sync_attempts: int = 0
    last_sync_error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "license_id": self.license_id, "metric": self.metric,
            "value": self.value, "metadata": self.metadata, "recorded_at": self.recorded_at,
            "sync_status": self.sync_status.value, "sync_attempts": self.sync_attempts,
            "last_sync_error": self.last_sync_error,
        }


@dataclass
class SyncResult:
    """Result of a batch sync operation."""
    total: int = 0
    synced: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


class OfflineUsageTracker:
    """Tracks usage events offline and syncs them when connectivity returns."""

    def __init__(self, max_buffer_size: int = 100_000, max_sync_attempts: int = 5, batch_size: int = 100):
        self._buffer: deque[OfflineUsageEvent] = deque(maxlen=max_buffer_size)
        self._max_sync_attempts = max_sync_attempts
        self._batch_size = batch_size
        self._total_recorded = 0
        self._total_synced = 0
        self._total_dropped = 0
        self._is_syncing = False

    def record(self, license_id: str, metric: str, value: float = 1.0, metadata: Optional[dict[str, Any]] = None) -> OfflineUsageEvent:
        """Record a usage event in the offline buffer."""
        event = OfflineUsageEvent(license_id=license_id, metric=metric, value=value, metadata=metadata or {})
        was_full = len(self._buffer) == (self._buffer.maxlen or 0)
        self._buffer.append(event)
        if was_full:
            self._total_dropped += 1
        self._total_recorded += 1
        return event

    async def sync(self, usage_service: Any, session: Any) -> SyncResult:
        """Sync pending offline events to the database via UsageService."""
        if self._is_syncing:
            return SyncResult()
        self._is_syncing = True
        result = SyncResult()
        try:
            pending = [e for e in self._buffer if e.sync_status in (SyncStatus.PENDING, SyncStatus.FAILED)]
            batch = pending[:self._batch_size]
            result.total = len(batch)
            for event in batch:
                event.sync_status = SyncStatus.SYNCING
                event.sync_attempts += 1
                try:
                    await usage_service.record_usage(
                        session, raw_key="", metric=event.metric, value=event.value,
                        metadata={**event.metadata, "offline_id": event.id, "offline_recorded_at": event.recorded_at},
                    )
                    event.sync_status = SyncStatus.SYNCED
                    result.synced += 1
                    self._total_synced += 1
                except Exception as exc:
                    event.last_sync_error = str(exc)
                    if event.sync_attempts >= self._max_sync_attempts:
                        event.sync_status = SyncStatus.FAILED
                    else:
                        event.sync_status = SyncStatus.PENDING
                    result.failed += 1
                    result.errors.append(f"Event {event.id}: {exc}")
            self._purge_synced()
        finally:
            self._is_syncing = False
        return result

    async def sync_by_license(self, license_id: str, record_callback: Any) -> SyncResult:
        """Sync all pending events for a specific license via callback."""
        result = SyncResult()
        pending = [e for e in self._buffer if e.license_id == license_id and e.sync_status in (SyncStatus.PENDING, SyncStatus.FAILED)]
        result.total = len(pending)
        for event in pending:
            event.sync_status = SyncStatus.SYNCING
            event.sync_attempts += 1
            try:
                await record_callback(event.metric, event.value, event.metadata)
                event.sync_status = SyncStatus.SYNCED
                result.synced += 1
                self._total_synced += 1
            except Exception as exc:
                event.last_sync_error = str(exc)
                if event.sync_attempts >= self._max_sync_attempts:
                    event.sync_status = SyncStatus.FAILED
                else:
                    event.sync_status = SyncStatus.PENDING
                result.failed += 1
                result.errors.append(f"Event {event.id}: {exc}")
        self._purge_synced()
        return result

    def get_pending_count(self) -> int:
        return sum(1 for e in self._buffer if e.sync_status in (SyncStatus.PENDING, SyncStatus.FAILED))

    def get_pending_events(self, license_id: Optional[str] = None, limit: int = 100) -> list[OfflineUsageEvent]:
        events = [e for e in self._buffer if e.sync_status in (SyncStatus.PENDING, SyncStatus.FAILED) and (license_id is None or e.license_id == license_id)]
        return events[:limit]

    def get_all_events(self, limit: int = 1000) -> list[OfflineUsageEvent]:
        return list(self._buffer)[:limit]

    def _purge_synced(self) -> int:
        before = len(self._buffer)
        self._buffer = deque((e for e in self._buffer if e.sync_status != SyncStatus.SYNCED), maxlen=self._buffer.maxlen)
        return before - len(self._buffer)

    def purge_failed(self) -> int:
        before = len(self._buffer)
        self._buffer = deque((e for e in self._buffer if not (e.sync_status == SyncStatus.FAILED and e.sync_attempts >= self._max_sync_attempts)), maxlen=self._buffer.maxlen)
        return before - len(self._buffer)

    def clear(self) -> None:
        self._buffer.clear()

    @property
    def buffer_size(self) -> int:
        return len(self._buffer)

    @property
    def stats(self) -> dict[str, Any]:
        return {"buffer_size": self.buffer_size, "max_buffer_size": self._buffer.maxlen, "pending_count": self.get_pending_count(), "total_recorded": self._total_recorded, "total_synced": self._total_synced, "total_dropped": self._total_dropped, "is_syncing": self._is_syncing}
