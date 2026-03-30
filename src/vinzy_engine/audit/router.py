"""Audit chain API router."""

from fastapi import APIRouter, Depends, Query, Request

from vinzy_engine.common.security import require_api_key, require_admin_ip
from vinzy_engine.common.rate_limiting import limiter, _admin_limit
from vinzy_engine.audit.schemas import AuditEventResponse, AuditChainVerification

router = APIRouter()


def _get_service():
    from vinzy_engine.deps import get_audit_service
    return get_audit_service()


def _get_db():
    from vinzy_engine.deps import get_db
    return get_db()


@router.get("/audit/{license_id}", response_model=list[AuditEventResponse])
@limiter.limit(_admin_limit)
async def get_audit_events(
    request: Request,
    license_id: str,
    event_type: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _=Depends(require_api_key),
    __=Depends(require_admin_ip),
):
    svc = _get_service()
    db = _get_db()
    async with db.get_session() as session:
        events = await svc.get_events(
            session, license_id, event_type=event_type,
            limit=limit, offset=offset,
        )
        return [
            AuditEventResponse(
                id=e.id,
                license_id=e.license_id,
                event_type=e.event_type,
                actor=e.actor,
                detail=e.detail or {},
                prev_hash=e.prev_hash,
                event_hash=e.event_hash,
                signature=e.signature,
                created_at=e.created_at,
            )
            for e in events
        ]


@router.get("/audit/{license_id}/verify", response_model=AuditChainVerification)
@limiter.limit(_admin_limit)
async def verify_audit_chain(
    request: Request,
    license_id: str, _=Depends(require_api_key),
    __=Depends(require_admin_ip),
):
    svc = _get_service()
    db = _get_db()
    async with db.get_session() as session:
        result = await svc.verify_chain(session, license_id)
        return AuditChainVerification(**result)
