"""Automated webhook retry with dead letter queue.

Tracks failed webhook deliveries, retries them with exponential backoff,
and moves permanently failed deliveries to a dead letter queue for inspection.
"""

import asyncio
import json
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from vinzy_engine.webhooks.models import WebhookDeliveryModel, WebhookEndpointModel

logger = logging.getLogger(__name__)

MAX_RETRIES = 5
BASE_BACKOFF_SECONDS = 2.0
MAX_BACKOFF_SECONDS = 300.0
DLQ_MAX_SIZE = 10_000


@dataclass
class DeadLetterEntry:
    """A permanently failed webhook delivery moved to the dead letter queue."""

    delivery_id: str
    endpoint_id: str
    event_type: str
    payload: dict[str, Any]
    last_error: str
    attempts: int
    first_attempt_at: datetime
    dead_lettered_at: datetime
    replayed: bool = False
    replayed_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "delivery_id": self.delivery_id,
            "endpoint_id": self.endpoint_id,
            "event_type": self.event_type,
            "payload": self.payload,
            "last_error": self.last_error,
            "attempts": self.attempts,
            "first_attempt_at": self.first_attempt_at.isoformat(),
            "dead_lettered_at": self.dead_lettered_at.isoformat(),
            "replayed": self.replayed,
            "replayed_at": self.replayed_at.isoformat() if self.replayed_at else None,
        }


class DeadLetterQueue:
    """In-memory dead letter queue for permanently failed webhook deliveries."""

    def __init__(self, max_size: int = DLQ_MAX_SIZE):
        self._entries: dict[str, DeadLetterEntry] = {}
        self._max_size = max_size

    def add(self, entry: DeadLetterEntry) -> None:
        if len(self._entries) >= self._max_size:
            # Evict oldest non-replayed entry, or oldest overall
            candidates = [
                e for e in self._entries.values() if not e.replayed
            ]
            if not candidates:
                candidates = list(self._entries.values())
            oldest = min(candidates, key=lambda e: e.dead_lettered_at)
            del self._entries[oldest.delivery_id]
        self._entries[entry.delivery_id] = entry
        logger.warning(
            "Delivery %s moved to dead letter queue after %d attempts: %s",
            entry.delivery_id, entry.attempts, entry.last_error,
        )

    def get(self, delivery_id: str) -> DeadLetterEntry | None:
        return self._entries.get(delivery_id)

    def list_entries(
        self,
        event_type: str | None = None,
        endpoint_id: str | None = None,
        include_replayed: bool = False,
    ) -> list[DeadLetterEntry]:
        results = []
        for entry in self._entries.values():
            if not include_replayed and entry.replayed:
                continue
            if event_type and entry.event_type != event_type:
                continue
            if endpoint_id and entry.endpoint_id != endpoint_id:
                continue
            results.append(entry)
        return sorted(results, key=lambda e: e.dead_lettered_at, reverse=True)

    def mark_replayed(self, delivery_id: str) -> bool:
        entry = self._entries.get(delivery_id)
        if entry is None:
            return False
        entry.replayed = True
        entry.replayed_at = datetime.now(timezone.utc)
        return True

    def purge(self, older_than_days: int | None = None) -> int:
        if older_than_days is None:
            count = len(self._entries)
            self._entries.clear()
            return count
        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        to_remove = [
            did for did, e in self._entries.items()
            if e.dead_lettered_at < cutoff
        ]
        for did in to_remove:
            del self._entries[did]
        return len(to_remove)

    @property
    def size(self) -> int:
        return len(self._entries)

    @property
    def pending_count(self) -> int:
        return sum(1 for e in self._entries.values() if not e.replayed)

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "total": self.size,
            "pending": self.pending_count,
            "replayed": self.size - self.pending_count,
        }


class WebhookRetryManager:
    """Manages webhook delivery retries with exponential backoff and jitter.

    Failed deliveries are retried up to max_retries times with exponential
    backoff. After exhausting retries, deliveries are moved to the dead
    letter queue for manual inspection and replay.
    """

    def __init__(
        self,
        dlq: DeadLetterQueue | None = None,
        max_retries: int = MAX_RETRIES,
        base_backoff: float = BASE_BACKOFF_SECONDS,
        max_backoff: float = MAX_BACKOFF_SECONDS,
        check_interval_seconds: float = 30.0,
        batch_size: int = 50,
    ):
        self._dlq = dlq or DeadLetterQueue()
        self._max_retries = max_retries
        self._base_backoff = base_backoff
        self._max_backoff = max_backoff
        self._check_interval = check_interval_seconds
        self._batch_size = batch_size
        self._task: asyncio.Task | None = None
        self._running = False
        self._total_retried = 0
        self._total_succeeded = 0
        self._total_dead_lettered = 0

    @property
    def dead_letter_queue(self) -> DeadLetterQueue:
        return self._dlq

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "total_retried": self._total_retried,
            "total_succeeded": self._total_succeeded,
            "total_dead_lettered": self._total_dead_lettered,
            "dlq": self._dlq.stats,
        }

    def calculate_backoff(self, attempt: int) -> float:
        """Exponential backoff with full jitter."""
        delay = min(self._base_backoff * (2 ** attempt), self._max_backoff)
        return random.uniform(0, delay)

    def start(self, db_manager=None) -> None:
        if db_manager is not None:
            self._db_manager = db_manager
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def run_once(self, db_manager=None) -> dict[str, int]:
        """Process one batch of failed deliveries eligible for retry."""
        mgr = db_manager or getattr(self, "_db_manager", None)
        if mgr is None:
            return {"retried": 0, "succeeded": 0, "dead_lettered": 0}

        from vinzy_engine.webhooks.service import sign_payload

        now = datetime.now(timezone.utc)
        retried = 0
        succeeded = 0
        dead_lettered = 0

        try:
            async with mgr.get_session() as session:
                # Find failed deliveries due for retry
                result = await session.execute(
                    select(WebhookDeliveryModel).where(
                        WebhookDeliveryModel.status == "failed",
                        WebhookDeliveryModel.next_retry_at != None,
                        WebhookDeliveryModel.next_retry_at <= now,
                    ).limit(self._batch_size)
                )
                deliveries = list(result.scalars().all())

                if not deliveries:
                    return {"retried": 0, "succeeded": 0, "dead_lettered": 0}

                # Load associated endpoints
                endpoint_ids = {d.endpoint_id for d in deliveries}
                ep_result = await session.execute(
                    select(WebhookEndpointModel).where(
                        WebhookEndpointModel.id.in_(endpoint_ids)
                    )
                )
                endpoints = {ep.id: ep for ep in ep_result.scalars().all()}

                for delivery in deliveries:
                    ep = endpoints.get(delivery.endpoint_id)
                    if ep is None or ep.status != "active":
                        self._move_to_dlq(delivery, ep, "Endpoint not found or inactive")
                        dead_lettered += 1
                        continue

                    attempts = (delivery.attempts or 0) + 1
                    if attempts > self._max_retries:
                        self._move_to_dlq(delivery, ep, delivery.last_error or "Max retries exceeded")
                        dead_lettered += 1
                        continue

                    success = await self._attempt_send(delivery, ep, sign_payload)
                    retried += 1

                    if success:
                        delivery.status = "success"
                        delivery.attempts = attempts
                        succeeded += 1
                    else:
                        delivery.attempts = attempts
                        if attempts >= self._max_retries:
                            self._move_to_dlq(delivery, ep, delivery.last_error or "Unknown error")
                            dead_lettered += 1
                        else:
                            backoff_secs = self.calculate_backoff(attempts)
                            delivery.next_retry_at = now + timedelta(seconds=backoff_secs)
                            delivery.status = "failed"

        except Exception:
            logger.exception("Webhook retry pass failed")

        self._total_retried += retried
        self._total_succeeded += succeeded
        self._total_dead_lettered += dead_lettered
        return {"retried": retried, "succeeded": succeeded, "dead_lettered": dead_lettered}

    def _move_to_dlq(
        self,
        delivery: WebhookDeliveryModel,
        endpoint: WebhookEndpointModel | None,
        error: str,
    ) -> None:
        delivery.status = "dead_letter"
        delivery.next_retry_at = None
        self._dlq.add(DeadLetterEntry(
            delivery_id=delivery.id,
            endpoint_id=delivery.endpoint_id,
            event_type=delivery.event_type,
            payload=delivery.payload or {},
            last_error=error,
            attempts=delivery.attempts or 0,
            first_attempt_at=delivery.created_at or datetime.now(timezone.utc),
            dead_lettered_at=datetime.now(timezone.utc),
        ))

    async def _attempt_send(
        self,
        delivery: WebhookDeliveryModel,
        endpoint: WebhookEndpointModel,
        sign_fn,
    ) -> bool:
        try:
            import httpx
        except ImportError:
            delivery.last_error = "httpx not available"
            return False

        payload_json = json.dumps(delivery.payload or {}, default=str)
        signature = sign_fn(payload_json, endpoint.secret)
        headers = {
            "Content-Type": "application/json",
            "X-Vinzy-Signature": signature,
            "X-Vinzy-Event": delivery.event_type,
        }

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    endpoint.url,
                    content=payload_json,
                    headers=headers,
                    timeout=endpoint.timeout_seconds,
                )
                delivery.last_response_code = resp.status_code
                if 200 <= resp.status_code < 300:
                    return True
                delivery.last_error = f"HTTP {resp.status_code}"
        except httpx.TimeoutException:
            delivery.last_error = "timeout"
        except Exception as e:
            delivery.last_error = str(e)[:1024]

        return False

    async def replay_from_dlq(
        self, db_manager, delivery_id: str,
    ) -> bool:
        """Replay a dead-lettered delivery by resetting it to pending."""
        entry = self._dlq.get(delivery_id)
        if entry is None:
            return False

        try:
            async with db_manager.get_session() as session:
                result = await session.execute(
                    select(WebhookDeliveryModel).where(
                        WebhookDeliveryModel.id == delivery_id,
                    )
                )
                delivery = result.scalar_one_or_none()
                if delivery is None:
                    return False

                delivery.status = "pending"
                delivery.attempts = 0
                delivery.last_error = None
                delivery.next_retry_at = None
                await session.flush()

            self._dlq.mark_replayed(delivery_id)
            return True
        except Exception:
            logger.exception("Failed to replay delivery %s from DLQ", delivery_id)
            return False

    async def _loop(self) -> None:
        while self._running:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in webhook retry loop")
            await asyncio.sleep(self._check_interval)


# ---------------------------------------------------------------------------
# Singletons
# ---------------------------------------------------------------------------

_dlq: DeadLetterQueue | None = None
_retry_manager: WebhookRetryManager | None = None


def get_dead_letter_queue() -> DeadLetterQueue:
    global _dlq
    if _dlq is None:
        _dlq = DeadLetterQueue()
    return _dlq


def get_webhook_retry_manager() -> WebhookRetryManager:
    global _retry_manager
    if _retry_manager is None:
        _retry_manager = WebhookRetryManager(dlq=get_dead_letter_queue())
    return _retry_manager


def reset_webhook_retry() -> None:
    """Reset singletons (for testing)."""
    global _dlq, _retry_manager
    _dlq = None
    _retry_manager = None
