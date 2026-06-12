"""Tests for analytics module: funnels, cohorts, revenue."""

import pytest
from datetime import datetime, timedelta, timezone

from vinzy_engine.analytics.funnels import (
    ConversionFunnelTracker, PaymentAnalyticsEngine,
)
from vinzy_engine.analytics.cohorts import CohortAnalysisEngine
from vinzy_engine.analytics.revenue import RevenueAnalyticsEngine


# ── Conversion Funnels (472, 448) ──

class TestConversionFunnels:
    def test_create_funnel(self):
        tracker = ConversionFunnelTracker()
        stages = tracker.create_funnel("main")
        assert len(stages) > 0
        assert stages[0].name == "visit"

    def test_custom_funnel(self):
        tracker = ConversionFunnelTracker()
        stages = tracker.create_funnel("custom", ["step1", "step2", "step3"])
        assert len(stages) == 3

    def test_record_and_analyze(self):
        tracker = ConversionFunnelTracker()
        tracker.create_funnel("main")
        now = datetime.now(timezone.utc)

        # Simulate funnel progression
        for i in range(100):
            tracker.record_event("main", f"lic{i}", "visit", "entered")
            tracker.record_event("main", f"lic{i}", "visit", "completed")
        for i in range(70):
            tracker.record_event("main", f"lic{i}", "signup", "entered")
            tracker.record_event("main", f"lic{i}", "signup", "completed")
        for i in range(30):
            tracker.record_event("main", f"lic{i}", "signup", "dropped")

        analysis = tracker.analyze_funnel("main", now - timedelta(hours=1), now + timedelta(hours=1))
        assert analysis.total_entered == 100
        assert analysis.overall_conversion_rate >= 0

    def test_unknown_funnel_raises(self):
        tracker = ConversionFunnelTracker()
        with pytest.raises(ValueError, match="Unknown funnel"):
            tracker.record_event("nope", "lic1", "visit", "entered")

    def test_get_events(self):
        tracker = ConversionFunnelTracker()
        tracker.create_funnel("f1")
        tracker.record_event("f1", "lic1", "visit", "entered")
        tracker.record_event("f1", "lic2", "visit", "entered")
        assert len(tracker.get_events(funnel_id="f1")) == 2
        assert len(tracker.get_events(license_id="lic1")) == 1


class TestPaymentAnalytics:
    """Item 448: payment analytics for conversion optimization."""

    def test_record_and_analyze(self):
        engine = PaymentAnalyticsEngine()
        now = datetime.now(timezone.utc)

        engine.record_attempt("lic1", 99, "credit_card", True, checkout_time_seconds=30)
        engine.record_attempt("lic2", 99, "credit_card", True, checkout_time_seconds=45)
        engine.record_attempt("lic3", 99, "paypal", False, failure_reason="declined")
        engine.record_attempt("lic4", 99, "credit_card", False, failure_reason="insufficient_funds")

        metrics = engine.analyze(now - timedelta(hours=1), now + timedelta(hours=1))
        assert metrics.total_attempts == 4
        assert metrics.successful == 2
        assert metrics.success_rate == 50.0
        assert "credit_card" in metrics.conversion_by_method

    def test_failure_reasons(self):
        engine = PaymentAnalyticsEngine()
        now = datetime.now(timezone.utc)
        engine.record_attempt("lic1", 99, "cc", False, failure_reason="declined")
        engine.record_attempt("lic2", 99, "cc", False, failure_reason="declined")
        engine.record_attempt("lic3", 99, "cc", False, failure_reason="expired")
        metrics = engine.analyze(now - timedelta(hours=1), now + timedelta(hours=1))
        assert metrics.top_failure_reasons[0] == ("declined", 2)


# ── Cohort Analysis (480) ──

class TestCohortAnalysis:
    def test_add_member(self):
        engine = CohortAnalysisEngine()
        member = engine.add_member("lic1", datetime(2026, 1, 15, tzinfo=timezone.utc), "pro")
        assert member.cohort_key == "2026-01"

    def test_analyze_cohort(self):
        engine = CohortAnalysisEngine()
        for i in range(10):
            m = engine.add_member(f"lic{i}", datetime(2026, 1, 1, tzinfo=timezone.utc), "pro")
            engine.record_activity(f"lic{i}", "2026-01", revenue=99)
        for i in range(7):
            engine.record_activity(f"lic{i}", "2026-02", revenue=99)
        for i in range(5):
            engine.record_activity(f"lic{i}", "2026-03", revenue=99)

        metrics = engine.analyze_cohort("2026-01", months_to_analyze=3)
        assert metrics.size == 10
        assert metrics.retention_by_month[0] == 100.0  # Month 0: all active
        assert metrics.retention_by_month[1] == 70.0   # Month 1
        assert metrics.retention_by_month[2] == 50.0   # Month 2

    def test_churn_tracking(self):
        engine = CohortAnalysisEngine()
        engine.add_member("lic1", datetime(2026, 1, 1, tzinfo=timezone.utc), "pro")
        engine.record_activity("lic1", "2026-01", revenue=99)
        engine.record_churn("lic1", "2026-02")
        metrics = engine.analyze_cohort("2026-01")
        assert metrics.churn_rate == 100.0

    def test_retention_matrix(self):
        engine = CohortAnalysisEngine()
        # Two cohorts
        for i in range(5):
            engine.add_member(f"jan{i}", datetime(2026, 1, 1, tzinfo=timezone.utc), "pro")
            engine.record_activity(f"jan{i}", "2026-01", revenue=99)
        for i in range(3):
            engine.add_member(f"feb{i}", datetime(2026, 2, 1, tzinfo=timezone.utc), "pro")
            engine.record_activity(f"feb{i}", "2026-02", revenue=99)

        matrix = engine.generate_retention_matrix(months=3)
        assert len(matrix.cohorts) == 2
        assert matrix.best_cohort != ""

    def test_ltv_estimate(self):
        engine = CohortAnalysisEngine()
        for i in range(10):
            engine.add_member(f"lic{i}", datetime(2026, 1, 1, tzinfo=timezone.utc), "pro")
            for m in ["2026-01", "2026-02", "2026-03"]:
                engine.record_activity(f"lic{i}", m, revenue=99)
        metrics = engine.analyze_cohort("2026-01")
        assert metrics.ltv_estimate > 0
        assert metrics.avg_revenue_per_user > 0


# ── Revenue Analytics (456, 462, 488, 494, 499) ──

class TestRevenueAnalytics:
    def test_record_revenue(self):
        engine = RevenueAnalyticsEngine()
        entry = engine.record_revenue("lic1", 99, period="2026-03")
        assert entry.amount == 99
        assert entry.period == "2026-03"

    def test_mrr_calculation(self):
        """Item 499: MRR/ARR metrics."""
        engine = RevenueAnalyticsEngine()
        engine.record_revenue("lic1", 99, period="2026-03")
        engine.record_revenue("lic2", 349, period="2026-03")
        engine.record_subscription_event("lic1", "new", 99, "2026-03")
        engine.record_subscription_event("lic2", "new", 349, "2026-03")

        mrr = engine.calculate_mrr("2026-03")
        assert mrr.total_mrr == 448
        assert mrr.new_mrr == 448
        assert mrr.arr == 448 * 12

    def test_subscription_metrics(self):
        """Item 462: subscription lifecycle analytics."""
        engine = RevenueAnalyticsEngine()
        now = datetime.now(timezone.utc)
        engine.record_revenue("lic1", 99, period="2026-03")
        engine.record_subscription_event("lic1", "new", 99, "2026-03")
        engine.record_subscription_event("lic2", "cancel", -99, "2026-03")

        metrics = engine.calculate_subscription_metrics(
            "2026-03", now - timedelta(days=30), now, active_count=10, total_count=12,
        )
        assert metrics.new_subscriptions == 1
        assert metrics.churned_subscriptions == 1
        assert metrics.gross_churn_rate > 0

    def test_revenue_forecast(self):
        """Item 488: revenue forecasting."""
        engine = RevenueAnalyticsEngine()
        engine.record_revenue("lic1", 10000, period="2026-01")
        engine.record_revenue("lic1", 11000, period="2026-02")
        engine.record_revenue("lic1", 12000, period="2026-03")

        forecasts = engine.forecast_revenue(months_ahead=3, growth_assumption=0.05)
        assert len(forecasts) == 3
        assert forecasts[0].predicted_mrr > 0
        assert forecasts[0].confidence_low < forecasts[0].predicted_mrr

    def test_cac_calculation(self):
        """Item 494: customer acquisition cost."""
        engine = RevenueAnalyticsEngine()
        engine.record_marketing_spend("google_ads", 5000, "2026-03", new_customers=50)
        engine.record_marketing_spend("organic", 1000, "2026-03", new_customers=100)

        cac = engine.calculate_cac("2026-03", avg_ltv=1200)
        assert cac.total_spend == 6000
        assert cac.new_customers == 150
        assert cac.cac == 40.0  # 6000/150
        assert cac.ltv_to_cac_ratio > 0
        assert "google_ads" in cac.by_channel

    def test_revenue_by_period(self):
        engine = RevenueAnalyticsEngine()
        engine.record_revenue("lic1", 100, period="2026-01")
        engine.record_revenue("lic2", 200, period="2026-02")
        engine.record_revenue("lic3", 150, period="2026-02")
        by_period = engine.get_revenue_by_period()
        assert by_period["2026-01"] == 100
        assert by_period["2026-02"] == 350

    def test_revenue_by_type(self):
        engine = RevenueAnalyticsEngine()
        engine.record_revenue("lic1", 99, type="subscription", period="2026-03")
        engine.record_revenue("lic1", 15, type="overage", period="2026-03")
        by_type = engine.get_revenue_by_type("2026-03")
        assert by_type["subscription"] == 99
        assert by_type["overage"] == 15

    def test_net_churn_with_expansion(self):
        engine = RevenueAnalyticsEngine()
        now = datetime.now(timezone.utc)
        engine.record_subscription_event("lic1", "cancel", -99, "2026-03")
        engine.record_subscription_event("lic2", "upgrade", 250, "2026-03")
        engine.record_revenue("lic3", 99, period="2026-03")

        metrics = engine.calculate_subscription_metrics(
            "2026-03", now - timedelta(days=30), now, active_count=20, total_count=21,
        )
        # 1 cancel - 1 upgrade = 0 net churn
        assert metrics.net_churn_rate == 0
