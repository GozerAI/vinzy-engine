"""Automated license compliance revenue recovery.

Detects compliance violations (overuse, expired-but-active usage,
unauthorized feature access) and generates recovery actions to reclaim
lost revenue or enforce license terms.
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class ViolationType(str, Enum):
    MACHINE_OVERUSE = "machine_overuse"
    EXPIRED_USAGE = "expired_usage"
    FEATURE_UNAUTHORIZED = "feature_unauthorized"
    TIER_MISMATCH = "tier_mismatch"
    USAGE_LIMIT_EXCEEDED = "usage_limit_exceeded"


class RecoveryAction(str, Enum):
    NOTIFY = "notify"               # send notification to customer
    UPGRADE_PROMPT = "upgrade_prompt"  # prompt customer to upgrade
    THROTTLE = "throttle"           # reduce service level
    SUSPEND = "suspend"             # suspend license
    INVOICE = "invoice"             # generate invoice for overuse


class RecoveryStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    WAIVED = "waived"


@dataclass
class ComplianceViolation:
    """A detected compliance violation."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    license_id: str = ""
    customer_id: str = ""
    violation_type: ViolationType = ViolationType.MACHINE_OVERUSE
    severity: str = "medium"
    details: dict[str, Any] = field(default_factory=dict)
    detected_at: float = field(default_factory=time.monotonic)
    estimated_revenue_loss_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "license_id": self.license_id,
            "customer_id": self.customer_id,
            "violation_type": self.violation_type.value,
            "severity": self.severity,
            "details": self.details,
            "detected_at": self.detected_at,
            "estimated_revenue_loss_usd": round(self.estimated_revenue_loss_usd, 2),
        }


@dataclass
class RecoveryTask:
    """A recovery action to address a compliance violation."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    violation_id: str = ""
    license_id: str = ""
    customer_id: str = ""
    action: RecoveryAction = RecoveryAction.NOTIFY
    status: RecoveryStatus = RecoveryStatus.PENDING
    recoverable_amount_usd: float = 0.0
    recovered_amount_usd: float = 0.0
    notes: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.monotonic)
    completed_at: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "violation_id": self.violation_id,
            "license_id": self.license_id,
            "customer_id": self.customer_id,
            "action": self.action.value,
            "status": self.status.value,
            "recoverable_amount_usd": round(self.recoverable_amount_usd, 2),
            "recovered_amount_usd": round(self.recovered_amount_usd, 2),
            "notes": self.notes,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }


class ComplianceRecoveryEngine:
    """Automated compliance violation detection and revenue recovery.

    Scans license data for violations and generates recovery tasks.

    Usage:
        engine = ComplianceRecoveryEngine()

        # Scan a license for violations
        violations = engine.scan_license(license_data)

        # Generate recovery tasks
        tasks = engine.generate_recovery_tasks(violations)

        # Complete a task
        engine.complete_task(task.id, recovered_amount=50.00)
    """

    def __init__(
        self,
        machine_overuse_rate_per_machine_usd: float = 10.0,
        expired_usage_daily_rate_usd: float = 5.0,
        feature_unauthorized_rate_usd: float = 25.0,
        max_violations: int = 50_000,
        max_tasks: int = 50_000,
    ) -> None:
        self._machine_rate = machine_overuse_rate_per_machine_usd
        self._expired_rate = expired_usage_daily_rate_usd
        self._feature_rate = feature_unauthorized_rate_usd
        self._max_violations = max_violations
        self._max_tasks = max_tasks

        self._violations: dict[str, ComplianceViolation] = {}
        self._tasks: dict[str, RecoveryTask] = {}
        self._by_license: dict[str, list[str]] = defaultdict(list)

    def scan_license(self, license_data: dict[str, Any]) -> list[ComplianceViolation]:
        """Scan a license for compliance violations.

        license_data keys:
          - license_id, customer_id, status, tier
          - machines_limit, machines_used
          - expires_at (epoch float), is_expired (bool)
          - features_entitled (list[str]), features_used (list[str])
          - usage_records (list of {metric, value, limit})
        """
        violations: list[ComplianceViolation] = []
        lic_id = license_data.get("license_id", "")
        cust_id = license_data.get("customer_id", "")

        # Machine overuse
        limit = license_data.get("machines_limit", 0)
        used = license_data.get("machines_used", 0)
        if limit > 0 and used > limit:
            excess = used - limit
            violation = ComplianceViolation(
                license_id=lic_id,
                customer_id=cust_id,
                violation_type=ViolationType.MACHINE_OVERUSE,
                severity="high" if excess > limit else "medium",
                details={"machines_limit": limit, "machines_used": used, "excess": excess},
                estimated_revenue_loss_usd=excess * self._machine_rate,
            )
            violations.append(violation)

        # Expired usage
        if license_data.get("is_expired") and license_data.get("status") == "active":
            days_overdue = license_data.get("days_overdue", 1)
            violation = ComplianceViolation(
                license_id=lic_id,
                customer_id=cust_id,
                violation_type=ViolationType.EXPIRED_USAGE,
                severity="high",
                details={"days_overdue": days_overdue},
                estimated_revenue_loss_usd=days_overdue * self._expired_rate,
            )
            violations.append(violation)

        # Unauthorized features
        entitled = set(license_data.get("features_entitled", []))
        used_features = set(license_data.get("features_used", []))
        unauthorized = used_features - entitled
        if unauthorized:
            violation = ComplianceViolation(
                license_id=lic_id,
                customer_id=cust_id,
                violation_type=ViolationType.FEATURE_UNAUTHORIZED,
                severity="high" if len(unauthorized) > 3 else "medium",
                details={
                    "unauthorized_features": sorted(unauthorized),
                    "entitled_features": sorted(entitled),
                },
                estimated_revenue_loss_usd=len(unauthorized) * self._feature_rate,
            )
            violations.append(violation)

        # Usage limit exceeded
        for record in license_data.get("usage_records", []):
            rlimit = record.get("limit")
            rvalue = record.get("value", 0)
            if rlimit is not None and rvalue > rlimit:
                violation = ComplianceViolation(
                    license_id=lic_id,
                    customer_id=cust_id,
                    violation_type=ViolationType.USAGE_LIMIT_EXCEEDED,
                    severity="medium",
                    details={
                        "metric": record.get("metric", ""),
                        "value": rvalue,
                        "limit": rlimit,
                        "excess": rvalue - rlimit,
                    },
                )
                violations.append(violation)

        # Store violations
        for v in violations:
            self._violations[v.id] = v
            self._by_license[lic_id].append(v.id)

        self._enforce_violation_limit()
        return violations

    def generate_recovery_tasks(
        self, violations: list[ComplianceViolation],
    ) -> list[RecoveryTask]:
        """Generate recovery tasks for a list of violations.

        Selects the appropriate action based on violation type and severity.
        """
        tasks: list[RecoveryTask] = []

        for v in violations:
            action = self._select_action(v)
            task = RecoveryTask(
                violation_id=v.id,
                license_id=v.license_id,
                customer_id=v.customer_id,
                action=action,
                recoverable_amount_usd=v.estimated_revenue_loss_usd,
            )
            self._tasks[task.id] = task
            tasks.append(task)

        self._enforce_task_limit()
        return tasks

    def complete_task(
        self,
        task_id: str,
        recovered_amount: float = 0.0,
        note: str = "",
    ) -> bool:
        """Mark a recovery task as completed."""
        task = self._tasks.get(task_id)
        if task is None:
            return False
        task.status = RecoveryStatus.COMPLETED
        task.recovered_amount_usd = recovered_amount
        task.completed_at = time.monotonic()
        if note:
            task.notes.append(note)
        return True

    def waive_task(self, task_id: str, reason: str = "") -> bool:
        """Waive a recovery task (forgive the violation)."""
        task = self._tasks.get(task_id)
        if task is None:
            return False
        task.status = RecoveryStatus.WAIVED
        task.completed_at = time.monotonic()
        if reason:
            task.notes.append(f"Waived: {reason}")
        return True

    def get_violations_for_license(self, license_id: str) -> list[ComplianceViolation]:
        ids = self._by_license.get(license_id, [])
        return [self._violations[i] for i in ids if i in self._violations]

    def get_task(self, task_id: str) -> Optional[RecoveryTask]:
        return self._tasks.get(task_id)

    def get_pending_tasks(self, limit: int = 100) -> list[RecoveryTask]:
        pending = [t for t in self._tasks.values() if t.status == RecoveryStatus.PENDING]
        pending.sort(key=lambda t: t.recoverable_amount_usd, reverse=True)
        return pending[:limit]

    @property
    def stats(self) -> dict[str, Any]:
        total_recoverable = sum(t.recoverable_amount_usd for t in self._tasks.values())
        total_recovered = sum(
            t.recovered_amount_usd for t in self._tasks.values()
            if t.status == RecoveryStatus.COMPLETED
        )
        return {
            "total_violations": len(self._violations),
            "total_tasks": len(self._tasks),
            "pending_tasks": sum(1 for t in self._tasks.values() if t.status == RecoveryStatus.PENDING),
            "completed_tasks": sum(1 for t in self._tasks.values() if t.status == RecoveryStatus.COMPLETED),
            "total_recoverable_usd": round(total_recoverable, 2),
            "total_recovered_usd": round(total_recovered, 2),
            "recovery_rate": round(total_recovered / total_recoverable, 4) if total_recoverable > 0 else 0.0,
        }

    def clear(self) -> None:
        self._violations.clear()
        self._tasks.clear()
        self._by_license.clear()

    # -- Internal --

    def _select_action(self, violation: ComplianceViolation) -> RecoveryAction:
        """Select recovery action based on violation type and severity."""
        severity_actions = {
            ("machine_overuse", "medium"): RecoveryAction.UPGRADE_PROMPT,
            ("machine_overuse", "high"): RecoveryAction.THROTTLE,
            ("expired_usage", "high"): RecoveryAction.SUSPEND,
            ("feature_unauthorized", "medium"): RecoveryAction.NOTIFY,
            ("feature_unauthorized", "high"): RecoveryAction.THROTTLE,
            ("usage_limit_exceeded", "medium"): RecoveryAction.UPGRADE_PROMPT,
        }
        key = (violation.violation_type.value, violation.severity)
        return severity_actions.get(key, RecoveryAction.NOTIFY)

    def _enforce_violation_limit(self) -> None:
        if len(self._violations) <= self._max_violations:
            return
        oldest = sorted(self._violations.values(), key=lambda v: v.detected_at)
        to_remove = len(self._violations) - self._max_violations
        for v in oldest[:to_remove]:
            del self._violations[v.id]

    def _enforce_task_limit(self) -> None:
        if len(self._tasks) <= self._max_tasks:
            return
        completed = sorted(
            (t for t in self._tasks.values()
             if t.status in (RecoveryStatus.COMPLETED, RecoveryStatus.WAIVED)),
            key=lambda t: t.created_at,
        )
        to_remove = len(self._tasks) - self._max_tasks
        for t in completed[:to_remove]:
            del self._tasks[t.id]
