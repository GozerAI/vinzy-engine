"""Trial management, conversion, and engagement tracking.

Item 369: Trial extension based on engagement.
Item 373: Trial usage analytics for conversion prediction.
Item 377: Trial-to-paid transition with saved progress.
Item 382: Trial conversion incentive (discount for early conversion).
Item 386: Abandoned trial re-engagement.
Item 390: Trial referral program.
Item 394: Trial segment analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any


class TrialStatus(str, Enum):
    ACTIVE = "active"
    EXTENDED = "extended"
    CONVERTING = "converting"
    CONVERTED = "converted"
    EXPIRED = "expired"
    ABANDONED = "abandoned"


class TrialSegment(str, Enum):
    HIGHLY_ENGAGED = "highly_engaged"
    MODERATELY_ENGAGED = "moderately_engaged"
    LOW_ENGAGEMENT = "low_engagement"
    INACTIVE = "inactive"
    POWER_USER = "power_user"


@dataclass
class Trial:
    """A trial subscription."""
    trial_id: str
    license_id: str
    email: str
    product_codes: list[str]
    tier: str = "pro"
    status: TrialStatus = TrialStatus.ACTIVE
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc) + timedelta(days=14))
    extended_days: int = 0
    max_extensions: int = 2
    extensions_used: int = 0
    conversion_discount_pct: float = 0.0
    referral_code: str = ""
    referred_by: str | None = None
    segment: TrialSegment | None = None
    usage_data: dict[str, float] = field(default_factory=dict)
    features_explored: list[str] = field(default_factory=list)
    progress_data: dict[str, Any] = field(default_factory=dict)  # Saved progress for transition
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def days_remaining(self) -> int:
        expires = self.expires_at.replace(tzinfo=timezone.utc) if self.expires_at.tzinfo is None else self.expires_at
        return max(0, (expires - datetime.now(timezone.utc)).days)

    @property
    def days_active(self) -> int:
        started = self.started_at.replace(tzinfo=timezone.utc) if self.started_at.tzinfo is None else self.started_at
        return (datetime.now(timezone.utc) - started).days

    @property
    def is_expired(self) -> bool:
        expires = self.expires_at.replace(tzinfo=timezone.utc) if self.expires_at.tzinfo is None else self.expires_at
        return datetime.now(timezone.utc) > expires


@dataclass
class ConversionPrediction:
    """Predicted likelihood of trial conversion."""
    trial_id: str
    conversion_probability: float  # 0.0-1.0
    confidence: float
    key_factors: list[str]
    recommended_action: str
    predicted_plan: str | None = None
    predicted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class TrialIncentive:
    """Incentive for trial conversion."""
    incentive_id: str
    trial_id: str
    type: str  # early_conversion_discount, extended_trial, bonus_credits
    value: float
    description: str
    valid_until: datetime
    redeemed: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class TrialReferral:
    """Trial referral record."""
    referral_id: str
    referrer_trial_id: str
    referred_email: str
    referral_code: str
    status: str = "pending"  # pending, signed_up, converted
    reward_given: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class SegmentAnalysis:
    """Analysis of a trial segment."""
    segment: TrialSegment
    count: int
    avg_days_active: float
    conversion_rate: float
    avg_features_explored: float
    top_features: list[str]
    avg_usage: float
    recommendations: list[str]


class TrialEngine:
    """Comprehensive trial management with conversion optimization."""

    def __init__(self, default_trial_days: int = 14, max_extension_days: int = 7):
        self._trials: dict[str, Trial] = {}
        self._incentives: list[TrialIncentive] = []
        self._referrals: list[TrialReferral] = []
        self._trial_counter = 0
        self._incentive_counter = 0
        self._referral_counter = 0

        self._default_trial_days = default_trial_days
        self._max_extension_days = max_extension_days

    def _next_trial_id(self) -> str:
        self._trial_counter += 1
        return f"TRL-{self._trial_counter:06d}"

    def _next_incentive_id(self) -> str:
        self._incentive_counter += 1
        return f"TINC-{self._incentive_counter:06d}"

    def _next_referral_id(self) -> str:
        self._referral_counter += 1
        return f"TREF-{self._referral_counter:06d}"

    # ── Trial Management ──

    def create_trial(
        self,
        license_id: str,
        email: str,
        product_codes: list[str],
        tier: str = "pro",
        days: int | None = None,
        referred_by: str | None = None,
    ) -> Trial:
        trial_days = days or self._default_trial_days
        now = datetime.now(timezone.utc)

        import secrets
        referral_code = f"TRL-{secrets.token_urlsafe(8)}"

        trial = Trial(
            trial_id=self._next_trial_id(),
            license_id=license_id,
            email=email,
            product_codes=product_codes,
            tier=tier,
            started_at=now,
            expires_at=now + timedelta(days=trial_days),
            referral_code=referral_code,
            referred_by=referred_by,
        )
        self._trials[trial.trial_id] = trial
        return trial

    def record_usage(
        self, trial_id: str, metric: str, value: float = 1.0
    ) -> Trial:
        trial = self._trials.get(trial_id)
        if trial is None:
            raise ValueError(f"Trial not found: {trial_id}")
        trial.usage_data[metric] = trial.usage_data.get(metric, 0) + value
        return trial

    def record_feature_explored(self, trial_id: str, feature: str) -> Trial:
        trial = self._trials.get(trial_id)
        if trial is None:
            raise ValueError(f"Trial not found: {trial_id}")
        if feature not in trial.features_explored:
            trial.features_explored.append(feature)
        return trial

    def save_progress(self, trial_id: str, progress: dict[str, Any]) -> Trial:
        """Save user progress for seamless trial-to-paid transition."""
        trial = self._trials.get(trial_id)
        if trial is None:
            raise ValueError(f"Trial not found: {trial_id}")
        trial.progress_data.update(progress)
        return trial

    # ── Extension (369) ──

    def extend_trial(
        self, trial_id: str, days: int | None = None, reason: str = ""
    ) -> Trial:
        """Extend trial based on engagement level."""
        trial = self._trials.get(trial_id)
        if trial is None:
            raise ValueError(f"Trial not found: {trial_id}")
        if trial.extensions_used >= trial.max_extensions:
            raise ValueError("Maximum extensions reached")

        ext_days = min(days or self._max_extension_days, self._max_extension_days)
        trial.expires_at = trial.expires_at + timedelta(days=ext_days)
        trial.extended_days += ext_days
        trial.extensions_used += 1
        trial.status = TrialStatus.EXTENDED
        return trial

    def auto_extend_if_engaged(self, trial_id: str) -> Trial | None:
        """Auto-extend trial if user is sufficiently engaged."""
        trial = self._trials.get(trial_id)
        if trial is None or trial.extensions_used >= trial.max_extensions:
            return None
        if trial.days_remaining > 3:
            return None

        # Check engagement
        total_usage = sum(trial.usage_data.values())
        features = len(trial.features_explored)

        if total_usage >= 10 or features >= 3:
            return self.extend_trial(trial_id, reason="auto_engagement")
        return None

    # ── Conversion Prediction (373) ──

    def predict_conversion(self, trial_id: str) -> ConversionPrediction:
        """Predict likelihood of trial conversion."""
        trial = self._trials.get(trial_id)
        if trial is None:
            raise ValueError(f"Trial not found: {trial_id}")

        score = 0.0
        factors = []

        # Usage volume
        total_usage = sum(trial.usage_data.values())
        if total_usage >= 50:
            score += 0.3
            factors.append("High usage volume")
        elif total_usage >= 20:
            score += 0.15
            factors.append("Moderate usage")

        # Feature exploration
        features = len(trial.features_explored)
        if features >= 5:
            score += 0.25
            factors.append("Explored many features")
        elif features >= 3:
            score += 0.15
            factors.append("Good feature exploration")

        # Recency
        if trial.days_active <= 3 and total_usage > 0:
            score += 0.15
            factors.append("Early adoption")

        # Progress saved
        if trial.progress_data:
            score += 0.15
            factors.append("Has saved progress/data")

        # Referral source
        if trial.referred_by:
            score += 0.1
            factors.append("Referred by existing user")

        score = min(1.0, score)

        # Recommendation
        if score >= 0.7:
            action = "Send conversion offer - high probability"
        elif score >= 0.4:
            action = "Nurture with feature highlights"
        else:
            action = "Re-engage with onboarding assistance"

        return ConversionPrediction(
            trial_id=trial_id,
            conversion_probability=round(score, 3),
            confidence=0.7,
            key_factors=factors,
            recommended_action=action,
            predicted_plan=trial.tier,
        )

    # ── Conversion Incentive (382) ──

    def create_early_conversion_incentive(
        self, trial_id: str, discount_pct: float = 20.0
    ) -> TrialIncentive:
        """Create a discount incentive for early trial conversion."""
        trial = self._trials.get(trial_id)
        if trial is None:
            raise ValueError(f"Trial not found: {trial_id}")

        # Better discount for earlier conversion
        if trial.days_active <= 3:
            actual_discount = discount_pct * 1.5  # 50% better for very early
        elif trial.days_active <= 7:
            actual_discount = discount_pct
        else:
            actual_discount = discount_pct * 0.75

        incentive = TrialIncentive(
            incentive_id=self._next_incentive_id(),
            trial_id=trial_id,
            type="early_conversion_discount",
            value=min(actual_discount, 40),  # Cap at 40%
            description=f"Convert now and save {actual_discount:.0f}%!",
            valid_until=trial.expires_at,
        )
        self._incentives.append(incentive)
        trial.conversion_discount_pct = incentive.value
        return incentive

    # ── Trial-to-Paid Transition (377) ──

    def convert_trial(self, trial_id: str) -> dict[str, Any]:
        """Convert trial to paid, preserving progress."""
        trial = self._trials.get(trial_id)
        if trial is None:
            raise ValueError(f"Trial not found: {trial_id}")

        trial.status = TrialStatus.CONVERTED
        return {
            "trial_id": trial_id,
            "license_id": trial.license_id,
            "tier": trial.tier,
            "products": trial.product_codes,
            "discount_pct": trial.conversion_discount_pct,
            "progress_data": trial.progress_data,
            "usage_data": trial.usage_data,
            "features_explored": trial.features_explored,
            "days_in_trial": trial.days_active,
        }

    # ── Abandoned Trial Re-engagement (386) ──

    def detect_abandoned_trials(self, inactive_days: int = 5) -> list[Trial]:
        """Find trials that appear abandoned."""
        abandoned = []
        for trial in self._trials.values():
            if trial.status in (TrialStatus.ACTIVE, TrialStatus.EXTENDED):
                total_usage = sum(trial.usage_data.values())
                if total_usage == 0 and trial.days_active >= inactive_days:
                    trial.status = TrialStatus.ABANDONED
                    abandoned.append(trial)
                elif trial.days_active >= inactive_days + 3 and total_usage < 5:
                    abandoned.append(trial)
        return abandoned

    # ── Trial Referral Program (390) ──

    def create_referral(self, referrer_trial_id: str, referred_email: str) -> TrialReferral:
        """Create a trial referral."""
        trial = self._trials.get(referrer_trial_id)
        if trial is None:
            raise ValueError(f"Trial not found: {referrer_trial_id}")

        referral = TrialReferral(
            referral_id=self._next_referral_id(),
            referrer_trial_id=referrer_trial_id,
            referred_email=referred_email,
            referral_code=trial.referral_code,
        )
        self._referrals.append(referral)
        return referral

    def complete_referral(self, referral_id: str) -> TrialReferral:
        for ref in self._referrals:
            if ref.referral_id == referral_id:
                ref.status = "converted"
                ref.reward_given = True
                # Extend referrer's trial
                trial = self._trials.get(ref.referrer_trial_id)
                if trial and trial.extensions_used < trial.max_extensions:
                    trial.expires_at += timedelta(days=3)
                    trial.extensions_used += 1
                return ref
        raise ValueError(f"Referral not found: {referral_id}")

    # ── Segment Analysis (394) ──

    def segment_trial(self, trial_id: str) -> TrialSegment:
        """Segment a trial based on engagement."""
        trial = self._trials.get(trial_id)
        if trial is None:
            raise ValueError(f"Trial not found: {trial_id}")

        total_usage = sum(trial.usage_data.values())
        features = len(trial.features_explored)

        if total_usage >= 100 and features >= 7:
            segment = TrialSegment.POWER_USER
        elif total_usage >= 30 and features >= 4:
            segment = TrialSegment.HIGHLY_ENGAGED
        elif total_usage >= 10 or features >= 2:
            segment = TrialSegment.MODERATELY_ENGAGED
        elif total_usage > 0:
            segment = TrialSegment.LOW_ENGAGEMENT
        else:
            segment = TrialSegment.INACTIVE

        trial.segment = segment
        return segment

    def analyze_segments(self) -> list[SegmentAnalysis]:
        """Analyze all trials by segment."""
        # Segment all trials first
        for trial_id in self._trials:
            self.segment_trial(trial_id)

        segment_groups: dict[TrialSegment, list[Trial]] = {}
        for trial in self._trials.values():
            seg = trial.segment or TrialSegment.INACTIVE
            segment_groups.setdefault(seg, []).append(trial)

        analyses = []
        for segment, trials in segment_groups.items():
            converted = sum(1 for t in trials if t.status == TrialStatus.CONVERTED)
            total_usage_values = [sum(t.usage_data.values()) for t in trials]

            # Top features across segment
            from collections import Counter
            feature_counter = Counter()
            for t in trials:
                feature_counter.update(t.features_explored)

            recommendations = []
            if segment == TrialSegment.INACTIVE:
                recommendations.append("Send onboarding guide and getting-started tips")
            elif segment == TrialSegment.LOW_ENGAGEMENT:
                recommendations.append("Provide targeted feature walkthroughs")
            elif segment == TrialSegment.HIGHLY_ENGAGED:
                recommendations.append("Offer early conversion discount")
            elif segment == TrialSegment.POWER_USER:
                recommendations.append("Fast-track to paid with premium tier offer")

            analyses.append(SegmentAnalysis(
                segment=segment,
                count=len(trials),
                avg_days_active=sum(t.days_active for t in trials) / max(1, len(trials)),
                conversion_rate=round(converted / max(1, len(trials)) * 100, 2),
                avg_features_explored=sum(len(t.features_explored) for t in trials) / max(1, len(trials)),
                top_features=[f for f, _ in feature_counter.most_common(5)],
                avg_usage=sum(total_usage_values) / max(1, len(total_usage_values)),
                recommendations=recommendations,
            ))

        return analyses

    # ── Getters ──

    def get_trial(self, trial_id: str) -> Trial | None:
        return self._trials.get(trial_id)

    def get_trials(
        self, status: TrialStatus | None = None, segment: TrialSegment | None = None
    ) -> list[Trial]:
        results = list(self._trials.values())
        if status:
            results = [t for t in results if t.status == status]
        if segment:
            results = [t for t in results if t.segment == segment]
        return results

    def get_incentives(self, trial_id: str | None = None) -> list[TrialIncentive]:
        if trial_id:
            return [i for i in self._incentives if i.trial_id == trial_id]
        return list(self._incentives)

    def get_referrals(self, trial_id: str | None = None) -> list[TrialReferral]:
        if trial_id:
            return [r for r in self._referrals if r.referrer_trial_id == trial_id]
        return list(self._referrals)
