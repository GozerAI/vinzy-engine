"""Pricing tier migration analytics.

Item 284: Track and analyze pricing tier migrations (upgrades, downgrades).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class MigrationDirection(str, Enum):
    UPGRADE = "upgrade"
    DOWNGRADE = "downgrade"
    LATERAL = "lateral"  # same tier level, different plan


TIER_ORDER = {"community": 0, "pro": 1, "growth": 2, "scale": 3}
TIER_ORDER["business"] = TIER_ORDER["growth"]
TIER_ORDER["enterprise"] = TIER_ORDER["scale"]


@dataclass
class TierMigration:
    """Record of a tier change."""
    migration_id: str
    license_id: str
    tenant_id: str | None
    from_tier: str
    to_tier: str
    direction: MigrationDirection
    from_price: float
    to_price: float
    revenue_impact: float  # positive = more revenue
    reason: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MigrationAnalytics:
    """Aggregated migration analytics."""
    total_migrations: int
    upgrades: int
    downgrades: int
    lateral: int
    net_revenue_impact: float
    avg_time_to_upgrade_days: float
    top_upgrade_paths: list[tuple[str, str, int]]  # (from, to, count)
    top_downgrade_paths: list[tuple[str, str, int]]
    churn_after_downgrade_pct: float
    period_start: datetime
    period_end: datetime


class TierMigrationTracker:
    """Track and analyze pricing tier migrations."""

    def __init__(self):
        self._migrations: list[TierMigration] = []
        self._counter = 0

    def _next_id(self) -> str:
        self._counter += 1
        return f"MIG-{self._counter:06d}"

    def _direction(self, from_tier: str, to_tier: str) -> MigrationDirection:
        from_level = TIER_ORDER.get(from_tier.lower(), 0)
        to_level = TIER_ORDER.get(to_tier.lower(), 0)
        if to_level > from_level:
            return MigrationDirection.UPGRADE
        elif to_level < from_level:
            return MigrationDirection.DOWNGRADE
        return MigrationDirection.LATERAL

    def record_migration(
        self,
        license_id: str,
        tenant_id: str | None,
        from_tier: str,
        to_tier: str,
        from_price: float,
        to_price: float,
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> TierMigration:
        direction = self._direction(from_tier, to_tier)
        migration = TierMigration(
            migration_id=self._next_id(),
            license_id=license_id,
            tenant_id=tenant_id,
            from_tier=from_tier,
            to_tier=to_tier,
            direction=direction,
            from_price=from_price,
            to_price=to_price,
            revenue_impact=round(to_price - from_price, 2),
            reason=reason,
            metadata=metadata or {},
        )
        self._migrations.append(migration)
        return migration

    def get_migrations(
        self,
        license_id: str | None = None,
        direction: MigrationDirection | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[TierMigration]:
        results = self._migrations
        if license_id:
            results = [m for m in results if m.license_id == license_id]
        if direction:
            results = [m for m in results if m.direction == direction]
        if since:
            results = [m for m in results if m.timestamp >= since]
        if until:
            results = [m for m in results if m.timestamp <= until]
        return results

    def analyze(
        self,
        period_start: datetime,
        period_end: datetime,
    ) -> MigrationAnalytics:
        """Generate migration analytics for a period."""
        migrations = self.get_migrations(since=period_start, until=period_end)

        upgrades = [m for m in migrations if m.direction == MigrationDirection.UPGRADE]
        downgrades = [m for m in migrations if m.direction == MigrationDirection.DOWNGRADE]
        laterals = [m for m in migrations if m.direction == MigrationDirection.LATERAL]

        # Path counting
        from collections import Counter
        upgrade_paths = Counter((m.from_tier, m.to_tier) for m in upgrades)
        downgrade_paths = Counter((m.from_tier, m.to_tier) for m in downgrades)

        top_up = [(f, t, c) for (f, t), c in upgrade_paths.most_common(5)]
        top_down = [(f, t, c) for (f, t), c in downgrade_paths.most_common(5)]

        # Revenue impact
        net_impact = sum(m.revenue_impact for m in migrations)

        # Average time to upgrade (from first migration per license)
        upgrade_times: list[float] = []
        license_first_seen: dict[str, datetime] = {}
        for m in sorted(self._migrations, key=lambda x: x.timestamp):
            if m.license_id not in license_first_seen:
                license_first_seen[m.license_id] = m.timestamp
            if m.direction == MigrationDirection.UPGRADE and m.license_id in license_first_seen:
                delta = (m.timestamp - license_first_seen[m.license_id]).days
                if delta > 0:
                    upgrade_times.append(delta)

        avg_upgrade_days = sum(upgrade_times) / len(upgrade_times) if upgrade_times else 0

        return MigrationAnalytics(
            total_migrations=len(migrations),
            upgrades=len(upgrades),
            downgrades=len(downgrades),
            lateral=len(laterals),
            net_revenue_impact=round(net_impact, 2),
            avg_time_to_upgrade_days=round(avg_upgrade_days, 1),
            top_upgrade_paths=top_up,
            top_downgrade_paths=top_down,
            churn_after_downgrade_pct=0.0,  # Needs churn data integration
            period_start=period_start,
            period_end=period_end,
        )
