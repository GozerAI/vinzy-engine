"""Overage billing for tier limit exceedance.

Item 254: Track when usage exceeds tier limits, calculate overage charges,
and generate overage invoices.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from vinzy_engine.licensing.tier_templates import OVERAGE_RATES, USAGE_LIMITS


class OveragePolicy(str, Enum):
    HARD_CAP = "hard_cap"        # Block usage at limit
    SOFT_CAP = "soft_cap"        # Allow overage, bill later
    BURST = "burst"              # Allow temporary burst, throttle after
    NOTIFY_ONLY = "notify_only"  # Allow all, just notify


@dataclass
class OverageEvent:
    """A single overage occurrence."""
    license_id: str
    metric: str
    tier: str
    limit: float
    actual: float
    overage_units: float
    unit_rate: float
    overage_charge: float
    policy: OveragePolicy
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class OverageInvoice:
    """Aggregated overage charges for a billing period."""
    license_id: str
    tenant_id: str | None
    period_start: datetime
    period_end: datetime
    events: list[OverageEvent]
    subtotal: float
    currency: str = "USD"
    status: str = "pending"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def event_count(self) -> int:
        return len(self.events)


class OverageBillingEngine:
    """Calculates and tracks overage charges when usage exceeds tier limits."""

    def __init__(
        self,
        custom_rates: dict[str, float] | None = None,
        default_policy: OveragePolicy = OveragePolicy.SOFT_CAP,
    ):
        self._rates = dict(OVERAGE_RATES)
        if custom_rates:
            self._rates.update(custom_rates)
        self._default_policy = default_policy
        self._events: list[OverageEvent] = []
        self._policy_overrides: dict[str, OveragePolicy] = {}

    def set_policy(self, metric: str, policy: OveragePolicy) -> None:
        self._policy_overrides[metric] = policy

    def get_policy(self, metric: str) -> OveragePolicy:
        return self._policy_overrides.get(metric, self._default_policy)

    def get_rate(self, tier: str, metric: str = "ai_credits") -> float:
        """Get the overage rate for a tier and metric."""
        key = f"{tier}_{metric}" if f"{tier}_{metric}" in self._rates else tier
        if metric in self._rates:
            return self._rates[metric]
        return self._rates.get(key, self._rates.get(tier, 0.0))

    def check_overage(
        self,
        license_id: str,
        tier: str,
        metric: str,
        current_usage: float,
        additional: float = 0,
    ) -> OverageEvent | None:
        """Check if usage exceeds tier limit and return overage event if so."""
        limits = USAGE_LIMITS.get(tier, {})
        limit = limits.get(metric)
        if limit is None or limit == 0:  # 0 means unlimited
            return None

        total = current_usage + additional
        if total <= limit:
            return None

        overage_units = total - limit
        rate = self.get_rate(tier, metric)
        charge = round(overage_units * rate, 2)
        policy = self.get_policy(metric)

        event = OverageEvent(
            license_id=license_id,
            metric=metric,
            tier=tier,
            limit=limit,
            actual=total,
            overage_units=overage_units,
            unit_rate=rate,
            overage_charge=charge,
            policy=policy,
        )
        self._events.append(event)
        return event

    def should_block(self, event: OverageEvent) -> bool:
        """Determine if usage should be blocked based on policy."""
        return event.policy == OveragePolicy.HARD_CAP

    def generate_invoice(
        self,
        license_id: str,
        tenant_id: str | None,
        period_start: datetime,
        period_end: datetime,
    ) -> OverageInvoice:
        """Generate an overage invoice for the billing period."""
        period_events = [
            e for e in self._events
            if e.license_id == license_id
            and period_start <= e.timestamp <= period_end
        ]
        subtotal = round(sum(e.overage_charge for e in period_events), 2)
        return OverageInvoice(
            license_id=license_id,
            tenant_id=tenant_id,
            period_start=period_start,
            period_end=period_end,
            events=period_events,
            subtotal=subtotal,
        )

    def get_events(self, license_id: str | None = None) -> list[OverageEvent]:
        if license_id:
            return [e for e in self._events if e.license_id == license_id]
        return list(self._events)

    def clear_events(self) -> None:
        self._events.clear()
