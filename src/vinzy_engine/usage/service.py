"""Usage service — record and query metered usage."""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from datetime import datetime, timezone

from vinzy_engine.common.config import VinzySettings
from vinzy_engine.common.exceptions import (
    LicenseExpiredError,
    LicenseNotFoundError,
    LicenseSuspendedError,
)
from vinzy_engine.licensing.models import LicenseModel
from vinzy_engine.licensing.service import LicensingService
from vinzy_engine.usage.models import UsageRecordModel


class UsageService:
    """Metered usage tracking operations."""

    def __init__(self, settings: VinzySettings, licensing: LicensingService, audit_service=None, anomaly_service=None, webhook_service=None):
        self.settings = settings
        self.licensing = licensing
        self.audit_service = audit_service
        self.anomaly_service = anomaly_service
        self.webhook_service = webhook_service

    async def record_usage(
        self,
        session: AsyncSession,
        raw_key: str,
        metric: str,
        value: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> dict:
        """Record a usage event for a licensed metric."""
        license_obj = await self.licensing.get_license_by_key(session, raw_key)
        if license_obj is None:
            raise LicenseNotFoundError()

        # Enforce license validity — reject suspended/revoked/expired keys
        if license_obj.status in ("suspended", "revoked"):
            raise LicenseSuspendedError(f"License is {license_obj.status}")
        if license_obj.status == "expired":
            raise LicenseExpiredError()
        if license_obj.expires_at:
            expires = license_obj.expires_at
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires < datetime.now(timezone.utc):
                raise LicenseExpiredError()

        # Anomaly scan — run BEFORE inserting usage so history reflects prior behavior only
        if self.anomaly_service:
            await self.anomaly_service.scan_and_record(
                session, license_obj.id, metric, value,
            )

        # Create usage record
        record = UsageRecordModel(
            license_id=license_obj.id,
            metric=metric,
            value=value,
            metadata_=metadata or {},
        )
        session.add(record)
        await session.flush()

        # Calculate total for this metric
        total_result = await session.execute(
            select(func.sum(UsageRecordModel.value)).where(
                UsageRecordModel.license_id == license_obj.id,
                UsageRecordModel.metric == metric,
            )
        )
        total_value = total_result.scalar() or 0.0

        # Check entitlement limits
        entitlements = license_obj.entitlements or {}
        limit = None
        remaining = None
        if metric in entitlements:
            ent = entitlements[metric]
            if isinstance(ent, dict):
                limit = ent.get("limit")
            if limit is not None:
                remaining = max(0.0, limit - total_value)

        # Audit: usage.recorded
        if self.audit_service:
            await self.audit_service.record_event(
                session, license_obj.id, "usage.recorded", "system",
                {"metric": metric, "value": value},
            )

        # Webhook: usage.recorded
        if self.webhook_service:
            await self.webhook_service.dispatch(
                session, "usage.recorded",
                {"license_id": license_obj.id, "metric": metric, "value": value},
            )

        return {
            "success": True,
            "metric": metric,
            "value_added": value,
            "total_value": total_value,
            "limit": limit,
            "remaining": remaining,
            "code": "RECORDED",
        }

    async def get_usage_summary(
        self,
        session: AsyncSession,
        license_id: str,
    ) -> list[dict]:
        """Get usage summary for all metrics of a license."""
        result = await session.execute(
            select(
                UsageRecordModel.metric,
                func.sum(UsageRecordModel.value).label("total_value"),
                func.count(UsageRecordModel.id).label("record_count"),
            )
            .where(UsageRecordModel.license_id == license_id)
            .group_by(UsageRecordModel.metric)
        )

        # Get license for entitlement limits
        lic_result = await session.execute(
            select(LicenseModel).where(LicenseModel.id == license_id)
        )
        license_obj = lic_result.scalar_one_or_none()
        entitlements = (license_obj.entitlements or {}) if license_obj else {}

        summaries = []
        for row in result:
            metric = row.metric
            total = row.total_value or 0.0
            count = row.record_count or 0

            limit = None
            remaining = None
            if metric in entitlements:
                ent = entitlements[metric]
                if isinstance(ent, dict):
                    limit = ent.get("limit")
                if limit is not None:
                    remaining = max(0.0, limit - total)

            summaries.append({
                "metric": metric,
                "total_value": total,
                "record_count": count,
                "limit": limit,
                "remaining": remaining,
            })

        return summaries

    async def get_agent_usage_summary(
        self,
        session: AsyncSession,
        license_id: str,
    ) -> dict[str, dict[str, float]]:
        """Get per-agent usage breakdown for a license.

        Queries records where metric starts with 'agent.' and aggregates.
        Returns: {"CTO": {"tokens": 5000, "delegations": 12}, ...}
        """
        from vinzy_engine.usage.agent_usage import AGENT_METRIC_PREFIX, aggregate_agent_usage

        result = await session.execute(
            select(
                UsageRecordModel.metric,
                func.sum(UsageRecordModel.value).label("total_value"),
            )
            .where(
                UsageRecordModel.license_id == license_id,
                UsageRecordModel.metric.startswith(AGENT_METRIC_PREFIX),
            )
            .group_by(UsageRecordModel.metric)
        )

        records = [
            {"metric": row.metric, "value": row.total_value or 0.0}
            for row in result
        ]
        return aggregate_agent_usage(records)
