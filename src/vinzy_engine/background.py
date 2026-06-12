"""Background task processing for Vinzy-Engine.

Implements:
- Soft-delete with background hard-delete (item 21)
- Background license expiration processing (item 156)
- Async webhook delivery with retry (item 143)
- Async Stripe webhook processing (item 164)
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select, update

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Hard-delete processor (item 21)
# ---------------------------------------------------------------------------

class HardDeleteProcessor:
    """Periodically hard-deletes soft-deleted records after a retention period.

    Soft-deleted licenses (is_deleted=True) are kept for `retention_days` days
    to allow recovery, then permanently removed by this background processor.
    """

    def __init__(
        self,
        db_manager=None,
        retention_days: int = 30,
        check_interval_seconds: float = 3600.0,  # 1 hour
        batch_size: int = 100,
    ):
        self._db_manager = db_manager
        self._retention_days = retention_days
        self._check_interval = check_interval_seconds
        self._batch_size = batch_size
        self._task: asyncio.Task | None = None
        self._running = False
        self._total_deleted = 0

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "retention_days": self._retention_days,
            "total_hard_deleted": self._total_deleted,
        }

    def start(self, db_manager=None) -> None:
        """Start the background hard-delete loop."""
        if db_manager is not None:
            self._db_manager = db_manager
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        """Stop the background loop."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def run_once(self, db_manager=None) -> int:
        """Run a single hard-delete pass. Returns count of records deleted."""
        mgr = db_manager or self._db_manager
        if mgr is None:
            return 0

        from vinzy_engine.licensing.models import LicenseModel
        from vinzy_engine.licensing.models import EntitlementModel
        from vinzy_engine.activation.models import MachineModel
        from vinzy_engine.audit.models import AuditEventModel

        cutoff = datetime.now(timezone.utc) - timedelta(days=self._retention_days)
        total = 0

        try:
            async with mgr.get_session() as session:
                # Find licenses eligible for hard delete
                result = await session.execute(
                    select(LicenseModel.id).where(
                        LicenseModel.is_deleted == True,
                        LicenseModel.deleted_at != None,
                        LicenseModel.deleted_at < cutoff,
                    ).limit(self._batch_size)
                )
                license_ids = [row[0] for row in result.all()]

                if not license_ids:
                    return 0

                # Delete related records first (cascade)
                await session.execute(
                    delete(EntitlementModel).where(
                        EntitlementModel.license_id.in_(license_ids)
                    )
                )
                await session.execute(
                    delete(MachineModel).where(
                        MachineModel.license_id.in_(license_ids)
                    )
                )
                await session.execute(
                    delete(AuditEventModel).where(
                        AuditEventModel.license_id.in_(license_ids)
                    )
                )
                # Hard delete the licenses
                await session.execute(
                    delete(LicenseModel).where(
                        LicenseModel.id.in_(license_ids)
                    )
                )
                total = len(license_ids)

        except Exception:
            logger.exception("Hard-delete pass failed")
            return 0

        self._total_deleted += total
        if total > 0:
            logger.info("Hard-deleted %d soft-deleted licenses (cutoff=%s)", total, cutoff)
        return total

    async def _loop(self) -> None:
        while self._running:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in hard-delete loop")
            await asyncio.sleep(self._check_interval)


# ---------------------------------------------------------------------------
# License expiration processor (item 156)
# ---------------------------------------------------------------------------

class LicenseExpirationProcessor:
    """Background processor that marks expired licenses.

    Scans for licenses with status='active' whose expires_at has passed,
    and updates their status to 'expired'. Runs on a configurable interval.
    """

    def __init__(
        self,
        db_manager=None,
        check_interval_seconds: float = 300.0,  # 5 minutes
        batch_size: int = 500,
    ):
        self._db_manager = db_manager
        self._check_interval = check_interval_seconds
        self._batch_size = batch_size
        self._task: asyncio.Task | None = None
        self._running = False
        self._total_expired = 0

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "total_expired": self._total_expired,
        }

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

    async def run_once(self, db_manager=None) -> int:
        """Run a single expiration pass. Returns count of licenses expired."""
        mgr = db_manager or self._db_manager
        if mgr is None:
            return 0

        from vinzy_engine.licensing.models import LicenseModel

        now = datetime.now(timezone.utc)
        total = 0

        try:
            async with mgr.get_session() as session:
                # Find active licenses that have expired
                result = await session.execute(
                    select(LicenseModel).where(
                        LicenseModel.status == "active",
                        LicenseModel.is_deleted == False,
                        LicenseModel.expires_at != None,
                        LicenseModel.expires_at < now,
                    ).limit(self._batch_size)
                )
                licenses = list(result.scalars().all())

                for lic in licenses:
                    lic.status = "expired"
                    total += 1

                if total > 0:
                    await session.flush()

        except Exception:
            logger.exception("License expiration pass failed")
            return 0

        self._total_expired += total
        if total > 0:
            logger.info("Expired %d licenses in background pass", total)
        return total

    async def _loop(self) -> None:
        while self._running:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in license expiration loop")
            await asyncio.sleep(self._check_interval)


# ---------------------------------------------------------------------------
# Async webhook delivery with retry (item 143)
# ---------------------------------------------------------------------------

class AsyncWebhookDeliveryProcessor:
    """Processes pending webhook deliveries with exponential backoff retry.

    Picks up deliveries with status='pending' or failed deliveries due for
    retry, and attempts to deliver them. Uses exponential backoff with
    configurable max retries.
    """

    def __init__(
        self,
        db_manager=None,
        check_interval_seconds: float = 10.0,
        batch_size: int = 50,
    ):
        self._db_manager = db_manager
        self._check_interval = check_interval_seconds
        self._batch_size = batch_size
        self._task: asyncio.Task | None = None
        self._running = False
        self._total_delivered = 0
        self._total_failed = 0

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "total_delivered": self._total_delivered,
            "total_failed": self._total_failed,
        }

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
        """Process one batch of pending deliveries. Returns delivery stats."""
        mgr = db_manager or self._db_manager
        if mgr is None:
            return {"delivered": 0, "failed": 0}

        from vinzy_engine.webhooks.models import WebhookDeliveryModel, WebhookEndpointModel
        from vinzy_engine.webhooks.service import sign_payload

        now = datetime.now(timezone.utc)
        delivered = 0
        failed = 0

        try:
            async with mgr.get_session() as session:
                # Find deliveries to process: pending, or failed with retry due
                result = await session.execute(
                    select(WebhookDeliveryModel).where(
                        WebhookDeliveryModel.status.in_(["pending", "retrying"]),
                    ).limit(self._batch_size)
                )
                deliveries = list(result.scalars().all())

                # Also pick up failed deliveries due for retry
                retry_result = await session.execute(
                    select(WebhookDeliveryModel).where(
                        WebhookDeliveryModel.status == "failed",
                        WebhookDeliveryModel.next_retry_at != None,
                        WebhookDeliveryModel.next_retry_at <= now,
                    ).limit(self._batch_size)
                )
                retries = list(retry_result.scalars().all())
                deliveries.extend(retries)

                if not deliveries:
                    return {"delivered": 0, "failed": 0}

                # Load endpoints
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
                        delivery.status = "failed"
                        delivery.last_error = "Endpoint not found or inactive"
                        failed += 1
                        continue

                    success = await self._attempt_delivery(delivery, ep)
                    if success:
                        delivered += 1
                    else:
                        failed += 1

        except Exception:
            logger.exception("Webhook delivery pass failed")

        self._total_delivered += delivered
        self._total_failed += failed
        return {"delivered": delivered, "failed": failed}

    async def _attempt_delivery(self, delivery, endpoint) -> bool:
        """Attempt to deliver a single webhook. Returns True on success."""
        from vinzy_engine.webhooks.service import sign_payload

        try:
            import httpx
        except ImportError:
            delivery.status = "failed"
            delivery.last_error = "httpx not available"
            return False

        payload_json = json.dumps(delivery.payload, default=str)
        signature = sign_payload(payload_json, endpoint.secret)
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
                delivery.attempts += 1
                delivery.last_response_code = resp.status_code

                if 200 <= resp.status_code < 300:
                    delivery.status = "success"
                    return True

                delivery.last_error = f"HTTP {resp.status_code}"

        except httpx.TimeoutException:
            delivery.attempts += 1
            delivery.last_error = "timeout"
        except Exception as e:
            delivery.attempts += 1
            delivery.last_error = str(e)[:1024]

        # Check if retries exhausted
        if delivery.attempts >= endpoint.max_retries:
            delivery.status = "failed"
        else:
            delivery.status = "retrying"
            # Exponential backoff: 2^attempt minutes
            backoff = timedelta(minutes=min(2 ** delivery.attempts, 60))
            delivery.next_retry_at = datetime.now(timezone.utc) + backoff

        return False

    async def _loop(self) -> None:
        while self._running:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in webhook delivery loop")
            await asyncio.sleep(self._check_interval)


# ---------------------------------------------------------------------------
# Async Stripe webhook processing (item 164)
# ---------------------------------------------------------------------------

class StripeWebhookProcessor:
    """Processes Stripe webhook events asynchronously.

    Instead of processing Stripe webhooks synchronously in the HTTP handler,
    events are queued and processed in the background. This allows the HTTP
    endpoint to return 200 immediately (Stripe requires fast responses).
    """

    def __init__(self, max_queue_size: int = 1000):
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)
        self._task: asyncio.Task | None = None
        self._running = False
        self._total_processed = 0
        self._total_errors = 0

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "queue_size": self._queue.qsize(),
            "total_processed": self._total_processed,
            "total_errors": self._total_errors,
        }

    def start(self) -> None:
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

    async def enqueue(self, event_data: dict[str, Any]) -> bool:
        """Add a Stripe event to the processing queue.

        Returns True if queued, False if queue is full.
        """
        try:
            self._queue.put_nowait(event_data)
            return True
        except asyncio.QueueFull:
            logger.error("Stripe webhook queue full, dropping event")
            return False

    async def process_event(self, event_data: dict[str, Any]) -> bool:
        """Process a single Stripe event. Returns True on success."""
        from vinzy_engine.provisioning.stripe_webhook import parse_stripe_checkout

        prov_request = parse_stripe_checkout(event_data)
        if prov_request is None:
            # Not a checkout event we handle — skip silently
            return True

        try:
            from vinzy_engine.provisioning.router import _get_provisioning_service
            svc, db = await _get_provisioning_service()
            async with db.get_session() as session:
                result = await svc.provision(session, prov_request)
                if result.success:
                    self._total_processed += 1
                    return True
                else:
                    self._total_errors += 1
                    logger.error("Stripe provisioning failed: %s", result.error)
                    return False
        except Exception:
            self._total_errors += 1
            logger.exception("Error processing Stripe webhook event")
            return False

    async def _loop(self) -> None:
        while self._running:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                await self.process_event(event)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in Stripe webhook processing loop")


# ---------------------------------------------------------------------------
# Singletons
# ---------------------------------------------------------------------------

_hard_delete_processor: HardDeleteProcessor | None = None
_expiration_processor: LicenseExpirationProcessor | None = None
_webhook_processor: AsyncWebhookDeliveryProcessor | None = None
_stripe_processor: StripeWebhookProcessor | None = None


def get_hard_delete_processor() -> HardDeleteProcessor:
    global _hard_delete_processor
    if _hard_delete_processor is None:
        _hard_delete_processor = HardDeleteProcessor()
    return _hard_delete_processor


def get_expiration_processor() -> LicenseExpirationProcessor:
    global _expiration_processor
    if _expiration_processor is None:
        _expiration_processor = LicenseExpirationProcessor()
    return _expiration_processor


def get_webhook_delivery_processor() -> AsyncWebhookDeliveryProcessor:
    global _webhook_processor
    if _webhook_processor is None:
        _webhook_processor = AsyncWebhookDeliveryProcessor()
    return _webhook_processor


def get_stripe_processor() -> StripeWebhookProcessor:
    global _stripe_processor
    if _stripe_processor is None:
        _stripe_processor = StripeWebhookProcessor()
    return _stripe_processor


def reset_background_processors() -> None:
    """Reset all singletons (for testing)."""
    global _hard_delete_processor, _expiration_processor
    global _webhook_processor, _stripe_processor
    _hard_delete_processor = None
    _expiration_processor = None
    _webhook_processor = None
    _stripe_processor = None
