"""License anomaly investigation automation.

Automates the investigation pipeline when anomalies or fraud signals are
detected: collects evidence, correlates events, assigns severity, and
produces investigation reports.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class InvestigationStatus(str, Enum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class EvidenceType(str, Enum):
    ANOMALY = "anomaly"
    FRAUD_SIGNAL = "fraud_signal"
    USAGE_PATTERN = "usage_pattern"
    AUDIT_EVENT = "audit_event"
    MANUAL = "manual"


@dataclass
class EvidenceItem:
    """A piece of evidence in an investigation."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    evidence_type: EvidenceType = EvidenceType.MANUAL
    source: str = ""
    description: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    severity_weight: float = 1.0
    collected_at: float = field(default_factory=time.monotonic)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "evidence_type": self.evidence_type.value,
            "source": self.source,
            "description": self.description,
            "data": self.data,
            "severity_weight": self.severity_weight,
            "collected_at": self.collected_at,
        }


@dataclass
class InvestigationReport:
    """Complete investigation report for a license."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    license_id: str = ""
    status: InvestigationStatus = InvestigationStatus.OPEN
    evidence: list[EvidenceItem] = field(default_factory=list)
    severity_score: float = 0.0
    recommended_action: str = ""
    notes: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.monotonic)
    resolved_at: Optional[float] = None
    resolved_by: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "license_id": self.license_id,
            "status": self.status.value,
            "evidence_count": len(self.evidence),
            "evidence": [e.to_dict() for e in self.evidence],
            "severity_score": round(self.severity_score, 2),
            "recommended_action": self.recommended_action,
            "notes": self.notes,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
            "resolved_by": self.resolved_by,
        }


class InvestigationEngine:
    """Automates license anomaly investigation workflows.

    Collects evidence, correlates signals, calculates severity scores,
    and recommends actions based on the weight of evidence.

    Thresholds for recommended actions:
      - severity < 3.0: "monitor" (keep watching)
      - severity < 6.0: "restrict" (throttle or limit usage)
      - severity < 9.0: "suspend" (temporarily disable license)
      - severity >= 9.0: "revoke" (permanently disable)
    """

    def __init__(self, max_investigations: int = 10_000) -> None:
        self._investigations: dict[str, InvestigationReport] = {}
        self._by_license: dict[str, list[str]] = {}
        self._max = max_investigations
        self._total_created = 0
        self._total_resolved = 0

    def open_investigation(self, license_id: str) -> InvestigationReport:
        """Open a new investigation for a license."""
        report = InvestigationReport(
            license_id=license_id,
            status=InvestigationStatus.OPEN,
        )
        self._investigations[report.id] = report
        self._by_license.setdefault(license_id, []).append(report.id)
        self._total_created += 1
        self._enforce_limit()
        return report

    def add_evidence(
        self,
        investigation_id: str,
        evidence_type: EvidenceType,
        source: str,
        description: str,
        data: Optional[dict[str, Any]] = None,
        severity_weight: float = 1.0,
    ) -> Optional[EvidenceItem]:
        """Add an evidence item to an investigation."""
        report = self._investigations.get(investigation_id)
        if report is None:
            return None
        if report.status in (InvestigationStatus.RESOLVED, InvestigationStatus.DISMISSED):
            return None

        item = EvidenceItem(
            evidence_type=evidence_type,
            source=source,
            description=description,
            data=data or {},
            severity_weight=severity_weight,
        )
        report.evidence.append(item)
        report.status = InvestigationStatus.INVESTIGATING
        self._recalculate(report)
        return item

    def add_anomaly_evidence(
        self, investigation_id: str, anomaly_data: dict[str, Any],
    ) -> Optional[EvidenceItem]:
        """Convenience: add anomaly detection result as evidence."""
        severity = anomaly_data.get("severity", "medium")
        weight_map = {"low": 0.5, "medium": 1.0, "high": 2.0, "critical": 3.0}
        weight = weight_map.get(severity, 1.0)
        return self.add_evidence(
            investigation_id,
            EvidenceType.ANOMALY,
            source="anomaly_detector",
            description=f"Anomaly: {anomaly_data.get('anomaly_type', 'unknown')} ({severity})",
            data=anomaly_data,
            severity_weight=weight,
        )

    def add_fraud_evidence(
        self, investigation_id: str, fraud_data: dict[str, Any],
    ) -> Optional[EvidenceItem]:
        """Convenience: add fraud signal as evidence."""
        severity = fraud_data.get("severity", "medium")
        weight_map = {"low": 1.0, "medium": 2.0, "high": 3.0, "critical": 5.0}
        weight = weight_map.get(severity, 2.0)
        return self.add_evidence(
            investigation_id,
            EvidenceType.FRAUD_SIGNAL,
            source="fraud_detector",
            description=f"Fraud: {fraud_data.get('fraud_type', 'unknown')} ({severity})",
            data=fraud_data,
            severity_weight=weight,
        )

    def escalate(self, investigation_id: str, note: str = "") -> bool:
        """Escalate an investigation for manual review."""
        report = self._investigations.get(investigation_id)
        if report is None:
            return False
        report.status = InvestigationStatus.ESCALATED
        if note:
            report.notes.append(f"Escalated: {note}")
        return True

    def resolve(
        self, investigation_id: str, resolved_by: str, note: str = "",
    ) -> bool:
        """Resolve an investigation."""
        report = self._investigations.get(investigation_id)
        if report is None:
            return False
        report.status = InvestigationStatus.RESOLVED
        report.resolved_at = time.monotonic()
        report.resolved_by = resolved_by
        if note:
            report.notes.append(f"Resolved: {note}")
        self._total_resolved += 1
        return True

    def dismiss(self, investigation_id: str, reason: str = "") -> bool:
        """Dismiss an investigation as a false positive."""
        report = self._investigations.get(investigation_id)
        if report is None:
            return False
        report.status = InvestigationStatus.DISMISSED
        report.resolved_at = time.monotonic()
        if reason:
            report.notes.append(f"Dismissed: {reason}")
        self._total_resolved += 1
        return True

    def get_investigation(self, investigation_id: str) -> Optional[InvestigationReport]:
        return self._investigations.get(investigation_id)

    def get_investigations_for_license(
        self, license_id: str, status: Optional[InvestigationStatus] = None,
    ) -> list[InvestigationReport]:
        ids = self._by_license.get(license_id, [])
        reports = [self._investigations[i] for i in ids if i in self._investigations]
        if status is not None:
            reports = [r for r in reports if r.status == status]
        return reports

    def list_investigations(
        self,
        status: Optional[InvestigationStatus] = None,
        min_severity: float = 0.0,
        limit: int = 100,
    ) -> list[InvestigationReport]:
        reports = list(self._investigations.values())
        if status is not None:
            reports = [r for r in reports if r.status == status]
        reports = [r for r in reports if r.severity_score >= min_severity]
        reports.sort(key=lambda r: r.severity_score, reverse=True)
        return reports[:limit]

    @property
    def stats(self) -> dict[str, Any]:
        statuses = {}
        for r in self._investigations.values():
            statuses[r.status.value] = statuses.get(r.status.value, 0) + 1
        return {
            "total_created": self._total_created,
            "total_resolved": self._total_resolved,
            "active_investigations": len(self._investigations),
            "by_status": statuses,
        }

    def clear(self) -> None:
        self._investigations.clear()
        self._by_license.clear()

    # -- Internal --

    def _recalculate(self, report: InvestigationReport) -> None:
        """Recalculate severity score and recommended action."""
        report.severity_score = sum(e.severity_weight for e in report.evidence)

        if report.severity_score >= 9.0:
            report.recommended_action = "revoke"
        elif report.severity_score >= 6.0:
            report.recommended_action = "suspend"
        elif report.severity_score >= 3.0:
            report.recommended_action = "restrict"
        else:
            report.recommended_action = "monitor"

        # Auto-escalate on critical severity
        if report.severity_score >= 9.0 and report.status == InvestigationStatus.INVESTIGATING:
            report.status = InvestigationStatus.ESCALATED
            report.notes.append("Auto-escalated: severity score >= 9.0")

    def _enforce_limit(self) -> None:
        """Evict oldest resolved investigations if over limit."""
        if len(self._investigations) <= self._max:
            return
        resolved = sorted(
            (r for r in self._investigations.values()
             if r.status in (InvestigationStatus.RESOLVED, InvestigationStatus.DISMISSED)),
            key=lambda r: r.created_at,
        )
        to_remove = len(self._investigations) - self._max
        for r in resolved[:to_remove]:
            del self._investigations[r.id]
            if r.license_id in self._by_license:
                ids = self._by_license[r.license_id]
                if r.id in ids:
                    ids.remove(r.id)
