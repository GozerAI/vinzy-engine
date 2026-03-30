"""Cross-product recommendation engine and upsell targeting.

Item 293: Cross-product recommendations based on usage patterns.
Item 298: Automated upgrade email sequences.
Item 304: Feature usage analytics for upsell targeting.
Item 326: Usage growth notification with upgrade prompt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class RecommendationType(str, Enum):
    UPGRADE = "upgrade"
    CROSS_SELL = "cross_sell"
    ADD_ON = "add_on"
    BUNDLE = "bundle"


class NotificationChannel(str, Enum):
    EMAIL = "email"
    IN_APP = "in_app"
    WEBHOOK = "webhook"


@dataclass
class ProductRecommendation:
    """A product recommendation for a customer."""
    recommendation_id: str
    license_id: str
    type: RecommendationType
    product_code: str
    score: float  # 0.0-1.0 relevance score
    reason: str
    current_tier: str | None = None
    recommended_tier: str | None = None
    estimated_value: float = 0.0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class UpgradeSequence:
    """An automated upgrade email sequence."""
    sequence_id: str
    license_id: str
    trigger_reason: str
    current_tier: str
    target_tier: str
    steps: list[SequenceStep]
    status: str = "active"  # active, completed, cancelled
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class SequenceStep:
    """A step in an upgrade sequence."""
    step_number: int
    channel: NotificationChannel
    template: str
    delay_hours: int
    sent: bool = False
    sent_at: datetime | None = None
    opened: bool = False
    clicked: bool = False


@dataclass
class UsageGrowthAlert:
    """Alert for significant usage growth."""
    alert_id: str
    license_id: str
    metric: str
    current_usage: float
    limit: float
    usage_pct: float
    growth_rate: float  # period-over-period
    recommendation: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class FeatureUsageInsight:
    """Feature usage insight for upsell targeting."""
    license_id: str
    feature: str
    usage_count: int
    usage_pct_of_limit: float
    is_gated: bool  # Available in higher tier
    gate_tier: str | None  # Tier required
    upsell_potential: float  # 0-1 score
    metadata: dict[str, Any] = field(default_factory=dict)


# Cross-product affinity matrix (product A users often need product B)
PRODUCT_AFFINITY = {
    "NXS": [("TS", 0.8, "Intelligence gathering enhances AI orchestration")],
    "TS": [("SF", 0.7, "Apply trend insights to commerce"), ("BG", 0.6, "Protect brand in trending markets")],
    "SF": [("BG", 0.75, "Brand protection for commerce"), ("TP", 0.5, "Task management for store ops")],
    "AGW": [("NXS", 0.85, "Nexus provides reasoning for agents"), ("CS", 0.7, "Swarm enhances multi-agent patterns")],
    "ZUL": [("VNZ", 0.8, "License management pairs with identity"), ("AGW", 0.5, "Secure agent authentication")],
    "ARC": [("TS", 0.75, "Trend data improves business cycles"), ("NXS", 0.6, "Intelligence for business decisions")],
}


class CrossProductRecommendationEngine:
    """Generate cross-product recommendations based on usage patterns."""

    def __init__(self):
        self._recommendations: list[ProductRecommendation] = []
        self._sequences: list[UpgradeSequence] = []
        self._growth_alerts: list[UsageGrowthAlert] = []
        self._rec_counter = 0
        self._seq_counter = 0
        self._alert_counter = 0

    def _next_rec_id(self) -> str:
        self._rec_counter += 1
        return f"REC-{self._rec_counter:06d}"

    def _next_seq_id(self) -> str:
        self._seq_counter += 1
        return f"SEQ-{self._seq_counter:06d}"

    def _next_alert_id(self) -> str:
        self._alert_counter += 1
        return f"UGA-{self._alert_counter:06d}"

    def generate_recommendations(
        self,
        license_id: str,
        current_products: list[str],
        usage_data: dict[str, float] | None = None,
        tier: str = "pro",
    ) -> list[ProductRecommendation]:
        """Generate cross-product recommendations based on current products."""
        recs = []
        seen = set(current_products)

        for product in current_products:
            affinities = PRODUCT_AFFINITY.get(product, [])
            for target_product, score, reason in affinities:
                if target_product not in seen:
                    seen.add(target_product)
                    rec = ProductRecommendation(
                        recommendation_id=self._next_rec_id(),
                        license_id=license_id,
                        type=RecommendationType.CROSS_SELL,
                        product_code=target_product,
                        score=score,
                        reason=reason,
                        current_tier=tier,
                    )
                    recs.append(rec)
                    self._recommendations.append(rec)

        # Sort by score descending
        recs.sort(key=lambda r: r.score, reverse=True)
        return recs

    def check_upgrade_eligibility(
        self,
        license_id: str,
        tier: str,
        usage_pct: float,
        feature_gate_hits: int = 0,
    ) -> ProductRecommendation | None:
        """Check if customer should be recommended an upgrade."""
        tier_upgrades = {
            "community": ("pro", 0.5),
            "pro": ("growth", 0.7),
            "growth": ("scale", 0.85),
        }

        upgrade = tier_upgrades.get(tier)
        if upgrade is None:
            return None

        target_tier, threshold = upgrade
        score = 0.0

        if usage_pct >= threshold:
            score += 0.5
        if feature_gate_hits > 0:
            score += min(0.3, feature_gate_hits * 0.05)
        if usage_pct >= 0.9:
            score += 0.2

        if score >= 0.4:
            rec = ProductRecommendation(
                recommendation_id=self._next_rec_id(),
                license_id=license_id,
                type=RecommendationType.UPGRADE,
                product_code="",
                score=min(1.0, score),
                reason=f"Usage at {usage_pct*100:.0f}% of tier limit",
                current_tier=tier,
                recommended_tier=target_tier,
            )
            self._recommendations.append(rec)
            return rec
        return None

    def create_upgrade_sequence(
        self,
        license_id: str,
        current_tier: str,
        target_tier: str,
        trigger_reason: str,
    ) -> UpgradeSequence:
        """Create an automated upgrade email sequence."""
        steps = [
            SequenceStep(1, NotificationChannel.IN_APP, "usage_approaching_limit", delay_hours=0),
            SequenceStep(2, NotificationChannel.EMAIL, "upgrade_benefits", delay_hours=24),
            SequenceStep(3, NotificationChannel.EMAIL, "case_study", delay_hours=72),
            SequenceStep(4, NotificationChannel.EMAIL, "limited_offer", delay_hours=168),
            SequenceStep(5, NotificationChannel.IN_APP, "final_upgrade_prompt", delay_hours=336),
        ]

        sequence = UpgradeSequence(
            sequence_id=self._next_seq_id(),
            license_id=license_id,
            trigger_reason=trigger_reason,
            current_tier=current_tier,
            target_tier=target_tier,
            steps=steps,
        )
        self._sequences.append(sequence)
        return sequence

    def check_usage_growth(
        self,
        license_id: str,
        metric: str,
        current_usage: float,
        previous_usage: float,
        limit: float,
    ) -> UsageGrowthAlert | None:
        """Check for significant usage growth and generate alert."""
        if previous_usage == 0:
            growth_rate = 1.0 if current_usage > 0 else 0.0
        else:
            growth_rate = (current_usage - previous_usage) / previous_usage

        usage_pct = (current_usage / limit * 100) if limit > 0 else 0

        # Alert if >20% growth and >70% of limit
        if growth_rate >= 0.2 and usage_pct >= 70:
            recommendation = "Consider upgrading to accommodate growth"
            if usage_pct >= 90:
                recommendation = "Upgrade recommended - approaching limit"

            alert = UsageGrowthAlert(
                alert_id=self._next_alert_id(),
                license_id=license_id,
                metric=metric,
                current_usage=current_usage,
                limit=limit,
                usage_pct=round(usage_pct, 2),
                growth_rate=round(growth_rate, 4),
                recommendation=recommendation,
            )
            self._growth_alerts.append(alert)
            return alert
        return None

    def analyze_feature_usage(
        self,
        license_id: str,
        feature_usage: dict[str, int],
        feature_limits: dict[str, int],
        gated_features: dict[str, str],  # feature -> required tier
    ) -> list[FeatureUsageInsight]:
        """Analyze feature usage for upsell targeting."""
        insights = []
        for feature, count in feature_usage.items():
            limit = feature_limits.get(feature, 0)
            pct = (count / limit * 100) if limit > 0 else 0
            is_gated = feature in gated_features
            gate_tier = gated_features.get(feature)

            upsell_potential = 0.0
            if pct >= 80:
                upsell_potential += 0.4
            if is_gated:
                upsell_potential += 0.3
            if pct >= 95:
                upsell_potential += 0.3

            insights.append(FeatureUsageInsight(
                license_id=license_id,
                feature=feature,
                usage_count=count,
                usage_pct_of_limit=round(pct, 2),
                is_gated=is_gated,
                gate_tier=gate_tier,
                upsell_potential=min(1.0, upsell_potential),
            ))

        insights.sort(key=lambda i: i.upsell_potential, reverse=True)
        return insights

    def get_recommendations(
        self, license_id: str | None = None, type_filter: RecommendationType | None = None
    ) -> list[ProductRecommendation]:
        results = self._recommendations
        if license_id:
            results = [r for r in results if r.license_id == license_id]
        if type_filter:
            results = [r for r in results if r.type == type_filter]
        return results

    def get_sequences(self, license_id: str | None = None) -> list[UpgradeSequence]:
        if license_id:
            return [s for s in self._sequences if s.license_id == license_id]
        return list(self._sequences)

    def get_growth_alerts(self, license_id: str | None = None) -> list[UsageGrowthAlert]:
        if license_id:
            return [a for a in self._growth_alerts if a.license_id == license_id]
        return list(self._growth_alerts)
