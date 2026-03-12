"""Webhook service — CRUD, dispatch, and delivery management."""

import asyncio
import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vinzy_engine.common.config import VinzySettings
from vinzy_engine.webhooks.models import WebhookDeliveryModel, WebhookEndpointModel

logger = logging.getLogger(__name__)

VALID_EVENT_TYPES: frozenset[str] = frozenset({
    "license.created",
    "license.updated",
    "license.deleted",
    "license.validated",
    "activation.created",
    "activation.removed",
    "usage.recorded",
    "anomaly.detected",
})


def sign_payload(payload_json: str, secret: str) -> str:
    """Compute HMAC-SHA256 hex digest for a JSON payload."""
    return hmac.new(
        secret.encode("utf-8"),
        payload_json.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


class WebhookService:
    """Webhook endpoint management and event dispatch."""

    def __init__(self, settings: VinzySettings):
        self.settings = settings
        self._http_client = None

    def _get_http_client(self):
        """Lazy-init httpx.AsyncClient."""
        if self._http_client is None:
            import httpx
            self._http_client = httpx.AsyncClient()
        return self._http_client

    # ── CRUD ──

    async def create_endpoint(
        self,
        session: AsyncSession,
        url: str,
        secret: str,
        event_types: list[str] | None = None,
        description: str = "",
        max_retries: int = 3,
        timeout_seconds: int = 10,
        tenant_id: str | None = None,
    ) -> WebhookEndpointModel:
        endpoint = WebhookEndpointModel(
            url=url,
            secret=secret,
            event_types=event_types or [],
            description=description,
            max_retries=max_retries,
            timeout_seconds=timeout_seconds,
            tenant_id=tenant_id,
        )
        session.add(endpoint)
        await session.flush()
        return endpoint

    async def get_endpoint(
        self, session: AsyncSession, endpoint_id: str,
        tenant_id: str | None = None,
    ) -> Optional[WebhookEndpointModel]:
        query = select(WebhookEndpointModel).where(
            WebhookEndpointModel.id == endpoint_id,
        )
        if tenant_id is not None:
            query = query.where(WebhookEndpointModel.tenant_id == tenant_id)
        result = await session.execute(query)
        return result.scalar_one_or_none()

    async def list_endpoints(
        self,
        session: AsyncSession,
        status: str | None = None,
        tenant_id: str | None = None,
    ) -> list[WebhookEndpointModel]:
        query = select(WebhookEndpointModel)
        if tenant_id is not None:
            query = query.where(WebhookEndpointModel.tenant_id == tenant_id)
        if status is not None:
            query = query.where(WebhookEndpointModel.status == status)
        query = query.order_by(WebhookEndpointModel.created_at.desc())
        result = await session.execute(query)
        return list(result.scalars().all())

    async def update_endpoint(
        self,
        session: AsyncSession,
        endpoint_id: str,
        tenant_id: str | None = None,
        **updates: Any,
    ) -> Optional[WebhookEndpointModel]:
        endpoint = await self.get_endpoint(session, endpoint_id, tenant_id=tenant_id)
        if endpoint is None:
            return None
        for field in ("url", "secret", "event_types", "description",
                      "max_retries", "timeout_seconds", "status"):
            if field in updates and updates[field] is not None:
                setattr(endpoint, field, updates[field])
        await session.flush()
        return endpoint

    async def delete_endpoint(
        self,
        session: AsyncSession,
        endpoint_id: str,
        tenant_id: str | None = None,
    ) -> bool:
        endpoint = await self.get_endpoint(session, endpoint_id, tenant_id=tenant_id)
        if endpoint is None:
            return False
        await session.delete(endpoint)
        await session.flush()
        return True

    # ── Dispatch ──

    async def dispatch(
        self,
        session: AsyncSession,
        event_type: str,
        payload: dict[str, Any],
        tenant_id: str | None = None,
    ) -> list[WebhookDeliveryModel]:
        """Create delivery records for matching active endpoints and fire async sends."""
        query = select(WebhookEndpointModel).where(
            WebhookEndpointModel.status == "active",
        )
        if tenant_id is not None:
            query = query.where(WebhookEndpointModel.tenant_id == tenant_id)
        else:
            query = query.where(WebhookEndpointModel.tenant_id.is_(None))

        result = await session.execute(query)
        endpoints = list(result.scalars().all())

        deliveries = []
        envelope = {
            "event_type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": payload,
        }

        for ep in endpoints:
            # Empty event_types = wildcard (match all events)
            if ep.event_types and event_type not in ep.event_types:
                continue

            delivery = WebhookDeliveryModel(
                endpoint_id=ep.id,
                event_type=event_type,
                payload=envelope,
                status="pending",
            )
            session.add(delivery)
            await session.flush()

            # Fire-and-forget async delivery
            asyncio.create_task(
                self._send_delivery(
                    delivery_id=delivery.id,
                    url=ep.url,
                    secret=ep.secret,
                    payload=envelope,
                    max_retries=ep.max_retries,
                    timeout=ep.timeout_seconds,
                )
            )
            deliveries.append(delivery)

        return deliveries

    async def _send_delivery(
        self,
        delivery_id: str,
        url: str,
        secret: str,
        payload: dict[str, Any],
        max_retries: int,
        timeout: int,
    ) -> None:
        """Send HTTP POST with HMAC signature and retry on failure."""
        import httpx

        payload_json = json.dumps(payload, default=str)
        signature = sign_payload(payload_json, secret)
        headers = {
            "Content-Type": "application/json",
            "X-Vinzy-Signature": signature,
            "X-Vinzy-Event": payload.get("event_type", ""),
        }

        last_error = None
        last_status = None

        for attempt in range(max_retries + 1):
            try:
                client = self._get_http_client()
                resp = await client.post(
                    url,
                    content=payload_json,
                    headers=headers,
                    timeout=timeout,
                )
                last_status = resp.status_code

                if 200 <= resp.status_code < 300:
                    await self._update_delivery_status(
                        delivery_id, "success", attempt + 1, last_status, None,
                    )
                    return

                last_error = f"HTTP {resp.status_code}"
            except httpx.TimeoutException:
                last_error = "timeout"
            except httpx.HTTPError as e:
                last_error = str(e)
            except Exception as e:
                last_error = str(e)

            if attempt < max_retries:
                await asyncio.sleep(2 ** attempt)

        # All retries exhausted
        await self._update_delivery_status(
            delivery_id, "failed", max_retries + 1, last_status, last_error,
        )

    async def _update_delivery_status(
        self,
        delivery_id: str,
        status: str,
        attempts: int,
        response_code: int | None,
        error: str | None,
    ) -> None:
        """Update delivery record using a fresh DB session."""
        from vinzy_engine.deps import get_db

        db = get_db()
        try:
            async with db.get_session() as session:
                result = await session.execute(
                    select(WebhookDeliveryModel).where(
                        WebhookDeliveryModel.id == delivery_id,
                    )
                )
                delivery = result.scalar_one_or_none()
                if delivery is None:
                    return
                delivery.status = status
                delivery.attempts = attempts
                delivery.last_response_code = response_code
                delivery.last_error = error
                if status == "failed":
                    delivery.next_retry_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        except Exception:
            logger.exception("Failed to update delivery %s", delivery_id)

    # ── Delivery queries ──

    async def get_deliveries(
        self,
        session: AsyncSession,
        endpoint_id: str | None = None,
        event_type: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[WebhookDeliveryModel]:
        query = select(WebhookDeliveryModel)
        if endpoint_id is not None:
            query = query.where(WebhookDeliveryModel.endpoint_id == endpoint_id)
        if event_type is not None:
            query = query.where(WebhookDeliveryModel.event_type == event_type)
        if status is not None:
            query = query.where(WebhookDeliveryModel.status == status)
        query = query.order_by(WebhookDeliveryModel.created_at.desc())
        query = query.offset(offset).limit(limit)
        result = await session.execute(query)
        return list(result.scalars().all())

    async def get_delivery(
        self, session: AsyncSession, delivery_id: str,
    ) -> Optional[WebhookDeliveryModel]:
        result = await session.execute(
            select(WebhookDeliveryModel).where(
                WebhookDeliveryModel.id == delivery_id,
            )
        )
        return result.scalar_one_or_none()

    async def retry_delivery(
        self, session: AsyncSession, delivery_id: str,
    ) -> Optional[WebhookDeliveryModel]:
        """Reset a failed delivery to pending and re-fire."""
        delivery = await self.get_delivery(session, delivery_id)
        if delivery is None:
            return None

        # Look up the endpoint to get url/secret/retry config
        endpoint = await self.get_endpoint(session, delivery.endpoint_id)
        if endpoint is None:
            return None

        delivery.status = "pending"
        delivery.attempts = 0
        delivery.last_error = None
        delivery.next_retry_at = None
        await session.flush()

        asyncio.create_task(
            self._send_delivery(
                delivery_id=delivery.id,
                url=endpoint.url,
                secret=endpoint.secret,
                payload=delivery.payload,
                max_retries=endpoint.max_retries,
                timeout=endpoint.timeout_seconds,
            )
        )
        return delivery
