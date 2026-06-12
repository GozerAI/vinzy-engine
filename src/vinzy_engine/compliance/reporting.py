"""License usage compliance reporting.

Generates compliance reports from usage data, anomaly history, and fraud
signals. Produces summaries suitable for auditing and regulatory purposes.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class ComplianceStatus(str, Enum):
    COMPLIANT = "compliant"
    WARNING = "warning"
    VIOLATION = "violation"
    UNDER_REVIEW = "under_review"


@dataclass
class LicenseComplianceEntry:
    """Compliance status for a single license."""

    license_id: str
    status: ComplianceStatus = ComplianceStatus.COMPLIANT
    machines_limit: int = 0
    machines_used: int = 0
    anomaly_count: int = 0
    fraud_signal_count: int = 0
    usage_within_limits: bool = True
    violations: list[str] = field(default_factory=list)
    last_checked_at: float = field(default_factory=time.monotonic)

    @property
    def is_compliant(self) -> bool:
        return self.status == ComplianceStatus.COMPLIANT

    def to_dict(self) -> dict[str, Any]:
        return {
            "license_id": self.license_id,
            "status": self.status.value,
            "machines_limit": self.machines_limit,
            "machines_used": self.machines_used,
            "anomaly_count": self.anomaly_count,
            "fraud_signal_count": self.fraud_signal_count,
            "usage_within_limits": self.usage_within_limits,
            "violations": self.violations,
            "last_checked_at": self.last_checked_at,
        }


@dataclass
class ComplianceReport:
    """Aggregate compliance report over multiple licenses."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    generated_at: float = field(default_factory=time.monotonic)
    total_licenses: int = 0
    compliant_count: int = 0
    warning_count: int = 0
    violation_count: int = 0
    review_count: int = 0
    entries: list[LicenseComplianceEntry] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    @property
    def compliance_rate(self) -> float:
        if self.total_licenses == 0:
            return 1.0
        return self.compliant_count / self.total_licenses

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "generated_at": self.generated_at,
            "total_licenses": self.total_licenses,
            "compliant_count": self.compliant_count,
            "warning_count": self.warning_count,
            "violation_count": self.violation_count,
            "review_count": self.review_count,
            "compliance_rate": round(self.compliance_rate, 4),
            "entries": [e.to_dict() for e in self.entries],
            "summary": self.summary,
        }


class ComplianceReporter:
    """Generates compliance reports from license usage data.

    Accepts license data dicts with keys:
      - license_id, machines_limit, machines_used, status
      - anomaly_count (optional), fraud_signal_count (optional)
      - usage_records (optional list of {metric, value, limit})
    """

    def __init__(
        self,
        machine_overuse_threshold: float = 1.0,
        anomaly_warning_threshold: int = 3,
        anomaly_violation_threshold: int = 10,
        fraud_warning_threshold: int = 1,
        fraud_violation_threshold: int = 3,
    ) -> None:
        self._machine_overuse_threshold = machine_overuse_threshold
        self._anomaly_warning = anomaly_warning_threshold
        self._anomaly_violation = anomaly_violation_threshold
        self._fraud_warning = fraud_warning_threshold
        self._fraud_violation = fraud_violation_threshold
        self._reports: list[ComplianceReport] = []

    def assess_license(self, license_data: dict[str, Any]) -> LicenseComplianceEntry:
        """Assess compliance for a single license."""
        entry = LicenseComplianceEntry(
            license_id=license_data.get("license_id", ""),
            machines_limit=license_data.get("machines_limit", 0),
            machines_used=license_data.get("machines_used", 0),
            anomaly_count=license_data.get("anomaly_count", 0),
            fraud_signal_count=license_data.get("fraud_signal_count", 0),
        )

        violations: list[str] = []

        # Machine limit check
        if entry.machines_limit > 0 and entry.machines_used > entry.machines_limit:
            ratio = entry.machines_used / entry.machines_limit
            if ratio > self._machine_overuse_threshold + 0.5:
                violations.append(
                    f"Machine overuse: {entry.machines_used}/{entry.machines_limit}"
                )
            entry.usage_within_limits = False

        # Usage record checks
        for record in license_data.get("usage_records", []):
            limit = record.get("limit")
            value = record.get("value", 0)
            if limit is not None and value > limit:
                entry.usage_within_limits = False
                violations.append(
                    f"Usage exceeded: {record.get('metric', '?')} "
                    f"{value}/{limit}"
                )

        # Anomaly checks
        if entry.anomaly_count >= self._anomaly_violation:
            violations.append(
                f"High anomaly count: {entry.anomaly_count}"
            )

        # Fraud signal checks
        if entry.fraud_signal_count >= self._fraud_violation:
            violations.append(
                f"Fraud signals detected: {entry.fraud_signal_count}"
            )

        entry.violations = violations

        # Determine status
        if violations:
            entry.status = ComplianceStatus.VIOLATION
        elif (
            entry.anomaly_count >= self._anomaly_warning
            or entry.fraud_signal_count >= self._fraud_warning
            or (entry.machines_limit > 0 and entry.machines_used > entry.machines_limit)
        ):
            entry.status = ComplianceStatus.WARNING
        elif license_data.get("status") == "suspended":
            entry.status = ComplianceStatus.UNDER_REVIEW
        else:
            entry.status = ComplianceStatus.COMPLIANT

        return entry

    def generate_report(
        self, licenses: list[dict[str, Any]],
    ) -> ComplianceReport:
        """Generate a compliance report for a batch of licenses."""
        report = ComplianceReport(total_licenses=len(licenses))

        for lic_data in licenses:
            entry = self.assess_license(lic_data)
            report.entries.append(entry)

            if entry.status == ComplianceStatus.COMPLIANT:
                report.compliant_count += 1
            elif entry.status == ComplianceStatus.WARNING:
                report.warning_count += 1
            elif entry.status == ComplianceStatus.VIOLATION:
                report.violation_count += 1
            elif entry.status == ComplianceStatus.UNDER_REVIEW:
                report.review_count += 1

        # Build summary
        report.summary = {
            "compliance_rate": round(report.compliance_rate, 4),
            "total_violations": sum(len(e.violations) for e in report.entries),
            "licenses_over_machine_limit": sum(
                1 for e in report.entries
                if e.machines_limit > 0 and e.machines_used > e.machines_limit
            ),
            "licenses_with_anomalies": sum(
                1 for e in report.entries if e.anomaly_count > 0
            ),
            "licenses_with_fraud_signals": sum(
                1 for e in report.entries if e.fraud_signal_count > 0
            ),
        }

        self._reports.append(report)
        return report

    def get_reports(self, limit: int = 50) -> list[ComplianceReport]:
        return self._reports[-limit:]

    def get_latest_report(self) -> Optional[ComplianceReport]:
        return self._reports[-1] if self._reports else None

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "total_reports_generated": len(self._reports),
        }

    def clear(self) -> None:
        self._reports.clear()
