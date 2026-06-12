"""Anomaly service — scan, record, and manage detected anomalies."""

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vinzy_engine.common.config import VinzySettings
from vinzy_engine.anomaly.detector import detect_anomalies
from vinzy_engine.anomaly.models import AnomalyModel
from vinzy_engine.usage.models import UsageRecordModel


class AnomalyService:
    """Behavioral anomaly detection and management."""

    def __init__(self, settings: VinzySettings, audit_service=None, webhook_service=None):
        self.settings = settings
        self.audit_service = audit_service
        self.webhook_service = webhook_service

    async def scan_and_record(
        self,
        session: AsyncSession,
        license_id: str,
        metric: str,
        current_value: float,
    ) -> Optional[AnomalyModel]:
        """
        Scan a usage observation against recent history.

        If anomalous, creates an AnomalyModel and records an audit event.
        Returns the anomaly model or None if normal.
        """
        # Load historical values for this license+metric
        result = await session.execute(
            select(UsageRecordModel.value)
            .where(
                UsageRecordModel.license_id == license_id,
                UsageRecordModel.metric == metric,
            )
            .order_by(UsageRecordModel.created_at.desc())
            .limit(30)
        )
        history = [row[0] for row in result.all()]
        history.reverse()  # oldest first

        # Need minimum history for meaningful anomaly detection
        if len(history) < 3:
            return None

        report = detect_anomalies(current_value, history, metric)
        if report is None:
            return None

        anomaly = AnomalyModel(
            license_id=license_id,
            anomaly_type=report.anomaly_type,
            severity=report.severity,
            metric=report.metric,
            z_score=report.z_score,
            baseline_mean=report.baseline_mean,
            baseline_stddev=report.baseline_stddev,
            observed_value=report.observed_value,
            detail={},
        )
        session.add(anomaly)
        await session.flush()

        # Record audit event
        if self.audit_service:
            await self.audit_service.record_event(
                session, license_id, "anomaly.detected", "system",
                {
                    "anomaly_id": anomaly.id,
                    "anomaly_type": anomaly.anomaly_type,
                    "severity": anomaly.severity,
                    "metric": metric,
                    "z_score": anomaly.z_score,
                },
            )

        # Webhook: anomaly.detected
        if self.webhook_service:
            await self.webhook_service.dispatch(
                session, "anomaly.detected",
                {
                    "anomaly_id": anomaly.id,
                    "license_id": license_id,
                    "anomaly_type": anomaly.anomaly_type,
                    "severity": anomaly.severity,
                    "metric": metric,
                    "z_score": anomaly.z_score,
                },
            )

        return anomaly

    async def list_all_anomalies(
        self,
        session: AsyncSession,
        resolved: Optional[bool] = None,
        severity: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[AnomalyModel], int]:
        """List anomalies across all licenses with count. Returns (items, total)."""
        filters = []
        if resolved is not None:
            filters.append(AnomalyModel.resolved == resolved)
        if severity is not None:
            filters.append(AnomalyModel.severity == severity)

        count_q = select(func.count(AnomalyModel.id))
        if filters:
            count_q = count_q.where(*filters)
        total = (await session.execute(count_q)).scalar() or 0

        query = select(AnomalyModel)
        if filters:
            query = query.where(*filters)
        query = query.order_by(AnomalyModel.created_at.desc()).offset(offset).limit(limit)
        result = await session.execute(query)
        return list(result.scalars().all()), total

    async def get_anomalies(
        self,
        session: AsyncSession,
        license_id: str,
        resolved: Optional[bool] = None,
        severity: Optional[str] = None,
    ) -> list[AnomalyModel]:
        """List anomalies for a license with optional filtering."""
        query = select(AnomalyModel).where(
            AnomalyModel.license_id == license_id,
        )
        if resolved is not None:
            query = query.where(AnomalyModel.resolved == resolved)
        if severity is not None:
            query = query.where(AnomalyModel.severity == severity)
        query = query.order_by(AnomalyModel.created_at.desc())
        result = await session.execute(query)
        return list(result.scalars().all())

    async def resolve_anomaly(
        self,
        session: AsyncSession,
        anomaly_id: str,
        resolved_by: str,
    ) -> Optional[AnomalyModel]:
        """Mark an anomaly as resolved."""
        result = await session.execute(
            select(AnomalyModel).where(AnomalyModel.id == anomaly_id)
        )
        anomaly = result.scalar_one_or_none()
        if anomaly is None:
            return None
        anomaly.resolved = True
        anomaly.resolved_by = resolved_by
        anomaly.resolved_at = datetime.now(timezone.utc)
        await session.flush()
        return anomaly
