"""Chargeback prevention system.

Item 459: Detect, prevent, and manage chargebacks proactively.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class ChargebackRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ChargebackStatus(str, Enum):
    ALERT = "alert"           # Early warning
    OPENED = "opened"         # Chargeback filed
    EVIDENCE_SUBMITTED = "evidence_submitted"
    WON = "won"
    LOST = "lost"
    REFUNDED = "refunded"     # Pre-emptive refund


@dataclass
class ChargebackCase:
    """A chargeback case."""
    case_id: str
    license_id: str
    charge_id: str
    amount: float
    currency: str
    reason_code: str
    risk_level: ChargebackRisk
    status: ChargebackStatus = ChargebackStatus.ALERT
    evidence: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RiskSignal:
    """A signal indicating chargeback risk."""
    signal_type: str
    score: float  # 0.0-1.0
    description: str
    metadata: dict[str, Any] = field(default_factory=dict)


class ChargebackPreventionEngine:
    """Proactively detect and prevent chargebacks."""

    def __init__(self):
        self._cases: dict[str, ChargebackCase] = {}
        self._counter = 0
        # Risk thresholds
        self._thresholds = {
            ChargebackRisk.LOW: 0.25,
            ChargebackRisk.MEDIUM: 0.50,
            ChargebackRisk.HIGH: 0.75,
            ChargebackRisk.CRITICAL: 0.90,
        }

    def _next_id(self) -> str:
        self._counter += 1
        return f"CB-{self._counter:06d}"

    def assess_risk(
        self,
        license_id: str,
        charge_amount: float,
        signals: list[RiskSignal] | None = None,
        history: dict[str, Any] | None = None,
    ) -> tuple[ChargebackRisk, float]:
        """Assess chargeback risk for a transaction."""
        risk_score = 0.0
        signal_list = signals or []
        hist = history or {}

        # Base signals
        if signal_list:
            risk_score = max(s.score for s in signal_list)

        # Historical factors
        if hist.get("previous_chargebacks", 0) > 0:
            risk_score = max(risk_score, 0.6)
        if hist.get("previous_chargebacks", 0) > 2:
            risk_score = max(risk_score, 0.85)

        # Amount-based risk
        if charge_amount > 500:
            risk_score = max(risk_score, risk_score + 0.1)
        if charge_amount > 2000:
            risk_score = max(risk_score, risk_score + 0.15)

        # New customer risk
        if hist.get("tenure_days", 365) < 30:
            risk_score = max(risk_score, risk_score + 0.1)

        risk_score = min(1.0, risk_score)

        # Determine level
        level = ChargebackRisk.LOW
        for risk_level, threshold in sorted(self._thresholds.items(), key=lambda x: x[1]):
            if risk_score >= threshold:
                level = risk_level

        return level, round(risk_score, 3)

    def create_case(
        self,
        license_id: str,
        charge_id: str,
        amount: float,
        currency: str,
        reason_code: str,
        risk_level: ChargebackRisk | None = None,
    ) -> ChargebackCase:
        """Create a chargeback case."""
        if risk_level is None:
            risk_level, _ = self.assess_risk(license_id, amount)

        case = ChargebackCase(
            case_id=self._next_id(),
            license_id=license_id,
            charge_id=charge_id,
            amount=amount,
            currency=currency,
            reason_code=reason_code,
            risk_level=risk_level,
        )
        self._cases[case.case_id] = case
        return case

    def submit_evidence(self, case_id: str, evidence: dict[str, Any]) -> ChargebackCase:
        case = self._cases.get(case_id)
        if case is None:
            raise ValueError(f"Case not found: {case_id}")
        case.evidence.update(evidence)
        case.status = ChargebackStatus.EVIDENCE_SUBMITTED
        return case

    def resolve(self, case_id: str, won: bool) -> ChargebackCase:
        case = self._cases.get(case_id)
        if case is None:
            raise ValueError(f"Case not found: {case_id}")
        case.status = ChargebackStatus.WON if won else ChargebackStatus.LOST
        case.resolved_at = datetime.now(timezone.utc)
        return case

    def preemptive_refund(self, case_id: str) -> ChargebackCase:
        """Issue a pre-emptive refund to prevent chargeback."""
        case = self._cases.get(case_id)
        if case is None:
            raise ValueError(f"Case not found: {case_id}")
        case.status = ChargebackStatus.REFUNDED
        case.resolved_at = datetime.now(timezone.utc)
        return case

    def get_case(self, case_id: str) -> ChargebackCase | None:
        return self._cases.get(case_id)

    def get_cases(
        self, license_id: str | None = None, status: ChargebackStatus | None = None
    ) -> list[ChargebackCase]:
        results = list(self._cases.values())
        if license_id:
            results = [c for c in results if c.license_id == license_id]
        if status:
            results = [c for c in results if c.status == status]
        return results

    def get_stats(self) -> dict[str, Any]:
        cases = list(self._cases.values())
        won = sum(1 for c in cases if c.status == ChargebackStatus.WON)
        lost = sum(1 for c in cases if c.status == ChargebackStatus.LOST)
        resolved = won + lost
        return {
            "total_cases": len(cases),
            "won": won,
            "lost": lost,
            "pending": len(cases) - resolved - sum(1 for c in cases if c.status == ChargebackStatus.REFUNDED),
            "refunded": sum(1 for c in cases if c.status == ChargebackStatus.REFUNDED),
            "win_rate": round(won / resolved * 100, 2) if resolved else 0,
            "total_amount_at_risk": round(sum(c.amount for c in cases if c.status not in (ChargebackStatus.WON, ChargebackStatus.REFUNDED)), 2),
        }
