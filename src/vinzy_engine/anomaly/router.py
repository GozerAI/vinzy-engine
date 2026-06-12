"""Anomaly detection API router."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from vinzy_engine.common.security import require_api_key, require_admin_ip
from vinzy_engine.common.rate_limiting import limiter, _admin_limit
from vinzy_engine.anomaly.schemas import AnomalyResolveRequest, AnomalyResponse

router = APIRouter()


def _get_service():
    from vinzy_engine.deps import get_anomaly_service
    return get_anomaly_service()


def _get_db():
    from vinzy_engine.deps import get_db
    return get_db()


@router.get("/anomalies/{license_id}", response_model=list[AnomalyResponse])
@limiter.limit(_admin_limit)
async def get_anomalies(
    request: Request,
    license_id: str,
    resolved: bool | None = Query(None),
    severity: str | None = Query(None),
    _=Depends(require_api_key),
    __=Depends(require_admin_ip),
):
    svc = _get_service()
    db = _get_db()
    async with db.get_session() as session:
        anomalies = await svc.get_anomalies(
            session, license_id, resolved=resolved, severity=severity,
        )
        return [
            AnomalyResponse(
                id=a.id,
                license_id=a.license_id,
                anomaly_type=a.anomaly_type,
                severity=a.severity,
                metric=a.metric,
                z_score=a.z_score,
                baseline_mean=a.baseline_mean,
                baseline_stddev=a.baseline_stddev,
                observed_value=a.observed_value,
                detail=a.detail or {},
                resolved=a.resolved,
                resolved_by=a.resolved_by,
                resolved_at=a.resolved_at,
                created_at=a.created_at,
            )
            for a in anomalies
        ]


@router.post("/anomalies/{anomaly_id}/resolve", response_model=AnomalyResponse)
@limiter.limit(_admin_limit)
async def resolve_anomaly(
    request: Request,
    anomaly_id: str,
    body: AnomalyResolveRequest,
    _=Depends(require_api_key),
    __=Depends(require_admin_ip),
):
    svc = _get_service()
    db = _get_db()
    async with db.get_session() as session:
        anomaly = await svc.resolve_anomaly(session, anomaly_id, body.resolved_by)
        if anomaly is None:
            raise HTTPException(status_code=404, detail="Anomaly not found")
        return AnomalyResponse(
            id=anomaly.id,
            license_id=anomaly.license_id,
            anomaly_type=anomaly.anomaly_type,
            severity=anomaly.severity,
            metric=anomaly.metric,
            z_score=anomaly.z_score,
            baseline_mean=anomaly.baseline_mean,
            baseline_stddev=anomaly.baseline_stddev,
            observed_value=anomaly.observed_value,
            detail=anomaly.detail or {},
            resolved=anomaly.resolved,
            resolved_by=anomaly.resolved_by,
            resolved_at=anomaly.resolved_at,
            created_at=anomaly.created_at,
        )
