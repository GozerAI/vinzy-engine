"""Churn prevention, win-back, and subscription management.

Item 330: Predictive churn-to-upsell conversion.
Item 332: Early warning system for declining usage.
Item 340: Subscription pause as alternative to cancel.
Item 356: Involuntary churn prevention (card update reminders).
Item 360: Multi-channel win-back (email, in-app, SMS).
Item 364: Grace period with limited access for expired subscriptions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any


class ChurnRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SubscriptionState(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    GRACE_PERIOD = "grace_period"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    WIN_BACK = "win_back"


class WinBackChannel(str, Enum):
    EMAIL = "email"
    IN_APP = "in_app"
    SMS = "sms"
    WEBHOOK = "webhook"


@dataclass
class ChurnRiskAssessment:
    """Churn risk assessment for a customer."""
    assessment_id: str
    license_id: str
    risk_level: ChurnRisk
    risk_score: float  # 0.0-1.0
    signals: list[ChurnSignal]
    recommended_actions: list[str]
    upsell_opportunity: bool = False
    upsell_reason: str = ""
    assessed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ChurnSignal:
    """A signal contributing to churn risk."""
    signal_type: str
    weight: float  # contribution to risk score
    value: Any
    description: str


@dataclass
class UsageDeclineAlert:
    """Alert for declining usage patterns."""
    alert_id: str
    license_id: str
    metric: str
    current_value: float
    previous_value: float
    decline_pct: float
    consecutive_declines: int
    severity: str  # info, warning, critical
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class SubscriptionPause:
    """A subscription pause record."""
    pause_id: str
    license_id: str
    reason: str
    paused_at: datetime
    resume_date: datetime
    max_pause_days: int = 90
    auto_resume: bool = True
    features_during_pause: list[str] = field(default_factory=list)  # Limited features
    status: str = "active"  # active, resumed, expired
    resumed_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def days_paused(self) -> int:
        end = self.resumed_at or datetime.now(timezone.utc)
        paused = self.paused_at
        if paused.tzinfo is None:
            paused = paused.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        return (end - paused).days


@dataclass
class GracePeriod:
    """Grace period for expired subscriptions."""
    grace_id: str
    license_id: str
    started_at: datetime
    ends_at: datetime
    access_level: str = "limited"  # limited, read_only, none
    features_allowed: list[str] = field(default_factory=list)
    converted: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_active(self) -> bool:
        now = datetime.now(timezone.utc)
        ends = self.ends_at.replace(tzinfo=timezone.utc) if self.ends_at.tzinfo is None else self.ends_at
        return now <= ends and not self.converted

    @property
    def days_remaining(self) -> int:
        now = datetime.now(timezone.utc)
        ends = self.ends_at.replace(tzinfo=timezone.utc) if self.ends_at.tzinfo is None else self.ends_at
        return max(0, (ends - now).days)


@dataclass
class WinBackCampaign:
    """Multi-channel win-back campaign."""
    campaign_id: str
    license_id: str
    channels: list[WinBackChannel]
    offer_type: str  # discount, free_month, tier_upgrade, credits
    offer_value: float
    status: str = "active"  # active, converted, expired, cancelled
    messages_sent: dict[str, bool] = field(default_factory=dict)  # channel -> sent
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None
    converted_at: datetime | None = None


@dataclass
class CardUpdateReminder:
    """Reminder to update payment card."""
    reminder_id: str
    license_id: str
    card_last_four: str
    expiry_month: int
    expiry_year: int
    reminders_sent: int = 0
    updated: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ChurnPreventionEngine:
    """Comprehensive churn prevention and win-back system."""

    def __init__(self, grace_period_days: int = 14, max_pause_days: int = 90):
        self._grace_period_days = grace_period_days
        self._max_pause_days = max_pause_days
        self._assessments: list[ChurnRiskAssessment] = []
        self._decline_alerts: list[UsageDeclineAlert] = []
        self._pauses: dict[str, SubscriptionPause] = {}
        self._grace_periods: dict[str, GracePeriod] = {}
        self._campaigns: list[WinBackCampaign] = []
        self._card_reminders: list[CardUpdateReminder] = []
        self._assessment_counter = 0
        self._alert_counter = 0
        self._pause_counter = 0
        self._grace_counter = 0
        self._campaign_counter = 0
        self._reminder_counter = 0

    def _next_assessment_id(self) -> str:
        self._assessment_counter += 1
        return f"CRA-{self._assessment_counter:06d}"

    def _next_alert_id(self) -> str:
        self._alert_counter += 1
        return f"UDA-{self._alert_counter:06d}"

    def _next_pause_id(self) -> str:
        self._pause_counter += 1
        return f"PSE-{self._pause_counter:06d}"

    def _next_grace_id(self) -> str:
        self._grace_counter += 1
        return f"GRC-{self._grace_counter:06d}"

    def _next_campaign_id(self) -> str:
        self._campaign_counter += 1
        return f"WBK-{self._campaign_counter:06d}"

    def _next_reminder_id(self) -> str:
        self._reminder_counter += 1
        return f"CRD-{self._reminder_counter:06d}"

    # ── Churn Risk Assessment (330) ──

    def assess_churn_risk(
        self,
        license_id: str,
        usage_trend: float,         # -1 to +1 (negative = declining)
        days_since_last_login: int,
        support_tickets_30d: int,
        feature_adoption_pct: float,
        payment_failures_90d: int,
        tier: str = "pro",
    ) -> ChurnRiskAssessment:
        """Assess churn risk with conversion opportunity detection."""
        signals: list[ChurnSignal] = []
        score = 0.0

        # Usage trend
        if usage_trend < -0.3:
            weight = 0.3
            signals.append(ChurnSignal("usage_declining", weight, usage_trend, "Significant usage decline"))
            score += weight
        elif usage_trend < 0:
            weight = 0.1
            signals.append(ChurnSignal("usage_slight_decline", weight, usage_trend, "Slight usage decline"))
            score += weight

        # Login recency
        if days_since_last_login > 30:
            weight = 0.25
            signals.append(ChurnSignal("inactive", weight, days_since_last_login, f"No login in {days_since_last_login} days"))
            score += weight
        elif days_since_last_login > 14:
            weight = 0.1
            signals.append(ChurnSignal("low_engagement", weight, days_since_last_login, "Reduced engagement"))
            score += weight

        # Support friction
        if support_tickets_30d >= 3:
            weight = 0.2
            signals.append(ChurnSignal("support_friction", weight, support_tickets_30d, f"{support_tickets_30d} support tickets"))
            score += weight

        # Feature adoption
        if feature_adoption_pct < 0.2:
            weight = 0.15
            signals.append(ChurnSignal("low_adoption", weight, feature_adoption_pct, "Low feature adoption"))
            score += weight

        # Payment issues
        if payment_failures_90d > 0:
            weight = 0.1 * payment_failures_90d
            signals.append(ChurnSignal("payment_issues", weight, payment_failures_90d, "Payment failures"))
            score += weight

        score = min(1.0, score)

        # Determine risk level
        if score >= 0.7:
            risk = ChurnRisk.CRITICAL
        elif score >= 0.5:
            risk = ChurnRisk.HIGH
        elif score >= 0.3:
            risk = ChurnRisk.MEDIUM
        else:
            risk = ChurnRisk.LOW

        # Check upsell opportunity (paradoxical churn-to-upsell)
        upsell = False
        upsell_reason = ""
        if usage_trend > 0.2 and feature_adoption_pct > 0.7:
            upsell = True
            upsell_reason = "High usage and adoption - candidate for tier upgrade"

        # Recommended actions
        actions = []
        if score >= 0.5:
            actions.append("Send personalized retention offer")
        if days_since_last_login > 14:
            actions.append("Send re-engagement email")
        if support_tickets_30d >= 3:
            actions.append("Assign dedicated support contact")
        if feature_adoption_pct < 0.3:
            actions.append("Schedule onboarding follow-up")
        if payment_failures_90d > 0:
            actions.append("Send payment update reminder")

        assessment = ChurnRiskAssessment(
            assessment_id=self._next_assessment_id(),
            license_id=license_id,
            risk_level=risk,
            risk_score=round(score, 3),
            signals=signals,
            recommended_actions=actions,
            upsell_opportunity=upsell,
            upsell_reason=upsell_reason,
        )
        self._assessments.append(assessment)
        return assessment

    # ── Usage Decline Alerts (332) ──

    def check_usage_decline(
        self,
        license_id: str,
        metric: str,
        current_value: float,
        previous_value: float,
        consecutive_declines: int = 0,
    ) -> UsageDeclineAlert | None:
        """Check for declining usage and generate alert."""
        if previous_value == 0:
            return None
        decline = (previous_value - current_value) / previous_value
        if decline <= 0.1:  # Less than 10% decline, no alert
            return None

        decline_pct = round(decline * 100, 2)
        if decline_pct >= 50 or consecutive_declines >= 3:
            severity = "critical"
        elif decline_pct >= 30 or consecutive_declines >= 2:
            severity = "warning"
        else:
            severity = "info"

        alert = UsageDeclineAlert(
            alert_id=self._next_alert_id(),
            license_id=license_id,
            metric=metric,
            current_value=current_value,
            previous_value=previous_value,
            decline_pct=decline_pct,
            consecutive_declines=consecutive_declines,
            severity=severity,
        )
        self._decline_alerts.append(alert)
        return alert

    # ── Subscription Pause (340) ──

    def pause_subscription(
        self,
        license_id: str,
        reason: str,
        pause_days: int | None = None,
        features_during_pause: list[str] | None = None,
    ) -> SubscriptionPause:
        """Pause a subscription as alternative to cancellation."""
        days = min(pause_days or self._max_pause_days, self._max_pause_days)
        now = datetime.now(timezone.utc)

        pause = SubscriptionPause(
            pause_id=self._next_pause_id(),
            license_id=license_id,
            reason=reason,
            paused_at=now,
            resume_date=now + timedelta(days=days),
            max_pause_days=self._max_pause_days,
            features_during_pause=features_during_pause or ["read_only", "export_data"],
        )
        self._pauses[pause.pause_id] = pause
        return pause

    def resume_subscription(self, pause_id: str) -> SubscriptionPause:
        pause = self._pauses.get(pause_id)
        if pause is None:
            raise ValueError(f"Pause not found: {pause_id}")
        pause.status = "resumed"
        pause.resumed_at = datetime.now(timezone.utc)
        return pause

    # ── Grace Period (364) ──

    def create_grace_period(
        self,
        license_id: str,
        access_level: str = "limited",
        features_allowed: list[str] | None = None,
        days: int | None = None,
    ) -> GracePeriod:
        """Create a grace period for an expired subscription."""
        now = datetime.now(timezone.utc)
        grace_days = days or self._grace_period_days

        grace = GracePeriod(
            grace_id=self._next_grace_id(),
            license_id=license_id,
            started_at=now,
            ends_at=now + timedelta(days=grace_days),
            access_level=access_level,
            features_allowed=features_allowed or ["read_only", "export_data"],
        )
        self._grace_periods[grace.grace_id] = grace
        return grace

    def convert_grace_period(self, grace_id: str) -> GracePeriod:
        """Convert grace period back to active subscription."""
        grace = self._grace_periods.get(grace_id)
        if grace is None:
            raise ValueError(f"Grace period not found: {grace_id}")
        grace.converted = True
        return grace

    # ── Win-back Campaigns (360) ──

    def create_win_back_campaign(
        self,
        license_id: str,
        channels: list[WinBackChannel] | None = None,
        offer_type: str = "discount",
        offer_value: float = 20.0,
        valid_days: int = 30,
    ) -> WinBackCampaign:
        """Create a multi-channel win-back campaign."""
        campaign = WinBackCampaign(
            campaign_id=self._next_campaign_id(),
            license_id=license_id,
            channels=channels or [WinBackChannel.EMAIL, WinBackChannel.IN_APP],
            offer_type=offer_type,
            offer_value=offer_value,
            expires_at=datetime.now(timezone.utc) + timedelta(days=valid_days),
        )
        self._campaigns.append(campaign)
        return campaign

    def convert_win_back(self, campaign_id: str) -> WinBackCampaign:
        for c in self._campaigns:
            if c.campaign_id == campaign_id:
                c.status = "converted"
                c.converted_at = datetime.now(timezone.utc)
                return c
        raise ValueError(f"Campaign not found: {campaign_id}")

    # ── Card Update Reminders (356) ──

    def create_card_reminder(
        self, license_id: str, card_last_four: str, expiry_month: int, expiry_year: int
    ) -> CardUpdateReminder:
        reminder = CardUpdateReminder(
            reminder_id=self._next_reminder_id(),
            license_id=license_id,
            card_last_four=card_last_four,
            expiry_month=expiry_month,
            expiry_year=expiry_year,
        )
        self._card_reminders.append(reminder)
        return reminder

    def mark_card_updated(self, reminder_id: str) -> CardUpdateReminder:
        for r in self._card_reminders:
            if r.reminder_id == reminder_id:
                r.updated = True
                return r
        raise ValueError(f"Reminder not found: {reminder_id}")

    # ── Getters ──

    def get_assessments(self, license_id: str | None = None) -> list[ChurnRiskAssessment]:
        if license_id:
            return [a for a in self._assessments if a.license_id == license_id]
        return list(self._assessments)

    def get_decline_alerts(self, license_id: str | None = None) -> list[UsageDeclineAlert]:
        if license_id:
            return [a for a in self._decline_alerts if a.license_id == license_id]
        return list(self._decline_alerts)

    def get_pauses(self, license_id: str | None = None) -> list[SubscriptionPause]:
        pauses = list(self._pauses.values())
        if license_id:
            pauses = [p for p in pauses if p.license_id == license_id]
        return pauses

    def get_grace_periods(self, license_id: str | None = None) -> list[GracePeriod]:
        graces = list(self._grace_periods.values())
        if license_id:
            graces = [g for g in graces if g.license_id == license_id]
        return graces

    def get_campaigns(self, license_id: str | None = None) -> list[WinBackCampaign]:
        if license_id:
            return [c for c in self._campaigns if c.license_id == license_id]
        return list(self._campaigns)

    def get_card_reminders(self, license_id: str | None = None) -> list[CardUpdateReminder]:
        if license_id:
            return [r for r in self._card_reminders if r.license_id == license_id]
        return list(self._card_reminders)
