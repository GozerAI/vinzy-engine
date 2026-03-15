"""Revenue recognition automation.

Item 443: Automate revenue recognition per ASC 606 / IFRS 15 guidelines.
Track deferred revenue, recognize over service period.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any


class RecognitionMethod(str, Enum):
    STRAIGHT_LINE = "straight_line"      # Even over period
    USAGE_BASED = "usage_based"          # Based on actual usage
    MILESTONE = "milestone"              # At specific milestones
    POINT_IN_TIME = "point_in_time"      # All at once


class RevenueStatus(str, Enum):
    DEFERRED = "deferred"
    PARTIALLY_RECOGNIZED = "partially_recognized"
    FULLY_RECOGNIZED = "fully_recognized"
    REFUNDED = "refunded"


@dataclass
class RevenueSchedule:
    """Revenue recognition schedule for a contract."""
    schedule_id: str
    license_id: str
    contract_amount: float
    recognized_amount: float = 0.0
    deferred_amount: float = 0.0
    method: RecognitionMethod = RecognitionMethod.STRAIGHT_LINE
    period_start: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    period_end: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: RevenueStatus = RevenueStatus.DEFERRED
    entries: list[RecognitionEntry] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def remaining(self) -> float:
        return round(self.contract_amount - self.recognized_amount, 2)

    @property
    def recognition_pct(self) -> float:
        if self.contract_amount == 0:
            return 100.0
        return round((self.recognized_amount / self.contract_amount) * 100, 2)


@dataclass
class RecognitionEntry:
    """A single revenue recognition journal entry."""
    entry_id: str
    schedule_id: str
    amount: float
    period: str  # YYYY-MM
    recognized_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    description: str = ""


class RevenueRecognitionEngine:
    """Automate revenue recognition per ASC 606 guidelines."""

    def __init__(self):
        self._schedules: dict[str, RevenueSchedule] = {}
        self._sched_counter = 0
        self._entry_counter = 0

    def _next_sched_id(self) -> str:
        self._sched_counter += 1
        return f"REV-{self._sched_counter:06d}"

    def _next_entry_id(self) -> str:
        self._entry_counter += 1
        return f"REC-{self._entry_counter:08d}"

    def create_schedule(
        self,
        license_id: str,
        contract_amount: float,
        period_start: datetime,
        period_end: datetime,
        method: RecognitionMethod = RecognitionMethod.STRAIGHT_LINE,
        metadata: dict[str, Any] | None = None,
    ) -> RevenueSchedule:
        """Create a revenue recognition schedule."""
        schedule = RevenueSchedule(
            schedule_id=self._next_sched_id(),
            license_id=license_id,
            contract_amount=contract_amount,
            deferred_amount=contract_amount,
            method=method,
            period_start=period_start,
            period_end=period_end,
            metadata=metadata or {},
        )
        self._schedules[schedule.schedule_id] = schedule
        return schedule

    def generate_entries(self, schedule_id: str) -> list[RecognitionEntry]:
        """Generate all recognition entries for a schedule."""
        schedule = self._schedules.get(schedule_id)
        if schedule is None:
            raise ValueError(f"Unknown schedule: {schedule_id}")

        if schedule.method == RecognitionMethod.STRAIGHT_LINE:
            return self._generate_straight_line(schedule)
        elif schedule.method == RecognitionMethod.POINT_IN_TIME:
            return self._generate_point_in_time(schedule)
        return []

    def _generate_straight_line(self, schedule: RevenueSchedule) -> list[RecognitionEntry]:
        """Generate straight-line recognition entries (monthly)."""
        start = schedule.period_start
        end = schedule.period_end
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)

        total_days = max(1, (end - start).days)
        entries = []
        current = start
        while current < end:
            month_end = min(
                (current.replace(day=28) + timedelta(days=4)).replace(day=1),
                end,
            )
            days_in_month = (month_end - current).days
            amount = round(schedule.contract_amount * days_in_month / total_days, 2)
            period = current.strftime("%Y-%m")

            entry = RecognitionEntry(
                entry_id=self._next_entry_id(),
                schedule_id=schedule.schedule_id,
                amount=amount,
                period=period,
                description=f"Straight-line recognition: {days_in_month}/{total_days} days",
            )
            entries.append(entry)
            current = month_end

        # Adjust rounding on last entry
        if entries:
            total_recognized = sum(e.amount for e in entries)
            diff = round(schedule.contract_amount - total_recognized, 2)
            if abs(diff) > 0:
                entries[-1].amount = round(entries[-1].amount + diff, 2)

        schedule.entries = entries
        return entries

    def _generate_point_in_time(self, schedule: RevenueSchedule) -> list[RecognitionEntry]:
        """Recognize all revenue at a single point."""
        entry = RecognitionEntry(
            entry_id=self._next_entry_id(),
            schedule_id=schedule.schedule_id,
            amount=schedule.contract_amount,
            period=schedule.period_start.strftime("%Y-%m"),
            description="Point-in-time recognition",
        )
        schedule.entries = [entry]
        return [entry]

    def recognize(self, schedule_id: str, amount: float, period: str) -> RecognitionEntry:
        """Manually recognize revenue for a period."""
        schedule = self._schedules.get(schedule_id)
        if schedule is None:
            raise ValueError(f"Unknown schedule: {schedule_id}")

        amount = min(amount, schedule.remaining)
        entry = RecognitionEntry(
            entry_id=self._next_entry_id(),
            schedule_id=schedule_id,
            amount=amount,
            period=period,
        )
        schedule.entries.append(entry)
        schedule.recognized_amount = round(schedule.recognized_amount + amount, 2)
        schedule.deferred_amount = round(schedule.contract_amount - schedule.recognized_amount, 2)

        if schedule.recognized_amount >= schedule.contract_amount:
            schedule.status = RevenueStatus.FULLY_RECOGNIZED
        elif schedule.recognized_amount > 0:
            schedule.status = RevenueStatus.PARTIALLY_RECOGNIZED

        return entry

    def get_schedule(self, schedule_id: str) -> RevenueSchedule | None:
        return self._schedules.get(schedule_id)

    def get_schedules(self, license_id: str | None = None) -> list[RevenueSchedule]:
        schedules = list(self._schedules.values())
        if license_id:
            schedules = [s for s in schedules if s.license_id == license_id]
        return schedules

    def get_deferred_revenue(self) -> float:
        """Total deferred revenue across all schedules."""
        return round(sum(s.deferred_amount for s in self._schedules.values()), 2)

    def get_recognized_revenue(self, period: str | None = None) -> float:
        """Total recognized revenue, optionally filtered by period."""
        total = 0.0
        for schedule in self._schedules.values():
            for entry in schedule.entries:
                if period is None or entry.period == period:
                    total += entry.amount
        return round(total, 2)
