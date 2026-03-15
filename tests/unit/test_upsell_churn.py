"""Tests for upsell and churn modules."""

import pytest
from datetime import datetime, timedelta, timezone

from vinzy_engine.upsell.recommendations import (
    CrossProductRecommendationEngine, RecommendationType,
)
from vinzy_engine.upsell.loyalty import (
    LoyaltyEngine, LoyaltyTier, TIER_THRESHOLDS,
)
from vinzy_engine.churn.prevention import (
    ChurnPreventionEngine, ChurnRisk, WinBackChannel,
)


# ── Cross-Product Recommendations (293, 298, 304, 326) ──

class TestCrossProductRecommendations:
    def test_generate_recommendations(self):
        engine = CrossProductRecommendationEngine()
        recs = engine.generate_recommendations("lic1", ["NXS"], tier="pro")
        assert len(recs) > 0
        assert recs[0].type == RecommendationType.CROSS_SELL

    def test_no_duplicate_recommendations(self):
        engine = CrossProductRecommendationEngine()
        recs = engine.generate_recommendations("lic1", ["NXS", "TS"])
        product_codes = [r.product_code for r in recs]
        assert len(product_codes) == len(set(product_codes))

    def test_existing_product_not_recommended(self):
        engine = CrossProductRecommendationEngine()
        recs = engine.generate_recommendations("lic1", ["NXS", "TS"])
        codes = [r.product_code for r in recs]
        assert "NXS" not in codes
        assert "TS" not in codes

    def test_upgrade_eligibility_high_usage(self):
        engine = CrossProductRecommendationEngine()
        rec = engine.check_upgrade_eligibility("lic1", "pro", 0.85, feature_gate_hits=3)
        assert rec is not None
        assert rec.type == RecommendationType.UPGRADE
        assert rec.recommended_tier == "growth"

    def test_upgrade_not_needed_low_usage(self):
        engine = CrossProductRecommendationEngine()
        rec = engine.check_upgrade_eligibility("lic1", "pro", 0.3)
        assert rec is None

    def test_upgrade_sequence_creation(self):
        """Item 298: automated upgrade sequences."""
        engine = CrossProductRecommendationEngine()
        seq = engine.create_upgrade_sequence("lic1", "pro", "growth", "Usage at 90%")
        assert len(seq.steps) == 5
        assert seq.steps[0].channel.value == "in_app"

    def test_usage_growth_alert(self):
        """Item 326: usage growth notification."""
        engine = CrossProductRecommendationEngine()
        alert = engine.check_usage_growth("lic1", "ai_credits", 4500, 3000, 5000)
        assert alert is not None
        assert alert.growth_rate > 0
        assert alert.usage_pct >= 70

    def test_no_alert_low_growth(self):
        engine = CrossProductRecommendationEngine()
        alert = engine.check_usage_growth("lic1", "ai_credits", 1100, 1000, 5000)
        assert alert is None

    def test_feature_usage_analysis(self):
        """Item 304: feature usage analytics for upsell."""
        engine = CrossProductRecommendationEngine()
        insights = engine.analyze_feature_usage(
            "lic1",
            feature_usage={"api_calls": 950, "exports": 5},
            feature_limits={"api_calls": 1000, "exports": 100},
            gated_features={"advanced_analytics": "growth"},
        )
        assert len(insights) >= 2
        # api_calls at 95% should have high upsell potential
        api_insight = next(i for i in insights if i.feature == "api_calls")
        assert api_insight.upsell_potential > 0.5


# ── Loyalty Program (315, 319, 344) ──

class TestLoyaltyProgram:
    def test_enroll(self):
        engine = LoyaltyEngine()
        member = engine.enroll("lic1")
        assert member.tier == LoyaltyTier.BRONZE
        assert member.points == 0

    def test_tier_progression(self):
        engine = LoyaltyEngine()
        member = engine.enroll("lic1")
        engine.record_spend(member.member_id, 600)
        assert member.tier == LoyaltyTier.SILVER
        engine.record_spend(member.member_id, 1500)
        assert member.tier == LoyaltyTier.GOLD

    def test_tenure_rewards(self):
        """Item 344: loyalty rewards for long-tenure."""
        engine = LoyaltyEngine()
        member = engine.enroll("lic1")
        rewards = engine.update_tenure(member.member_id, 12)
        assert len(rewards) >= 3  # 3, 6, 12 month milestones

    def test_no_duplicate_rewards(self):
        engine = LoyaltyEngine()
        member = engine.enroll("lic1")
        engine.update_tenure(member.member_id, 6)
        rewards2 = engine.update_tenure(member.member_id, 6)
        assert len(rewards2) == 0  # Already claimed

    def test_renewal_incentives(self):
        """Item 319: renewal incentive automation."""
        engine = LoyaltyEngine()
        member = engine.enroll("lic1")
        engine.record_spend(member.member_id, 5000)  # Platinum
        now = datetime.now(timezone.utc)
        incentives = engine.generate_renewal_incentives(member.member_id, now + timedelta(days=30))
        assert len(incentives) >= 1

    def test_claim_reward(self):
        engine = LoyaltyEngine()
        member = engine.enroll("lic1")
        rewards = engine.update_tenure(member.member_id, 3)
        assert len(rewards) >= 1
        engine.claim_reward(rewards[0].reward_id)
        assert rewards[0].claimed is True

    def test_spend_to_next_tier(self):
        engine = LoyaltyEngine()
        member = engine.enroll("lic1")
        assert member.spend_to_next_tier == TIER_THRESHOLDS[LoyaltyTier.SILVER]

    def test_diamond_no_next_tier(self):
        engine = LoyaltyEngine()
        member = engine.enroll("lic1")
        engine.record_spend(member.member_id, 20000)
        assert member.tier == LoyaltyTier.DIAMOND
        assert member.next_tier is None

    def test_duplicate_enroll_returns_existing(self):
        engine = LoyaltyEngine()
        m1 = engine.enroll("lic1")
        m2 = engine.enroll("lic1")
        assert m1.member_id == m2.member_id


# ── Churn Prevention (330, 332, 340, 356, 360, 364) ──

class TestChurnPrevention:
    def test_assess_low_risk(self):
        engine = ChurnPreventionEngine()
        assessment = engine.assess_churn_risk(
            "lic1", usage_trend=0.1, days_since_last_login=2,
            support_tickets_30d=0, feature_adoption_pct=0.8,
            payment_failures_90d=0,
        )
        assert assessment.risk_level == ChurnRisk.LOW

    def test_assess_high_risk(self):
        engine = ChurnPreventionEngine()
        assessment = engine.assess_churn_risk(
            "lic1", usage_trend=-0.5, days_since_last_login=45,
            support_tickets_30d=5, feature_adoption_pct=0.1,
            payment_failures_90d=2,
        )
        assert assessment.risk_level in (ChurnRisk.HIGH, ChurnRisk.CRITICAL)

    def test_churn_to_upsell(self):
        """Item 330: predictive churn-to-upsell."""
        engine = ChurnPreventionEngine()
        assessment = engine.assess_churn_risk(
            "lic1", usage_trend=0.5, days_since_last_login=1,
            support_tickets_30d=0, feature_adoption_pct=0.9,
            payment_failures_90d=0,
        )
        assert assessment.upsell_opportunity is True

    def test_usage_decline_alert(self):
        """Item 332: early warning for declining usage."""
        engine = ChurnPreventionEngine()
        alert = engine.check_usage_decline("lic1", "ai_credits", 500, 1000)
        assert alert is not None
        assert alert.decline_pct == 50.0
        assert alert.severity == "critical"

    def test_no_alert_slight_decline(self):
        engine = ChurnPreventionEngine()
        alert = engine.check_usage_decline("lic1", "ai_credits", 950, 1000)
        assert alert is None  # <10% decline

    def test_pause_subscription(self):
        """Item 340: subscription pause."""
        engine = ChurnPreventionEngine()
        pause = engine.pause_subscription("lic1", "vacation", pause_days=30)
        assert pause.status == "active"
        assert len(pause.features_during_pause) > 0

    def test_resume_subscription(self):
        engine = ChurnPreventionEngine()
        pause = engine.pause_subscription("lic1", "vacation")
        engine.resume_subscription(pause.pause_id)
        assert pause.status == "resumed"

    def test_card_update_reminder(self):
        """Item 356: involuntary churn prevention."""
        engine = ChurnPreventionEngine()
        reminder = engine.create_card_reminder("lic1", "4242", 12, 2026)
        assert reminder.reminder_id.startswith("CRD-")
        engine.mark_card_updated(reminder.reminder_id)
        assert reminder.updated is True

    def test_win_back_campaign(self):
        """Item 360: multi-channel win-back."""
        engine = ChurnPreventionEngine()
        campaign = engine.create_win_back_campaign(
            "lic1",
            channels=[WinBackChannel.EMAIL, WinBackChannel.IN_APP, WinBackChannel.SMS],
            offer_type="discount", offer_value=30,
        )
        assert len(campaign.channels) == 3
        engine.convert_win_back(campaign.campaign_id)
        assert campaign.status == "converted"

    def test_grace_period(self):
        """Item 364: grace period with limited access."""
        engine = ChurnPreventionEngine()
        grace = engine.create_grace_period("lic1", access_level="limited")
        assert grace.is_active is True
        assert grace.days_remaining > 0
        assert grace.access_level == "limited"

    def test_convert_grace_period(self):
        engine = ChurnPreventionEngine()
        grace = engine.create_grace_period("lic1")
        engine.convert_grace_period(grace.grace_id)
        assert grace.converted is True

    def test_recommended_actions(self):
        engine = ChurnPreventionEngine()
        assessment = engine.assess_churn_risk(
            "lic1", usage_trend=-0.4, days_since_last_login=20,
            support_tickets_30d=4, feature_adoption_pct=0.2,
            payment_failures_90d=1,
        )
        assert len(assessment.recommended_actions) > 0
