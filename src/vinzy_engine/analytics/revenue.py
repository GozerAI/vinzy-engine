"""Revenue analytics, forecasting, and subscription metrics.

Item 456: Revenue analytics dashboard.
Item 462: Subscription lifecycle analytics.
Item 488: Revenue forecasting dashboard.
Item 494: Customer acquisition cost tracking.
Item 499: Subscription metrics dashboard (MRR, ARR, churn).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any


@dataclass
class RevenueEntry:
    """A single revenue entry."""
    license_id: str
    amount: float
    currency: str = "USD"
    type: str = "subscription"  # subscription, usage, overage, one_time
    period: str = ""  # YYYY-MM
    recorded_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MRRMetrics:
    """Monthly Recurring Revenue breakdown."""
    total_mrr: float
    new_mrr: float          # From new customers
    expansion_mrr: float    # From upgrades
    contraction_mrr: float  # From downgrades (negative)
    churned_mrr: float      # From cancellations (negative)
    net_new_mrr: float      # new + expansion + contraction + churned
    arr: float              # Annual run rate (MRR * 12)
    period: str


@dataclass
class SubscriptionMetrics:
    """Comprehensive subscription metrics."""
    total_subscriptions: int
    active_subscriptions: int
    new_subscriptions: int
    churned_subscriptions: int
    paused_subscriptions: int
    gross_churn_rate: float
    net_churn_rate: float
    avg_revenue_per_account: float
    customer_lifetime_value: float
    mrr: MRRMetrics
    period: str
    period_start: datetime
    period_end: datetime


@dataclass
class RevenueForcast:
    """Revenue forecast for a future period."""
    period: str
    predicted_mrr: float
    predicted_arr: float
    confidence_low: float
    confidence_high: float
    growth_rate: float
    assumptions: list[str]
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class CACMetrics:
    """Customer Acquisition Cost metrics."""
    period: str
    total_marketing_spend: float
    total_sales_spend: float
    total_spend: float
    new_customers: int
    cac: float  # Cost per acquisition
    ltv_to_cac_ratio: float
    payback_months: float
    by_channel: dict[str, float]  # channel -> CAC


@dataclass
class LifecycleStage:
    """Subscription lifecycle stage."""
    name: str
    count: int
    avg_duration_days: float
    transition_rate: float  # % that move to next stage


class RevenueAnalyticsEngine:
    """Revenue analytics, forecasting, and subscription metrics."""

    def __init__(self):
        self._entries: list[RevenueEntry] = []
        self._subscriptions: list[dict[str, Any]] = []
        self._marketing_spend: list[dict[str, Any]] = []

    def record_revenue(
        self,
        license_id: str,
        amount: float,
        type: str = "subscription",
        period: str = "",
        currency: str = "USD",
        metadata: dict[str, Any] | None = None,
    ) -> RevenueEntry:
        if not period:
            period = datetime.now(timezone.utc).strftime("%Y-%m")
        entry = RevenueEntry(
            license_id=license_id,
            amount=amount,
            currency=currency,
            type=type,
            period=period,
            metadata=metadata or {},
        )
        self._entries.append(entry)
        return entry

    def record_subscription_event(
        self,
        license_id: str,
        event: str,  # new, upgrade, downgrade, cancel, pause, resume
        mrr_change: float,
        period: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not period:
            period = datetime.now(timezone.utc).strftime("%Y-%m")
        self._subscriptions.append({
            "license_id": license_id,
            "event": event,
            "mrr_change": mrr_change,
            "period": period,
            "timestamp": datetime.now(timezone.utc),
            "metadata": metadata or {},
        })

    def record_marketing_spend(
        self, channel: str, amount: float, period: str, new_customers: int = 0
    ) -> None:
        self._marketing_spend.append({
            "channel": channel,
            "amount": amount,
            "period": period,
            "new_customers": new_customers,
        })

    def calculate_mrr(self, period: str) -> MRRMetrics:
        """Calculate MRR breakdown for a period."""
        events = [s for s in self._subscriptions if s["period"] == period]

        new_mrr = sum(s["mrr_change"] for s in events if s["event"] == "new")
        expansion = sum(s["mrr_change"] for s in events if s["event"] == "upgrade")
        contraction = sum(s["mrr_change"] for s in events if s["event"] == "downgrade")
        churned = sum(s["mrr_change"] for s in events if s["event"] == "cancel")

        # Total MRR = sum of all active subscription revenue
        revenue_entries = [e for e in self._entries if e.period == period and e.type == "subscription"]
        total = sum(e.amount for e in revenue_entries)

        net_new = new_mrr + expansion + contraction + churned

        return MRRMetrics(
            total_mrr=round(total, 2),
            new_mrr=round(new_mrr, 2),
            expansion_mrr=round(expansion, 2),
            contraction_mrr=round(contraction, 2),
            churned_mrr=round(churned, 2),
            net_new_mrr=round(net_new, 2),
            arr=round(total * 12, 2),
            period=period,
        )

    def calculate_subscription_metrics(
        self,
        period: str,
        period_start: datetime,
        period_end: datetime,
        active_count: int,
        total_count: int,
    ) -> SubscriptionMetrics:
        """Calculate comprehensive subscription metrics."""
        events = [s for s in self._subscriptions if s["period"] == period]

        new_subs = sum(1 for s in events if s["event"] == "new")
        churned = sum(1 for s in events if s["event"] == "cancel")
        paused = sum(1 for s in events if s["event"] == "pause")

        gross_churn = round(churned / active_count * 100, 2) if active_count else 0

        # Net churn (accounting for expansion)
        expansion_count = sum(1 for s in events if s["event"] == "upgrade")
        net_churned = churned - expansion_count
        net_churn = round(max(0, net_churned) / active_count * 100, 2) if active_count else 0

        mrr = self.calculate_mrr(period)
        arpa = round(mrr.total_mrr / active_count, 2) if active_count else 0

        # Simple LTV = ARPA / churn_rate
        churn_decimal = gross_churn / 100 if gross_churn > 0 else 0.01
        ltv = round(arpa / churn_decimal, 2)

        return SubscriptionMetrics(
            total_subscriptions=total_count,
            active_subscriptions=active_count,
            new_subscriptions=new_subs,
            churned_subscriptions=churned,
            paused_subscriptions=paused,
            gross_churn_rate=gross_churn,
            net_churn_rate=net_churn,
            avg_revenue_per_account=arpa,
            customer_lifetime_value=ltv,
            mrr=mrr,
            period=period,
            period_start=period_start,
            period_end=period_end,
        )

    def forecast_revenue(
        self, months_ahead: int = 6, growth_assumption: float = 0.05
    ) -> list[RevenueForcast]:
        """Generate revenue forecasts."""
        # Get most recent period's MRR
        periods = sorted(set(e.period for e in self._entries))
        if not periods:
            return []

        latest_period = periods[-1]
        mrr = self.calculate_mrr(latest_period)
        current_mrr = mrr.total_mrr

        forecasts = []
        year, month = map(int, latest_period.split("-"))

        for i in range(1, months_ahead + 1):
            m = month + i
            y = year + (m - 1) // 12
            m = ((m - 1) % 12) + 1
            period = f"{y:04d}-{m:02d}"

            predicted = current_mrr * ((1 + growth_assumption) ** i)
            low = predicted * 0.85
            high = predicted * 1.15

            forecasts.append(RevenueForcast(
                period=period,
                predicted_mrr=round(predicted, 2),
                predicted_arr=round(predicted * 12, 2),
                confidence_low=round(low, 2),
                confidence_high=round(high, 2),
                growth_rate=growth_assumption,
                assumptions=[
                    f"Assumed {growth_assumption*100:.1f}% monthly growth",
                    "Based on most recent MRR trend",
                ],
            ))

        return forecasts

    def calculate_cac(self, period: str, avg_ltv: float = 0) -> CACMetrics:
        """Calculate Customer Acquisition Cost for a period."""
        spend_entries = [s for s in self._marketing_spend if s["period"] == period]

        total_marketing = sum(s["amount"] for s in spend_entries)
        new_customers = sum(s["new_customers"] for s in spend_entries)
        cac = round(total_marketing / new_customers, 2) if new_customers else 0

        # By channel
        from collections import defaultdict
        channel_spend: dict[str, float] = defaultdict(float)
        channel_customers: dict[str, int] = defaultdict(int)
        for s in spend_entries:
            channel_spend[s["channel"]] += s["amount"]
            channel_customers[s["channel"]] += s["new_customers"]

        by_channel = {
            ch: round(channel_spend[ch] / channel_customers[ch], 2)
            if channel_customers[ch] else 0
            for ch in channel_spend
        }

        ltv_ratio = round(avg_ltv / cac, 2) if cac > 0 and avg_ltv > 0 else 0
        payback = round(cac / (avg_ltv / 12), 1) if avg_ltv > 0 else 0

        return CACMetrics(
            period=period,
            total_marketing_spend=round(total_marketing, 2),
            total_sales_spend=0,
            total_spend=round(total_marketing, 2),
            new_customers=new_customers,
            cac=cac,
            ltv_to_cac_ratio=ltv_ratio,
            payback_months=payback,
            by_channel=by_channel,
        )

    def get_revenue_by_period(
        self, start_period: str | None = None, end_period: str | None = None
    ) -> dict[str, float]:
        """Get total revenue grouped by period."""
        entries = self._entries
        if start_period:
            entries = [e for e in entries if e.period >= start_period]
        if end_period:
            entries = [e for e in entries if e.period <= end_period]

        result: dict[str, float] = {}
        for e in entries:
            result[e.period] = result.get(e.period, 0) + e.amount
        return {k: round(v, 2) for k, v in sorted(result.items())}

    def get_revenue_by_type(self, period: str | None = None) -> dict[str, float]:
        """Get revenue breakdown by type."""
        entries = self._entries
        if period:
            entries = [e for e in entries if e.period == period]
        result: dict[str, float] = {}
        for e in entries:
            result[e.type] = result.get(e.type, 0) + e.amount
        return {k: round(v, 2) for k, v in result.items()}
