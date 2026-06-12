"""License usage report generation.

Generates usage, activation, and anomaly reports in JSON or CSV format."""

import csv
import io
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vinzy_engine.activation.models import MachineModel
from vinzy_engine.anomaly.models import AnomalyModel
from vinzy_engine.licensing.models import CustomerModel, LicenseModel, ProductModel
from vinzy_engine.usage.models import UsageRecordModel

logger = logging.getLogger(__name__)


class ReportFormat(str, Enum):
    JSON = "json"
    CSV = "csv"


class ReportType(str, Enum):
    USAGE = "usage"
    ACTIVATION = "activation"
    ANOMALY = "anomaly"


class LicenseReportGenerator:
    """Generates license-related reports."""

    async def generate_usage_report(self, session: AsyncSession, days: int = 30, tenant_id: str | None = None) -> dict[str, Any]:
        """Generate usage statistics by product and tenant."""
        since = datetime.now(timezone.utc) - timedelta(days=days)
        # Total usage records
        count_q = select(func.count(UsageRecordModel.id)).where(UsageRecordModel.created_at >= since)
        total_records = (await session.execute(count_q)).scalar() or 0

        # Usage by metric
        metric_q = (
            select(UsageRecordModel.metric, func.count(UsageRecordModel.id), func.sum(UsageRecordModel.value))
            .where(UsageRecordModel.created_at >= since)
            .group_by(UsageRecordModel.metric)
        )
        metric_result = await session.execute(metric_q)
        by_metric = [
            {"metric": row[0], "count": row[1], "total_value": float(row[2] or 0)}
            for row in metric_result.all()
        ]

        # Active licenses count
        filters = [LicenseModel.is_deleted == False, LicenseModel.status == "active"]
        if tenant_id is not None:
            filters.append(LicenseModel.tenant_id == tenant_id)
        active_count = (await session.execute(select(func.count(LicenseModel.id)).where(*filters))).scalar() or 0

        return {
            "report_type": "usage",
            "period_days": days,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_usage_records": total_records,
            "active_licenses": active_count,
            "by_metric": by_metric,
        }

    async def generate_activation_report(self, session: AsyncSession, days: int = 30) -> dict[str, Any]:
        """Generate activation success/failure rates."""
        since = datetime.now(timezone.utc) - timedelta(days=days)
        # Total machines activated in period
        total_q = select(func.count(MachineModel.id)).where(MachineModel.created_at >= since)
        total_activations = (await session.execute(total_q)).scalar() or 0

        # Activations by platform
        platform_q = (
            select(MachineModel.platform, func.count(MachineModel.id))
            .where(MachineModel.created_at >= since)
            .group_by(MachineModel.platform)
        )
        platform_result = await session.execute(platform_q)
        by_platform = [
            {"platform": row[0] or "unknown", "count": row[1]}
            for row in platform_result.all()
        ]

        # Licenses at machine limit (potential failures)
        at_limit_q = select(func.count(LicenseModel.id)).where(
            LicenseModel.is_deleted == False,
            LicenseModel.status == "active",
            LicenseModel.machines_used >= LicenseModel.machines_limit,
        )
        at_limit = (await session.execute(at_limit_q)).scalar() or 0

        return {
            "report_type": "activation",
            "period_days": days,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_activations": total_activations,
            "by_platform": by_platform,
            "licenses_at_machine_limit": at_limit,
        }

    async def generate_anomaly_report(self, session: AsyncSession, days: int = 30) -> dict[str, Any]:
        """Generate recent anomaly summary."""
        since = datetime.now(timezone.utc) - timedelta(days=days)
        # Total anomalies
        total_q = select(func.count(AnomalyModel.id)).where(AnomalyModel.created_at >= since)
        total = (await session.execute(total_q)).scalar() or 0

        # By severity
        sev_q = (
            select(AnomalyModel.severity, func.count(AnomalyModel.id))
            .where(AnomalyModel.created_at >= since)
            .group_by(AnomalyModel.severity)
        )
        sev_result = await session.execute(sev_q)
        by_severity = [{"severity": r[0], "count": r[1]} for r in sev_result.all()]

        # By type
        type_q = (
            select(AnomalyModel.anomaly_type, func.count(AnomalyModel.id))
            .where(AnomalyModel.created_at >= since)
            .group_by(AnomalyModel.anomaly_type)
        )
        type_result = await session.execute(type_q)
        by_type = [{"type": r[0], "count": r[1]} for r in type_result.all()]

        # Unresolved count
        unresolved_q = select(func.count(AnomalyModel.id)).where(AnomalyModel.resolved == False, AnomalyModel.created_at >= since)
        unresolved = (await session.execute(unresolved_q)).scalar() or 0

        return {
            "report_type": "anomaly",
            "period_days": days,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_anomalies": total,
            "unresolved": unresolved,
            "by_severity": by_severity,
            "by_type": by_type,
        }

    def export_json(self, report: dict[str, Any], indent: int = 2) -> str:
        """Export a report as a JSON string."""
        return json.dumps(report, indent=indent, default=str)

    def export_csv(self, report: dict[str, Any]) -> str:
        """Export a report as CSV.

        Flattens the report structure into rows suitable for CSV."""
        output = io.StringIO()
        writer = csv.writer(output)
        report_type = report.get("report_type", "unknown")

        if report_type == "usage":
            writer.writerow(["metric", "count", "total_value"])
            for row in report.get("by_metric", []):
                writer.writerow([row["metric"], row["count"], row["total_value"]])
        elif report_type == "activation":
            writer.writerow(["platform", "count"])
            for row in report.get("by_platform", []):
                writer.writerow([row["platform"], row["count"]])
        elif report_type == "anomaly":
            writer.writerow(["severity", "count"])
            for row in report.get("by_severity", []):
                writer.writerow([row["severity"], row["count"]])
        else:
            # Generic: dump top-level keys as single row
            writer.writerow(list(report.keys()))
            writer.writerow([str(v) for v in report.values()])

        return output.getvalue()


_report_generator: LicenseReportGenerator | None = None


def get_report_generator() -> LicenseReportGenerator:
    """Get the singleton report generator."""
    global _report_generator
    if _report_generator is None:
        _report_generator = LicenseReportGenerator()
    return _report_generator


def reset_report_generator() -> None:
    """Reset singleton (for testing)."""
    global _report_generator
    _report_generator = None
