"""Cohort analysis for retention.

Item 480: Cohort-based retention and behavior analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class CohortMember:
    """A member of a cohort."""
    license_id: str
    cohort_key: str  # e.g., "2026-01" (signup month)
    signup_date: datetime
    tier: str
    active_months: list[str] = field(default_factory=list)  # months with activity
    total_revenue: float = 0.0
    churned: bool = False
    churn_month: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CohortMetrics:
    """Metrics for a single cohort."""
    cohort_key: str
    size: int
    retention_by_month: dict[int, float]  # month offset -> retention %
    revenue_by_month: dict[int, float]    # month offset -> total revenue
    churn_rate: float
    avg_lifetime_months: float
    avg_revenue_per_user: float
    ltv_estimate: float  # estimated lifetime value


@dataclass
class RetentionMatrix:
    """Full retention matrix across cohorts."""
    cohorts: list[CohortMetrics]
    overall_retention_by_month: dict[int, float]
    best_cohort: str
    worst_cohort: str
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class CohortAnalysisEngine:
    """Cohort-based retention and behavior analysis."""

    def __init__(self):
        self._members: list[CohortMember] = []

    def add_member(
        self,
        license_id: str,
        signup_date: datetime,
        tier: str,
        metadata: dict[str, Any] | None = None,
    ) -> CohortMember:
        cohort_key = signup_date.strftime("%Y-%m")
        member = CohortMember(
            license_id=license_id,
            cohort_key=cohort_key,
            signup_date=signup_date,
            tier=tier,
            metadata=metadata or {},
        )
        self._members.append(member)
        return member

    def record_activity(self, license_id: str, month: str, revenue: float = 0) -> None:
        for m in self._members:
            if m.license_id == license_id:
                if month not in m.active_months:
                    m.active_months.append(month)
                m.total_revenue += revenue
                return

    def record_churn(self, license_id: str, churn_month: str) -> None:
        for m in self._members:
            if m.license_id == license_id:
                m.churned = True
                m.churn_month = churn_month
                return

    def analyze_cohort(self, cohort_key: str, months_to_analyze: int = 12) -> CohortMetrics:
        """Analyze a single cohort."""
        members = [m for m in self._members if m.cohort_key == cohort_key]
        size = len(members)
        if size == 0:
            return CohortMetrics(
                cohort_key=cohort_key, size=0,
                retention_by_month={}, revenue_by_month={},
                churn_rate=0, avg_lifetime_months=0,
                avg_revenue_per_user=0, ltv_estimate=0,
            )

        # Parse cohort start
        year, month = map(int, cohort_key.split("-"))

        retention: dict[int, float] = {}
        revenue: dict[int, float] = {}

        for offset in range(months_to_analyze):
            m = month + offset
            y = year + (m - 1) // 12
            m = ((m - 1) % 12) + 1
            month_key = f"{y:04d}-{m:02d}"

            active_count = sum(1 for mbr in members if month_key in mbr.active_months)
            month_revenue = sum(
                mbr.total_revenue / max(1, len(mbr.active_months))
                for mbr in members if month_key in mbr.active_months
            )

            retention[offset] = round(active_count / size * 100, 2)
            revenue[offset] = round(month_revenue, 2)

        churned = sum(1 for m in members if m.churned)
        churn_rate = round(churned / size * 100, 2)

        # Avg lifetime
        lifetimes = [len(m.active_months) for m in members]
        avg_lifetime = sum(lifetimes) / len(lifetimes) if lifetimes else 0

        total_rev = sum(m.total_revenue for m in members)
        avg_arpu = round(total_rev / size, 2)

        # Simple LTV = ARPU * avg_lifetime
        ltv = round(avg_arpu * avg_lifetime, 2)

        return CohortMetrics(
            cohort_key=cohort_key,
            size=size,
            retention_by_month=retention,
            revenue_by_month=revenue,
            churn_rate=churn_rate,
            avg_lifetime_months=round(avg_lifetime, 1),
            avg_revenue_per_user=avg_arpu,
            ltv_estimate=ltv,
        )

    def generate_retention_matrix(self, months: int = 12) -> RetentionMatrix:
        """Generate full retention matrix across all cohorts."""
        cohort_keys = sorted(set(m.cohort_key for m in self._members))
        cohorts = [self.analyze_cohort(k, months) for k in cohort_keys]

        # Overall retention
        overall: dict[int, list[float]] = {}
        for c in cohorts:
            for offset, rate in c.retention_by_month.items():
                overall.setdefault(offset, []).append(rate)

        overall_retention = {
            k: round(sum(v) / len(v), 2) for k, v in overall.items()
        }

        best = max(cohorts, key=lambda c: c.ltv_estimate) if cohorts else None
        worst = min(cohorts, key=lambda c: c.ltv_estimate) if cohorts else None

        return RetentionMatrix(
            cohorts=cohorts,
            overall_retention_by_month=overall_retention,
            best_cohort=best.cohort_key if best else "",
            worst_cohort=worst.cohort_key if worst else "",
        )

    def get_members(self, cohort_key: str | None = None) -> list[CohortMember]:
        if cohort_key:
            return [m for m in self._members if m.cohort_key == cohort_key]
        return list(self._members)
