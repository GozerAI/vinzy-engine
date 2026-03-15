"""Enterprise license compliance reporting.

Item 422: Generate compliance reports for enterprise license usage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class ComplianceStatus(str, Enum):
    COMPLIANT = "compliant"
    WARNING = "warning"
    NON_COMPLIANT = "non_compliant"
    AUDIT_REQUIRED = "audit_required"


@dataclass
class ComplianceViolation:
    """A license compliance violation."""
    violation_id: str
    tenant_id: str
    violation_type: str  # over_usage, expired_license, unauthorized_feature, seat_exceeded
    severity: str  # low, medium, high, critical
    description: str
    license_id: str | None = None
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolved: bool = False
    resolved_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ComplianceReport:
    """Enterprise compliance report."""
    report_id: str
    tenant_id: str
    period_start: datetime
    period_end: datetime
    overall_status: ComplianceStatus
    total_licenses: int
    compliant_licenses: int
    violations: list[ComplianceViolation]
    usage_within_limits: bool
    seat_utilization_pct: float
    feature_compliance: dict[str, bool]
    recommendations: list[str]
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


class ComplianceReportingEngine:
    """Generate enterprise license compliance reports."""

    def __init__(self):
        self._violations: list[ComplianceViolation] = []
        self._reports: list[ComplianceReport] = []
        self._violation_counter = 0
        self._report_counter = 0

    def _next_violation_id(self) -> str:
        self._violation_counter += 1
        return f"VIOL-{self._violation_counter:06d}"

    def _next_report_id(self) -> str:
        self._report_counter += 1
        return f"CRPT-{self._report_counter:06d}"

    def record_violation(
        self,
        tenant_id: str,
        violation_type: str,
        severity: str,
        description: str,
        license_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ComplianceViolation:
        violation = ComplianceViolation(
            violation_id=self._next_violation_id(),
            tenant_id=tenant_id,
            violation_type=violation_type,
            severity=severity,
            description=description,
            license_id=license_id,
            metadata=metadata or {},
        )
        self._violations.append(violation)
        return violation

    def resolve_violation(self, violation_id: str) -> ComplianceViolation:
        for v in self._violations:
            if v.violation_id == violation_id:
                v.resolved = True
                v.resolved_at = datetime.now(timezone.utc)
                return v
        raise ValueError(f"Violation not found: {violation_id}")

    def generate_report(
        self,
        tenant_id: str,
        period_start: datetime,
        period_end: datetime,
        licenses: list[dict[str, Any]],
        usage_data: list[dict[str, Any]] | None = None,
        seat_pool_data: dict[str, Any] | None = None,
    ) -> ComplianceReport:
        """Generate a comprehensive compliance report."""
        usage_data = usage_data or []
        seat_pool = seat_pool_data or {}

        # Get violations for this tenant in period
        violations = [
            v for v in self._violations
            if v.tenant_id == tenant_id
            and not v.resolved
        ]

        total = len(licenses)
        compliant = sum(1 for l in licenses if l.get("status") == "active")

        # Usage compliance
        usage_within = True
        for lic in licenses:
            lic_usage = sum(
                u.get("value", 0) for u in usage_data
                if u.get("license_id") == lic.get("id")
            )
            limit = lic.get("limit", 0)
            if limit and lic_usage > limit:
                usage_within = False
                break

        # Seat utilization
        total_seats = seat_pool.get("total_seats", total)
        allocated_seats = seat_pool.get("allocated_seats", compliant)
        utilization = round(allocated_seats / total_seats * 100, 2) if total_seats else 0

        # Feature compliance
        feature_compliance: dict[str, bool] = {}
        for lic in licenses:
            features = lic.get("features", {})
            for feat, allowed in features.items():
                feature_compliance[feat] = feature_compliance.get(feat, True) and bool(allowed)

        # Overall status
        if violations:
            high_violations = [v for v in violations if v.severity in ("high", "critical")]
            if high_violations:
                overall = ComplianceStatus.NON_COMPLIANT
            else:
                overall = ComplianceStatus.WARNING
        elif not usage_within:
            overall = ComplianceStatus.WARNING
        else:
            overall = ComplianceStatus.COMPLIANT

        # Recommendations
        recommendations: list[str] = []
        if not usage_within:
            recommendations.append("Consider upgrading tier to accommodate current usage levels")
        if utilization < 50:
            recommendations.append(f"License utilization is low ({utilization}%) - consider pool consolidation")
        if utilization > 90:
            recommendations.append("Approaching seat limit - consider expanding pool")
        if violations:
            recommendations.append(f"Resolve {len(violations)} outstanding compliance violations")

        report = ComplianceReport(
            report_id=self._next_report_id(),
            tenant_id=tenant_id,
            period_start=period_start,
            period_end=period_end,
            overall_status=overall,
            total_licenses=total,
            compliant_licenses=compliant,
            violations=violations,
            usage_within_limits=usage_within,
            seat_utilization_pct=utilization,
            feature_compliance=feature_compliance,
            recommendations=recommendations,
        )
        self._reports.append(report)
        return report

    def get_violations(self, tenant_id: str | None = None, resolved: bool | None = None) -> list[ComplianceViolation]:
        results = self._violations
        if tenant_id:
            results = [v for v in results if v.tenant_id == tenant_id]
        if resolved is not None:
            results = [v for v in results if v.resolved == resolved]
        return results

    def get_reports(self, tenant_id: str | None = None) -> list[ComplianceReport]:
        if tenant_id:
            return [r for r in self._reports if r.tenant_id == tenant_id]
        return list(self._reports)
