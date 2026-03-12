"""Usage API router."""

from fastapi import APIRouter, Depends, Request

from vinzy_engine.common.exceptions import VinzyError
from vinzy_engine.common.security import require_api_key, require_admin_ip
from vinzy_engine.common.rate_limiting import limiter, _public_limit, _admin_limit
from vinzy_engine.usage.schemas import UsageRecordRequest, UsageRecordResponse, UsageSummary

router = APIRouter()


def _get_service():
    from vinzy_engine.deps import get_usage_service
    return get_usage_service()


def _get_db():
    from vinzy_engine.deps import get_db
    return get_db()


@router.post("/usage/record", response_model=UsageRecordResponse)
@limiter.limit(_public_limit)
async def record_usage(request: Request, body: UsageRecordRequest):
    svc = _get_service()
    db = _get_db()
    try:
        async with db.get_session() as session:
            result = await svc.record_usage(
                session,
                raw_key=body.key,
                metric=body.metric,
                value=body.value,
                metadata=body.metadata,
            )
            return result
    except VinzyError as e:
        return UsageRecordResponse(
            success=False, metric=body.metric,
            value_added=0, total_value=0, code=e.code,
        )


@router.get("/usage/{license_id}", response_model=list[UsageSummary])
@limiter.limit(_admin_limit)
async def get_usage(request: Request, license_id: str, _=Depends(require_api_key), __=Depends(require_admin_ip)):
    svc = _get_service()
    db = _get_db()
    async with db.get_session() as session:
        summaries = await svc.get_usage_summary(session, license_id)
        return summaries


@router.get("/usage/agents/{license_id}", response_model=dict[str, dict[str, float]])
@limiter.limit(_admin_limit)
async def get_agent_usage(request: Request, license_id: str, _=Depends(require_api_key), __=Depends(require_admin_ip)):
    svc = _get_service()
    db = _get_db()
    async with db.get_session() as session:
        summary = await svc.get_agent_usage_summary(session, license_id)
        return summary
