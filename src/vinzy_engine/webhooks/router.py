"""Webhook management API router."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from vinzy_engine.common.security import require_api_key, require_admin_ip
from vinzy_engine.common.rate_limiting import limiter, _admin_limit
from vinzy_engine.webhooks.schemas import (
    WebhookDeliveryResponse,
    WebhookEndpointCreate,
    WebhookEndpointResponse,
    WebhookEndpointUpdate,
    WebhookTestRequest,
)
from vinzy_engine.webhooks.models import WebhookDeliveryModel
from vinzy_engine.webhooks.service import VALID_EVENT_TYPES

router = APIRouter()


def _get_service():
    from vinzy_engine.deps import get_webhook_service
    return get_webhook_service()


def _get_db():
    from vinzy_engine.deps import get_db
    return get_db()


def _endpoint_to_response(ep) -> WebhookEndpointResponse:
    return WebhookEndpointResponse(
        id=ep.id,
        tenant_id=ep.tenant_id,
        url=ep.url,
        description=ep.description,
        event_types=ep.event_types or [],
        status=ep.status,
        max_retries=ep.max_retries,
        timeout_seconds=ep.timeout_seconds,
        created_at=ep.created_at,
        updated_at=ep.updated_at,
    )


def _delivery_to_response(d) -> WebhookDeliveryResponse:
    return WebhookDeliveryResponse(
        id=d.id,
        endpoint_id=d.endpoint_id,
        event_type=d.event_type,
        payload=d.payload or {},
        status=d.status,
        attempts=d.attempts,
        last_response_code=d.last_response_code,
        last_error=d.last_error,
        next_retry_at=d.next_retry_at,
        created_at=d.created_at,
        updated_at=d.updated_at,
    )


@router.post("/webhooks", response_model=WebhookEndpointResponse, status_code=201)
@limiter.limit(_admin_limit)
async def create_webhook_endpoint(
    request: Request,
    body: WebhookEndpointCreate,
    _=Depends(require_api_key),
    __=Depends(require_admin_ip),
):
    # Validate event types
    for et in body.event_types:
        if et not in VALID_EVENT_TYPES:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid event type: {et}. Valid types: {sorted(VALID_EVENT_TYPES)}",
            )

    svc = _get_service()
    db = _get_db()
    async with db.get_session() as session:
        ep = await svc.create_endpoint(
            session,
            url=body.url,
            secret=body.secret,
            event_types=body.event_types,
            description=body.description,
            max_retries=body.max_retries,
            timeout_seconds=body.timeout_seconds,
        )
        return _endpoint_to_response(ep)


@router.get("/webhooks", response_model=list[WebhookEndpointResponse])
@limiter.limit(_admin_limit)
async def list_webhook_endpoints(
    request: Request,
    status: str | None = Query(None),
    _=Depends(require_api_key),
    __=Depends(require_admin_ip),
):
    svc = _get_service()
    db = _get_db()
    async with db.get_session() as session:
        endpoints = await svc.list_endpoints(session, status=status)
        return [_endpoint_to_response(ep) for ep in endpoints]


@router.get("/webhooks/{endpoint_id}", response_model=WebhookEndpointResponse)
@limiter.limit(_admin_limit)
async def get_webhook_endpoint(
    request: Request,
    endpoint_id: str,
    _=Depends(require_api_key),
    __=Depends(require_admin_ip),
):
    svc = _get_service()
    db = _get_db()
    async with db.get_session() as session:
        ep = await svc.get_endpoint(session, endpoint_id)
        if ep is None:
            raise HTTPException(status_code=404, detail="Webhook endpoint not found")
        return _endpoint_to_response(ep)


@router.patch("/webhooks/{endpoint_id}", response_model=WebhookEndpointResponse)
@limiter.limit(_admin_limit)
async def update_webhook_endpoint(
    request: Request,
    endpoint_id: str,
    body: WebhookEndpointUpdate,
    _=Depends(require_api_key),
    __=Depends(require_admin_ip),
):
    # Validate event types if provided
    if body.event_types is not None:
        for et in body.event_types:
            if et not in VALID_EVENT_TYPES:
                raise HTTPException(
                    status_code=422,
                    detail=f"Invalid event type: {et}. Valid types: {sorted(VALID_EVENT_TYPES)}",
                )

    svc = _get_service()
    db = _get_db()
    updates = body.model_dump(exclude_none=True)
    async with db.get_session() as session:
        ep = await svc.update_endpoint(session, endpoint_id, **updates)
        if ep is None:
            raise HTTPException(status_code=404, detail="Webhook endpoint not found")
        return _endpoint_to_response(ep)


@router.delete("/webhooks/{endpoint_id}", status_code=204)
@limiter.limit(_admin_limit)
async def delete_webhook_endpoint(
    request: Request,
    endpoint_id: str,
    _=Depends(require_api_key),
    __=Depends(require_admin_ip),
):
    svc = _get_service()
    db = _get_db()
    async with db.get_session() as session:
        deleted = await svc.delete_endpoint(session, endpoint_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Webhook endpoint not found")
    return Response(status_code=204)


@router.get(
    "/webhooks/{endpoint_id}/deliveries",
    response_model=list[WebhookDeliveryResponse],
)
@limiter.limit(_admin_limit)
async def list_endpoint_deliveries(
    request: Request,
    endpoint_id: str,
    event_type: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _=Depends(require_api_key),
    __=Depends(require_admin_ip),
):
    svc = _get_service()
    db = _get_db()
    async with db.get_session() as session:
        # Verify endpoint exists
        ep = await svc.get_endpoint(session, endpoint_id)
        if ep is None:
            raise HTTPException(status_code=404, detail="Webhook endpoint not found")
        deliveries = await svc.get_deliveries(
            session,
            endpoint_id=endpoint_id,
            event_type=event_type,
            status=status,
            limit=limit,
            offset=offset,
        )
        return [_delivery_to_response(d) for d in deliveries]


@router.post("/webhooks/{endpoint_id}/test", status_code=202)
@limiter.limit(_admin_limit)
async def test_webhook_endpoint(
    request: Request,
    endpoint_id: str,
    body: WebhookTestRequest | None = None,
    _=Depends(require_api_key),
    __=Depends(require_admin_ip),
):
    svc = _get_service()
    db = _get_db()
    async with db.get_session() as session:
        ep = await svc.get_endpoint(session, endpoint_id)
        if ep is None:
            raise HTTPException(status_code=404, detail="Webhook endpoint not found")

        test_payload = {
            "event_type": "webhook.test",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": {"message": "Test ping from Vinzy-Engine"},
        }
        delivery = WebhookDeliveryModel(
            endpoint_id=ep.id,
            event_type="webhook.test",
            payload=test_payload,
            status="pending",
        )
        session.add(delivery)
        await session.flush()

        import asyncio
        asyncio.create_task(
            svc._send_delivery(
                delivery_id=delivery.id,
                url=ep.url,
                secret=ep.secret,
                payload=test_payload,
                max_retries=ep.max_retries,
                timeout=ep.timeout_seconds,
            )
        )
        return _delivery_to_response(delivery)


@router.post(
    "/webhooks/deliveries/{delivery_id}/retry",
    response_model=WebhookDeliveryResponse,
)
@limiter.limit(_admin_limit)
async def retry_webhook_delivery(
    request: Request,
    delivery_id: str,
    _=Depends(require_api_key),
    __=Depends(require_admin_ip),
):
    svc = _get_service()
    db = _get_db()
    async with db.get_session() as session:
        delivery = await svc.retry_delivery(session, delivery_id)
        if delivery is None:
            raise HTTPException(status_code=404, detail="Delivery not found")
        return _delivery_to_response(delivery)
