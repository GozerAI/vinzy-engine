"""Conversion funnel tracking and payment analytics.

Item 448: Payment analytics for conversion optimization.
Item 472: Conversion funnel tracking.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class FunnelStage:
    """A stage in a conversion funnel."""
    name: str
    order: int
    entered: int = 0
    completed: int = 0
    dropped: int = 0

    @property
    def completion_rate(self) -> float:
        return round(self.completed / self.entered * 100, 2) if self.entered else 0

    @property
    def drop_rate(self) -> float:
        return round(self.dropped / self.entered * 100, 2) if self.entered else 0


@dataclass
class FunnelEvent:
    """An event in the conversion funnel."""
    event_id: str
    funnel_id: str
    license_id: str
    stage: str
    action: str  # entered, completed, dropped
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class FunnelAnalysis:
    """Analysis of a conversion funnel."""
    funnel_id: str
    stages: list[FunnelStage]
    overall_conversion_rate: float
    biggest_drop_stage: str
    avg_time_to_convert_hours: float
    total_entered: int
    total_converted: int
    period_start: datetime
    period_end: datetime


@dataclass
class PaymentConversionMetrics:
    """Payment-specific conversion metrics."""
    total_attempts: int
    successful: int
    failed: int
    abandoned_checkout: int
    success_rate: float
    avg_checkout_time_seconds: float
    top_failure_reasons: list[tuple[str, int]]
    conversion_by_method: dict[str, float]  # payment method -> rate
    period_start: datetime
    period_end: datetime


# Default funnel stages
DEFAULT_FUNNEL_STAGES = [
    "visit", "signup", "trial_start", "feature_explore",
    "pricing_view", "checkout_start", "payment", "activation",
]


class ConversionFunnelTracker:
    """Track and analyze conversion funnels."""

    def __init__(self):
        self._funnels: dict[str, list[FunnelStage]] = {}
        self._events: list[FunnelEvent] = []
        self._event_counter = 0

    def _next_event_id(self) -> str:
        self._event_counter += 1
        return f"FEV-{self._event_counter:08d}"

    def create_funnel(self, funnel_id: str, stages: list[str] | None = None) -> list[FunnelStage]:
        stage_names = stages or DEFAULT_FUNNEL_STAGES
        funnel_stages = [FunnelStage(name=s, order=i) for i, s in enumerate(stage_names)]
        self._funnels[funnel_id] = funnel_stages
        return funnel_stages

    def record_event(
        self,
        funnel_id: str,
        license_id: str,
        stage: str,
        action: str = "completed",
        metadata: dict[str, Any] | None = None,
    ) -> FunnelEvent:
        if funnel_id not in self._funnels:
            raise ValueError(f"Unknown funnel: {funnel_id}")

        # Update stage counters
        for fs in self._funnels[funnel_id]:
            if fs.name == stage:
                if action == "entered":
                    fs.entered += 1
                elif action == "completed":
                    fs.completed += 1
                elif action == "dropped":
                    fs.dropped += 1
                break

        event = FunnelEvent(
            event_id=self._next_event_id(),
            funnel_id=funnel_id,
            license_id=license_id,
            stage=stage,
            action=action,
            metadata=metadata or {},
        )
        self._events.append(event)
        return event

    def analyze_funnel(
        self,
        funnel_id: str,
        period_start: datetime,
        period_end: datetime,
    ) -> FunnelAnalysis:
        """Analyze a funnel for a period."""
        stages = self._funnels.get(funnel_id, [])
        if not stages:
            raise ValueError(f"Unknown funnel: {funnel_id}")

        # Filter events by period
        events = [
            e for e in self._events
            if e.funnel_id == funnel_id
            and period_start <= e.timestamp <= period_end
        ]

        first_stage = stages[0] if stages else None
        last_stage = stages[-1] if stages else None
        total_entered = first_stage.entered if first_stage else 0
        total_converted = last_stage.completed if last_stage else 0

        overall_rate = round(total_converted / total_entered * 100, 2) if total_entered else 0

        # Find biggest drop
        biggest_drop = ""
        max_drop_rate = 0
        for s in stages:
            if s.entered > 0 and s.drop_rate > max_drop_rate:
                max_drop_rate = s.drop_rate
                biggest_drop = s.name

        # Avg conversion time
        license_first: dict[str, datetime] = {}
        license_last: dict[str, datetime] = {}
        for e in events:
            if e.action in ("entered", "completed"):
                if e.license_id not in license_first:
                    license_first[e.license_id] = e.timestamp
                license_last[e.license_id] = e.timestamp

        times = []
        for lid in license_first:
            if lid in license_last:
                delta = (license_last[lid] - license_first[lid]).total_seconds() / 3600
                if delta > 0:
                    times.append(delta)

        avg_time = sum(times) / len(times) if times else 0

        return FunnelAnalysis(
            funnel_id=funnel_id,
            stages=stages,
            overall_conversion_rate=overall_rate,
            biggest_drop_stage=biggest_drop,
            avg_time_to_convert_hours=round(avg_time, 2),
            total_entered=total_entered,
            total_converted=total_converted,
            period_start=period_start,
            period_end=period_end,
        )

    def get_events(
        self, funnel_id: str | None = None, license_id: str | None = None
    ) -> list[FunnelEvent]:
        results = self._events
        if funnel_id:
            results = [e for e in results if e.funnel_id == funnel_id]
        if license_id:
            results = [e for e in results if e.license_id == license_id]
        return results


class PaymentAnalyticsEngine:
    """Payment analytics for conversion optimization."""

    def __init__(self):
        self._attempts: list[dict[str, Any]] = []

    def record_attempt(
        self,
        license_id: str,
        amount: float,
        payment_method: str,
        success: bool,
        failure_reason: str = "",
        checkout_time_seconds: float = 0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._attempts.append({
            "license_id": license_id,
            "amount": amount,
            "payment_method": payment_method,
            "success": success,
            "failure_reason": failure_reason,
            "checkout_time_seconds": checkout_time_seconds,
            "timestamp": datetime.now(timezone.utc),
            "metadata": metadata or {},
        })

    def analyze(
        self, period_start: datetime, period_end: datetime
    ) -> PaymentConversionMetrics:
        attempts = [
            a for a in self._attempts
            if period_start <= a["timestamp"] <= period_end
        ]

        total = len(attempts)
        successful = sum(1 for a in attempts if a["success"])
        failed = sum(1 for a in attempts if not a["success"] and a["failure_reason"])
        abandoned = total - successful - failed

        # Failure reasons
        from collections import Counter
        reasons = Counter(a["failure_reason"] for a in attempts if a["failure_reason"])

        # By payment method
        method_stats: dict[str, dict[str, int]] = {}
        for a in attempts:
            m = a["payment_method"]
            if m not in method_stats:
                method_stats[m] = {"total": 0, "success": 0}
            method_stats[m]["total"] += 1
            if a["success"]:
                method_stats[m]["success"] += 1

        conversion_by_method = {
            m: round(s["success"] / s["total"] * 100, 2) if s["total"] else 0
            for m, s in method_stats.items()
        }

        checkout_times = [a["checkout_time_seconds"] for a in attempts if a["checkout_time_seconds"] > 0]
        avg_checkout = sum(checkout_times) / len(checkout_times) if checkout_times else 0

        return PaymentConversionMetrics(
            total_attempts=total,
            successful=successful,
            failed=failed,
            abandoned_checkout=abandoned,
            success_rate=round(successful / total * 100, 2) if total else 0,
            avg_checkout_time_seconds=round(avg_checkout, 2),
            top_failure_reasons=reasons.most_common(5),
            conversion_by_method=conversion_by_method,
            period_start=period_start,
            period_end=period_end,
        )
