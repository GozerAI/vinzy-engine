"""Activation API router."""

from fastapi import APIRouter, HTTPException, Request

from vinzy_engine.common.exceptions import ActivationLimitError, VinzyError
from vinzy_engine.common.rate_limiting import limiter, _public_limit
from vinzy_engine.activation.schemas import (
    ActivateRequest,
    ActivateResponse,
    DeactivateRequest,
    DeactivateResponse,
    HeartbeatRequest,
    HeartbeatResponse,
)

router = APIRouter()


def _get_service():
    from vinzy_engine.deps import get_activation_service
    return get_activation_service()


def _get_db():
    from vinzy_engine.deps import get_db
    return get_db()


@router.post("/activate", response_model=ActivateResponse)
@limiter.limit(_public_limit)
async def activate(request: Request, body: ActivateRequest):
    svc = _get_service()
    db = _get_db()
    try:
        async with db.get_session() as session:
            result = await svc.activate(
                session,
                raw_key=body.key,
                fingerprint=body.fingerprint,
                hostname=body.hostname,
                platform=body.platform,
                metadata=body.metadata,
            )
            return result
    except ActivationLimitError as e:
        return ActivateResponse(
            success=False, code=e.code, message=e.message
        )
    except VinzyError as e:
        return ActivateResponse(
            success=False, code=e.code, message=e.message
        )


@router.post("/deactivate", response_model=DeactivateResponse)
@limiter.limit(_public_limit)
async def deactivate(request: Request, body: DeactivateRequest):
    svc = _get_service()
    db = _get_db()
    try:
        async with db.get_session() as session:
            result = await svc.deactivate(
                session, raw_key=body.key, fingerprint=body.fingerprint
            )
            return DeactivateResponse(success=result)
    except VinzyError as e:
        raise HTTPException(status_code=404, detail=e.message)


@router.post("/heartbeat", response_model=HeartbeatResponse)
@limiter.limit(_public_limit)
async def heartbeat(request: Request, body: HeartbeatRequest):
    svc = _get_service()
    db = _get_db()
    try:
        async with db.get_session() as session:
            result = await svc.heartbeat(
                session,
                raw_key=body.key,
                fingerprint=body.fingerprint,
                version=body.version,
            )
            if result:
                return HeartbeatResponse(success=True, code="OK", message="Heartbeat recorded")
            return HeartbeatResponse(
                success=False, code="NOT_FOUND", message="Machine not activated"
            )
    except VinzyError as e:
        return HeartbeatResponse(success=False, code=e.code, message=e.message)
