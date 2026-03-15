"""Smart dunning management.

Item 453: Intelligent payment retry and dunning sequences.
Item 337: Payment failure recovery automation.
Item 348: Payment retry with smart timing.
Item 465: Failed payment recovery automation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any


class DunningStage(str, Enum):
    INITIAL_RETRY = "initial_retry"
    SECOND_RETRY = "second_retry"
    THIRD_RETRY = "third_retry"
    SOFT_REMINDER = "soft_reminder"
    HARD_REMINDER = "hard_reminder"
    FINAL_NOTICE = "final_notice"
    SUSPENSION = "suspension"
    CANCELLATION = "cancellation"


class PaymentFailureType(str, Enum):
    INSUFFICIENT_FUNDS = "insufficient_funds"
    CARD_DECLINED = "card_declined"
    CARD_EXPIRED = "card_expired"
    PROCESSING_ERROR = "processing_error"
    FRAUD_SUSPECTED = "fraud_suspected"
    NETWORK_ERROR = "network_error"
    UNKNOWN = "unknown"


@dataclass
class DunningConfig:
    """Configuration for dunning sequences."""
    max_retries: int = 4
    retry_intervals_hours: list[int] = field(
        default_factory=lambda: [4, 24, 72, 168]  # 4h, 1d, 3d, 7d
    )
    grace_period_days: int = 7
    soft_reminder_day: int = 3
    hard_reminder_day: int = 7
    final_notice_day: int = 14
    suspension_day: int = 21
    cancellation_day: int = 30
    # Smart timing: preferred retry times (hour of day UTC)
    preferred_retry_hours: list[int] = field(
        default_factory=lambda: [10, 14, 18]  # Business hours
    )
    # Failure type specific delays
    failure_delays: dict[str, int] = field(default_factory=lambda: {
        "insufficient_funds": 72,    # Wait 3 days
        "card_expired": 0,           # Don't retry, ask for update
        "processing_error": 4,       # Retry quickly
        "network_error": 1,          # Retry very quickly
    })


@dataclass
class DunningRecord:
    """A dunning sequence record for a failed payment."""
    dunning_id: str
    license_id: str
    tenant_id: str | None
    original_amount: float
    currency: str
    failure_type: PaymentFailureType
    stage: DunningStage = DunningStage.INITIAL_RETRY
    retry_count: int = 0
    next_retry_at: datetime | None = None
    last_retry_at: datetime | None = None
    resolved: bool = False
    resolved_at: datetime | None = None
    notifications_sent: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def days_since_failure(self) -> int:
        created = self.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - created).days


@dataclass
class DunningAction:
    """An action to take in the dunning sequence."""
    action_type: str  # retry, notify, suspend, cancel
    dunning_id: str
    description: str
    scheduled_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


class SmartDunningEngine:
    """Intelligent payment failure recovery with smart retry timing."""

    def __init__(self, config: DunningConfig | None = None):
        self._config = config or DunningConfig()
        self._records: dict[str, DunningRecord] = {}
        self._actions: list[DunningAction] = []
        self._counter = 0

    def _next_id(self) -> str:
        self._counter += 1
        return f"DUN-{self._counter:06d}"

    def _smart_retry_time(self, base_time: datetime, hours_delay: int) -> datetime:
        """Calculate smart retry time, aligning to preferred hours."""
        candidate = base_time + timedelta(hours=hours_delay)
        preferred = self._config.preferred_retry_hours
        if not preferred:
            return candidate
        # Find nearest preferred hour
        best_hour = min(preferred, key=lambda h: abs(candidate.hour - h))
        return candidate.replace(hour=best_hour, minute=0, second=0, microsecond=0)

    def record_failure(
        self,
        license_id: str,
        tenant_id: str | None,
        amount: float,
        currency: str,
        failure_type: PaymentFailureType,
        metadata: dict[str, Any] | None = None,
    ) -> DunningRecord:
        """Record a payment failure and initiate dunning."""
        now = datetime.now(timezone.utc)
        delay = self._config.failure_delays.get(failure_type.value, 24)

        # Don't retry card expired - just notify
        if failure_type == PaymentFailureType.CARD_EXPIRED:
            next_retry = None
            stage = DunningStage.SOFT_REMINDER
        else:
            next_retry = self._smart_retry_time(now, delay)
            stage = DunningStage.INITIAL_RETRY

        record = DunningRecord(
            dunning_id=self._next_id(),
            license_id=license_id,
            tenant_id=tenant_id,
            original_amount=amount,
            currency=currency,
            failure_type=failure_type,
            stage=stage,
            next_retry_at=next_retry,
            metadata=metadata or {},
        )
        self._records[record.dunning_id] = record
        return record

    def process_retry(self, dunning_id: str, success: bool) -> DunningRecord:
        """Process the result of a payment retry."""
        record = self._records.get(dunning_id)
        if record is None:
            raise ValueError(f"Dunning record not found: {dunning_id}")

        record.retry_count += 1
        record.last_retry_at = datetime.now(timezone.utc)

        if success:
            record.resolved = True
            record.resolved_at = datetime.now(timezone.utc)
            return record

        # Advance to next stage
        if record.retry_count >= self._config.max_retries:
            record.stage = DunningStage.FINAL_NOTICE
            record.next_retry_at = None
        else:
            idx = min(record.retry_count, len(self._config.retry_intervals_hours) - 1)
            delay = self._config.retry_intervals_hours[idx]
            record.next_retry_at = self._smart_retry_time(
                datetime.now(timezone.utc), delay
            )
            stages = list(DunningStage)
            current_idx = stages.index(record.stage)
            if current_idx + 1 < len(stages):
                record.stage = stages[current_idx + 1]

        return record

    def get_pending_retries(self) -> list[DunningRecord]:
        """Get records that need retry now."""
        now = datetime.now(timezone.utc)
        return [
            r for r in self._records.values()
            if not r.resolved
            and r.next_retry_at is not None
            and r.next_retry_at <= now
        ]

    def get_actions_due(self) -> list[DunningAction]:
        """Generate actions for all active dunning records."""
        actions = []
        now = datetime.now(timezone.utc)

        for record in self._records.values():
            if record.resolved:
                continue

            days = record.days_since_failure

            if days >= self._config.cancellation_day:
                actions.append(DunningAction(
                    action_type="cancel",
                    dunning_id=record.dunning_id,
                    description=f"Cancel subscription after {days} days of failed payment",
                    scheduled_at=now,
                ))
            elif days >= self._config.suspension_day:
                actions.append(DunningAction(
                    action_type="suspend",
                    dunning_id=record.dunning_id,
                    description=f"Suspend license after {days} days",
                    scheduled_at=now,
                ))
            elif days >= self._config.final_notice_day and "final_notice" not in record.notifications_sent:
                actions.append(DunningAction(
                    action_type="notify",
                    dunning_id=record.dunning_id,
                    description="Final notice: payment required to avoid cancellation",
                    scheduled_at=now,
                    metadata={"notification_type": "final_notice"},
                ))
            elif record.next_retry_at and record.next_retry_at <= now:
                actions.append(DunningAction(
                    action_type="retry",
                    dunning_id=record.dunning_id,
                    description=f"Retry payment (attempt #{record.retry_count + 1})",
                    scheduled_at=now,
                ))

        return actions

    def resolve(self, dunning_id: str) -> DunningRecord:
        """Mark dunning as resolved (payment collected or forgiven)."""
        record = self._records.get(dunning_id)
        if record is None:
            raise ValueError(f"Dunning record not found: {dunning_id}")
        record.resolved = True
        record.resolved_at = datetime.now(timezone.utc)
        return record

    def get_record(self, dunning_id: str) -> DunningRecord | None:
        return self._records.get(dunning_id)

    def get_records(
        self, license_id: str | None = None, resolved: bool | None = None
    ) -> list[DunningRecord]:
        results = list(self._records.values())
        if license_id:
            results = [r for r in results if r.license_id == license_id]
        if resolved is not None:
            results = [r for r in results if r.resolved == resolved]
        return results

    def get_recovery_stats(self) -> dict[str, Any]:
        """Get dunning recovery statistics."""
        total = len(self._records)
        resolved = sum(1 for r in self._records.values() if r.resolved)
        pending = total - resolved
        total_amount = sum(r.original_amount for r in self._records.values())
        recovered = sum(r.original_amount for r in self._records.values() if r.resolved)
        return {
            "total_records": total,
            "resolved": resolved,
            "pending": pending,
            "recovery_rate": round(resolved / total * 100, 2) if total else 0,
            "total_at_risk": round(total_amount, 2),
            "recovered_amount": round(recovered, 2),
        }
