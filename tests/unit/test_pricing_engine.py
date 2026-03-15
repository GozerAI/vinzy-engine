"""Tests for pricing engine, overage, rate limits, enterprise calc, metering, credits, commitments, promotions, migration, settlement."""

import pytest
from datetime import datetime, timedelta, timezone

from vinzy_engine.pricing.engine import (
    BillingCycle, BundleDefinition, CurrencyConfig, LineItem,
    PricingModel, PricingPlan, PricingResult, PricingTier,
    UsageBasedPricingEngine, SUPPORTED_CURRENCIES,
)
from vinzy_engine.pricing.overage import (
    OverageBillingEngine, OveragePolicy, OverageEvent,
)
from vinzy_engine.pricing.rate_limits import (
    TieredRateLimiter, RateLimitConfig, TIER_RATE_LIMITS,
)
from vinzy_engine.pricing.enterprise_calc import (
    EnterprisePricingCalculator, EnterpriseQuoteRequest,
)
from vinzy_engine.pricing.metering import (
    FeatureUsageMeter, MeterDefinition, MeterType, AggregationMethod,
)
from vinzy_engine.pricing.credits import (
    PrepaidCreditEngine, CreditPackage, DEFAULT_PACKAGES,
)
from vinzy_engine.pricing.commitments import (
    CommitmentEngine, CommitmentType, CommitmentStatus,
)
from vinzy_engine.pricing.promotions import (
    PromotionEngine, Promotion, DiscountType, PromoStatus, EligibilityRule,
)
from vinzy_engine.pricing.migration import (
    TierMigrationTracker, MigrationDirection,
)
from vinzy_engine.pricing.settlement import MultiCurrencySettlement


# ── Usage-Based Pricing Engine (251) ──

class TestUsageBasedPricingEngine:
    def test_flat_plan(self):
        engine = UsageBasedPricingEngine()
        plan = PricingPlan(plan_id="flat", name="Flat", model=PricingModel.FLAT, base_price=99)
        engine.register_plan(plan)
        result = engine.calculate_price("flat", units_consumed=100)
        assert result.total == 99.0
        assert result.plan_id == "flat"

    def test_usage_based_with_overage(self):
        engine = UsageBasedPricingEngine()
        plan = PricingPlan(
            plan_id="usage", name="Usage", model=PricingModel.USAGE_BASED,
            base_price=49, included_units=100, overage_price=0.10,
        )
        engine.register_plan(plan)
        result = engine.calculate_price("usage", units_consumed=150)
        # base + 50 overage * 0.10
        assert result.total == 54.0

    def test_usage_no_overage(self):
        engine = UsageBasedPricingEngine()
        plan = PricingPlan(
            plan_id="usage", name="Usage", model=PricingModel.USAGE_BASED,
            base_price=49, included_units=100, overage_price=0.10,
        )
        engine.register_plan(plan)
        result = engine.calculate_price("usage", units_consumed=50)
        assert result.total == 49.0

    def test_graduated_pricing(self):
        """Item 275: graduated pricing."""
        engine = UsageBasedPricingEngine()
        plan = PricingPlan(
            plan_id="graduated", name="Graduated", model=PricingModel.GRADUATED,
            base_price=0, tiers=[
                PricingTier(min_units=1, max_units=100, unit_price=0.10),
                PricingTier(min_units=101, max_units=500, unit_price=0.08),
                PricingTier(min_units=501, max_units=None, unit_price=0.05),
            ],
        )
        engine.register_plan(plan)
        result = engine.calculate_price("graduated", units_consumed=250)
        # First 100 @ 0.10 = 10.0, next 150 @ 0.08 = 12.0
        assert len(result.line_items) >= 2
        assert result.total > 0

    def test_volume_pricing(self):
        """Item 257: volume discount tiers."""
        engine = UsageBasedPricingEngine()
        plan = PricingPlan(
            plan_id="volume", name="Volume", model=PricingModel.VOLUME,
            base_price=0, tiers=[
                PricingTier(min_units=1, max_units=99, unit_price=0.10),
                PricingTier(min_units=100, max_units=499, unit_price=0.08),
                PricingTier(min_units=500, max_units=None, unit_price=0.05),
            ],
        )
        engine.register_plan(plan)
        # 250 units: all at 0.08 (volume tier)
        result = engine.calculate_price("volume", units_consumed=250)
        assert result.total == 20.0  # 250 * 0.08

    def test_tiered_pricing(self):
        engine = UsageBasedPricingEngine()
        plan = PricingPlan(
            plan_id="tiered", name="Tiered", model=PricingModel.TIERED,
            base_price=0, tiers=[
                PricingTier(min_units=1, max_units=100, unit_price=0.10),
                PricingTier(min_units=101, max_units=500, unit_price=0.08),
            ],
        )
        engine.register_plan(plan)
        result = engine.calculate_price("tiered", units_consumed=50)
        assert result.total == 5.0

    def test_annual_billing_discount(self):
        """Item 260: annual billing discount."""
        engine = UsageBasedPricingEngine()
        plan = PricingPlan(
            plan_id="annual", name="Annual", model=PricingModel.FLAT,
            base_price=99, annual_discount_pct=16.67,
        )
        engine.register_plan(plan)
        result = engine.calculate_price("annual", billing_cycle=BillingCycle.ANNUAL)
        # 99 * (1-0.1667) * 12 ≈ 989.64
        assert result.total < 99 * 12
        assert result.billing_cycle == BillingCycle.ANNUAL

    def test_quarterly_billing_discount(self):
        engine = UsageBasedPricingEngine()
        plan = PricingPlan(
            plan_id="q", name="Q", model=PricingModel.FLAT,
            base_price=99, quarterly_discount_pct=10.0,
        )
        engine.register_plan(plan)
        result = engine.calculate_price("q", billing_cycle=BillingCycle.QUARTERLY)
        assert result.total < 99 * 3

    def test_currency_conversion(self):
        """Item 278: currency-specific pricing."""
        engine = UsageBasedPricingEngine()
        plan = PricingPlan(plan_id="flat", name="Flat", model=PricingModel.FLAT, base_price=100)
        engine.register_plan(plan)
        result = engine.calculate_price("flat", currency="EUR")
        assert result.currency == "EUR"
        assert result.total < 100  # EUR is less than USD

    def test_jpy_no_decimals(self):
        engine = UsageBasedPricingEngine()
        plan = PricingPlan(plan_id="flat", name="Flat", model=PricingModel.FLAT, base_price=100)
        engine.register_plan(plan)
        result = engine.calculate_price("flat", currency="JPY")
        assert result.currency == "JPY"
        assert result.total == int(result.total)  # No decimals for JPY

    def test_bundle_pricing(self):
        """Item 281: bundle pricing."""
        engine = UsageBasedPricingEngine()
        bundle = BundleDefinition(
            bundle_id="dev", name="Dev Bundle",
            product_ids=["SC", "CS", "GO"],
            discount_pct=20, base_price_usd=79,
        )
        engine.register_bundle(bundle)
        result = engine.calculate_bundle_price("dev")
        assert result.total == 79.0

    def test_bundle_annual(self):
        engine = UsageBasedPricingEngine()
        bundle = BundleDefinition(
            bundle_id="dev", name="Dev Bundle",
            product_ids=["SC", "CS", "GO"],
            discount_pct=20, base_price_usd=79,
        )
        engine.register_bundle(bundle)
        result = engine.calculate_bundle_price("dev", BillingCycle.ANNUAL)
        assert result.total < 79 * 12

    def test_unknown_plan_raises(self):
        engine = UsageBasedPricingEngine()
        with pytest.raises(ValueError, match="Unknown plan"):
            engine.calculate_price("nonexistent")

    def test_unknown_currency_raises(self):
        engine = UsageBasedPricingEngine()
        plan = PricingPlan(plan_id="flat", name="Flat", model=PricingModel.FLAT, base_price=100)
        engine.register_plan(plan)
        with pytest.raises(ValueError, match="Unsupported currency"):
            engine.calculate_price("flat", currency="XYZ")

    def test_currency_conversion_between(self):
        engine = UsageBasedPricingEngine()
        converted = engine.convert_currency(100, "USD", "EUR")
        assert converted < 100

    def test_list_plans_and_bundles(self):
        engine = UsageBasedPricingEngine()
        engine.register_plan(PricingPlan(plan_id="a", name="A", model=PricingModel.FLAT, base_price=10))
        engine.register_bundle(BundleDefinition(bundle_id="b", name="B", product_ids=[], discount_pct=0, base_price_usd=10))
        assert len(engine.list_plans()) == 1
        assert len(engine.list_bundles()) == 1

    def test_per_unit_pricing(self):
        engine = UsageBasedPricingEngine()
        plan = PricingPlan(
            plan_id="pu", name="Per Unit", model=PricingModel.PER_UNIT,
            base_price=0, overage_price=0.05,
        )
        engine.register_plan(plan)
        result = engine.calculate_price("pu", units_consumed=200)
        assert result.total == 10.0


# ── Overage Billing (254) ──

class TestOverageBilling:
    def test_no_overage_within_limit(self):
        engine = OverageBillingEngine()
        event = engine.check_overage("lic1", "pro", "ai_credits", 3000, 100)
        assert event is None

    def test_overage_detected(self):
        engine = OverageBillingEngine()
        event = engine.check_overage("lic1", "pro", "ai_credits", 4900, 200)
        assert event is not None
        assert event.overage_units == 100

    def test_overage_charge_calculation(self):
        engine = OverageBillingEngine()
        event = engine.check_overage("lic1", "pro", "ai_credits", 5500, 0)
        assert event is not None
        assert event.overage_charge == round(500 * 0.018, 2)

    def test_hard_cap_blocks(self):
        engine = OverageBillingEngine(default_policy=OveragePolicy.HARD_CAP)
        event = engine.check_overage("lic1", "pro", "ai_credits", 5100, 0)
        assert event is not None
        assert engine.should_block(event) is True

    def test_soft_cap_allows(self):
        engine = OverageBillingEngine(default_policy=OveragePolicy.SOFT_CAP)
        event = engine.check_overage("lic1", "pro", "ai_credits", 5100, 0)
        assert event is not None
        assert engine.should_block(event) is False

    def test_policy_per_metric(self):
        engine = OverageBillingEngine()
        engine.set_policy("ai_credits", OveragePolicy.HARD_CAP)
        assert engine.get_policy("ai_credits") == OveragePolicy.HARD_CAP
        assert engine.get_policy("other") == OveragePolicy.SOFT_CAP

    def test_invoice_generation(self):
        engine = OverageBillingEngine()
        now = datetime.now(timezone.utc)
        engine.check_overage("lic1", "pro", "ai_credits", 5500, 0)
        engine.check_overage("lic1", "pro", "ai_credits", 6000, 0)
        invoice = engine.generate_invoice(
            "lic1", "tenant1",
            now - timedelta(hours=1), now + timedelta(hours=1),
        )
        assert invoice.event_count == 2
        assert invoice.subtotal > 0

    def test_unlimited_no_overage(self):
        engine = OverageBillingEngine()
        # scale tier has 0 machine_activations (unlimited)
        event = engine.check_overage("lic1", "scale", "machine_activations", 999, 0)
        assert event is None

    def test_get_events(self):
        engine = OverageBillingEngine()
        engine.check_overage("lic1", "pro", "ai_credits", 5500, 0)
        engine.check_overage("lic2", "pro", "ai_credits", 5500, 0)
        assert len(engine.get_events()) == 2
        assert len(engine.get_events("lic1")) == 1

    def test_clear_events(self):
        engine = OverageBillingEngine()
        engine.check_overage("lic1", "pro", "ai_credits", 5500, 0)
        engine.clear_events()
        assert len(engine.get_events()) == 0


# ── Tiered Rate Limits (263) ──

class TestTieredRateLimits:
    def test_community_limits(self):
        limiter = TieredRateLimiter()
        config = limiter.get_limits("community")
        assert config.requests_per_minute == 10

    def test_scale_limits(self):
        limiter = TieredRateLimiter()
        config = limiter.get_limits("scale")
        assert config.requests_per_minute == 1000

    def test_rate_limit_allowed(self):
        limiter = TieredRateLimiter()
        result = limiter.check_rate_limit("lic1", "pro")
        assert result.allowed is True
        assert result.remaining >= 0

    def test_rate_limit_exhaustion(self):
        limiter = TieredRateLimiter()
        # Community: 10 rpm
        for _ in range(10):
            limiter.check_rate_limit("lic1", "community")
        result = limiter.check_rate_limit("lic1", "community")
        assert result.allowed is False
        assert result.retry_after_ms > 0

    def test_burst_limit(self):
        limiter = TieredRateLimiter()
        result = limiter.check_burst("lic1", "pro")
        assert result.allowed is True

    def test_reset(self):
        limiter = TieredRateLimiter()
        limiter.check_rate_limit("lic1", "community")
        limiter.reset("lic1")
        result = limiter.check_rate_limit("lic1", "community")
        assert result.allowed is True

    def test_backward_compat(self):
        limiter = TieredRateLimiter()
        assert limiter.get_limits("business") == limiter.get_limits("growth")
        assert limiter.get_limits("enterprise") == limiter.get_limits("scale")


# ── Enterprise Pricing Calculator (266) ──

class TestEnterprisePricingCalculator:
    def test_basic_quote(self):
        calc = EnterprisePricingCalculator()
        request = EnterpriseQuoteRequest(
            company_name="Acme Corp",
            estimated_users=50,
            estimated_monthly_usage=10000,
            products=["AGW", "NXS"],
            commitment_months=12,
        )
        quote = calc.calculate(request)
        assert quote.quote_id.startswith("ENT-Q-")
        assert quote.total_monthly > 0
        assert quote.total_annual > 0
        assert len(quote.lines) >= 2

    def test_volume_discount(self):
        calc = EnterprisePricingCalculator()
        small = EnterpriseQuoteRequest(
            company_name="Small", estimated_users=5,
            estimated_monthly_usage=0, products=["AGW"],
        )
        large = EnterpriseQuoteRequest(
            company_name="Large", estimated_users=500,
            estimated_monthly_usage=0, products=["AGW"],
        )
        q_small = calc.calculate(small)
        q_large = calc.calculate(large)
        # Per-user cost should be lower for large
        per_user_small = q_small.total_monthly / 5
        per_user_large = q_large.total_monthly / 500
        assert per_user_large < per_user_small

    def test_commitment_discount(self):
        calc = EnterprisePricingCalculator()
        short = EnterpriseQuoteRequest(
            company_name="Short", estimated_users=50,
            estimated_monthly_usage=0, products=["AGW"],
            commitment_months=1,
        )
        long = EnterpriseQuoteRequest(
            company_name="Long", estimated_users=50,
            estimated_monthly_usage=0, products=["AGW"],
            commitment_months=36,
        )
        q_short = calc.calculate(short)
        q_long = calc.calculate(long)
        assert q_long.total_monthly < q_short.total_monthly

    def test_support_pricing(self):
        calc = EnterprisePricingCalculator()
        req = EnterpriseQuoteRequest(
            company_name="Premium", estimated_users=10,
            estimated_monthly_usage=0, products=["AGW"],
            support_level="premium",
        )
        quote = calc.calculate(req)
        support_lines = [l for l in quote.lines if "Support" in l.description]
        assert len(support_lines) == 1

    def test_sla_surcharge(self):
        calc = EnterprisePricingCalculator()
        req = EnterpriseQuoteRequest(
            company_name="Mission", estimated_users=10,
            estimated_monthly_usage=0, products=["AGW"],
            sla_tier="mission_critical",
        )
        quote = calc.calculate(req)
        sla_lines = [l for l in quote.lines if "SLA" in l.description]
        assert len(sla_lines) == 1

    def test_prepaid_discount(self):
        calc = EnterprisePricingCalculator()
        req = EnterpriseQuoteRequest(
            company_name="Prepaid", estimated_users=10,
            estimated_monthly_usage=0, products=["AGW"],
            payment_terms="prepaid",
        )
        quote = calc.calculate(req)
        assert "prepaid" in quote.notes[0].lower() or any("prepaid" in n.lower() for n in quote.notes)


# ── Feature Usage Metering (269) ──

class TestFeatureUsageMetering:
    def test_define_and_record(self):
        meter = FeatureUsageMeter()
        meter.define_meter(MeterDefinition(
            meter_id="api_calls", feature="API Calls",
            meter_type=MeterType.COUNTER, rate_per_unit=0.001,
        ))
        reading = meter.record("api_calls", "lic1", 5.0)
        assert reading.meter_id == "api_calls"
        assert reading.value == 5.0

    def test_aggregate_sum(self):
        meter = FeatureUsageMeter()
        now = datetime.now(timezone.utc)
        meter.define_meter(MeterDefinition(
            meter_id="calls", feature="Calls",
            meter_type=MeterType.COUNTER,
            rate_per_unit=0.01, included_free=10,
        ))
        meter.record("calls", "lic1", 8)
        meter.record("calls", "lic1", 7)
        summary = meter.aggregate("calls", "lic1", now - timedelta(hours=1), now + timedelta(hours=1))
        assert summary.total_value == 15
        assert summary.billable_value == 5  # 15 - 10 free
        assert summary.estimated_charge == 0.05

    def test_aggregate_max(self):
        meter = FeatureUsageMeter()
        now = datetime.now(timezone.utc)
        meter.define_meter(MeterDefinition(
            meter_id="seats", feature="Seats",
            meter_type=MeterType.GAUGE,
            aggregation=AggregationMethod.MAX,
        ))
        meter.record("seats", "lic1", 3)
        meter.record("seats", "lic1", 7)
        meter.record("seats", "lic1", 5)
        summary = meter.aggregate("seats", "lic1", now - timedelta(hours=1), now + timedelta(hours=1))
        assert summary.total_value == 7

    def test_unknown_meter_raises(self):
        meter = FeatureUsageMeter()
        with pytest.raises(ValueError, match="Unknown meter"):
            meter.record("nonexistent", "lic1", 1)

    def test_estimate_charges(self):
        meter = FeatureUsageMeter()
        now = datetime.now(timezone.utc)
        meter.define_meter(MeterDefinition(
            meter_id="a", feature="A", meter_type=MeterType.COUNTER,
            rate_per_unit=0.01, included_free=0,
        ))
        meter.define_meter(MeterDefinition(
            meter_id="b", feature="B", meter_type=MeterType.COUNTER,
            rate_per_unit=0.02, included_free=0,
        ))
        meter.record("a", "lic1", 100)
        meter.record("b", "lic1", 50)
        total = meter.estimate_charges("lic1", now - timedelta(hours=1), now + timedelta(hours=1))
        assert total == 2.0  # 100*0.01 + 50*0.02

    def test_list_meters(self):
        meter = FeatureUsageMeter()
        meter.define_meter(MeterDefinition(meter_id="a", feature="A", meter_type=MeterType.COUNTER))
        meter.define_meter(MeterDefinition(meter_id="b", feature="B", meter_type=MeterType.GAUGE))
        assert len(meter.list_meters()) == 2


# ── Prepaid Credits (272) ──

class TestPrepaidCredits:
    def test_purchase_package(self):
        engine = PrepaidCreditEngine()
        tx = engine.purchase("lic1", "credits_2000")
        assert tx.amount == 2000
        balance = engine.get_balance("lic1")
        assert balance.purchased_credits == 2000
        assert balance.bonus_credits == 200  # Growth Pack bonus

    def test_consume_credits(self):
        engine = PrepaidCreditEngine()
        engine.purchase("lic1", "credits_500")
        tx = engine.consume("lic1", 100)
        assert tx.amount == -100
        balance = engine.get_balance("lic1")
        assert balance.available == 400

    def test_insufficient_credits(self):
        engine = PrepaidCreditEngine()
        engine.purchase("lic1", "credits_500")
        with pytest.raises(ValueError, match="Insufficient"):
            engine.consume("lic1", 600)

    def test_reserve_and_release(self):
        engine = PrepaidCreditEngine()
        engine.purchase("lic1", "credits_500")
        assert engine.reserve("lic1", 200) is True
        balance = engine.get_balance("lic1")
        assert balance.available == 300
        engine.release_reservation("lic1", 200)
        assert engine.get_balance("lic1").available == 500

    def test_refund_credits(self):
        engine = PrepaidCreditEngine()
        engine.purchase("lic1", "credits_500")
        engine.consume("lic1", 200)
        engine.refund("lic1", 100, "service issue")
        assert engine.get_balance("lic1").available == 400

    def test_bonus_credits_included(self):
        engine = PrepaidCreditEngine()
        engine.purchase("lic1", "credits_10000")
        balance = engine.get_balance("lic1")
        assert balance.bonus_credits == 2000
        assert balance.total_credits == 12000

    def test_effective_cost(self):
        for pkg in DEFAULT_PACKAGES:
            if pkg.total_credits > 0:
                assert pkg.effective_cost_per_credit > 0
                assert pkg.effective_cost_per_credit < pkg.price_usd

    def test_transaction_history(self):
        engine = PrepaidCreditEngine()
        engine.purchase("lic1", "credits_500")
        engine.consume("lic1", 50)
        txs = engine.get_transactions("lic1")
        assert len(txs) == 2

    def test_unknown_package_raises(self):
        engine = PrepaidCreditEngine()
        with pytest.raises(ValueError, match="Unknown package"):
            engine.purchase("lic1", "nonexistent")


# ── Commitment Contracts (287) ──

class TestCommitmentContracts:
    def test_create_contract(self):
        engine = CommitmentEngine()
        contract = engine.create_contract(
            "lic1", "tenant1", CommitmentType.SPEND, 10000, 12,
        )
        assert contract.contract_id.startswith("CMT-")
        assert contract.minimum_value == 10000
        assert contract.fulfillment_pct == 0

    def test_record_value(self):
        engine = CommitmentEngine()
        contract = engine.create_contract("lic1", None, CommitmentType.SPEND, 1000, 12)
        engine.record_value(contract.contract_id, 500)
        assert contract.actual_value == 500
        assert contract.fulfillment_pct == 50.0

    def test_fulfilled_contract(self):
        engine = CommitmentEngine()
        contract = engine.create_contract("lic1", None, CommitmentType.USAGE, 100, 12)
        engine.record_value(contract.contract_id, 100)
        assert contract.is_fulfilled is True
        assert contract.shortfall == 0

    def test_true_up_invoice(self):
        engine = CommitmentEngine()
        now = datetime.now(timezone.utc)
        contract = engine.create_contract(
            "lic1", None, CommitmentType.SPEND, 1000, 1,
            start_date=now - timedelta(days=60),
        )
        engine.record_value(contract.contract_id, 700)
        invoice = engine.generate_true_up(contract.contract_id)
        assert invoice is not None
        assert invoice.shortfall == 300
        assert invoice.amount == 300

    def test_cancel_contract(self):
        engine = CommitmentEngine()
        contract = engine.create_contract("lic1", None, CommitmentType.SPEND, 1000, 12)
        engine.cancel_contract(contract.contract_id)
        assert contract.status == CommitmentStatus.CANCELLED


# ── Promotions (309) ──

class TestPromotions:
    def test_create_promotion(self):
        engine = PromotionEngine()
        now = datetime.now(timezone.utc)
        promo = Promotion(
            promo_id="promo1", name="Summer Sale", description="20% off",
            discount_type=DiscountType.PERCENTAGE, discount_value=20,
            start_date=now - timedelta(days=1), end_date=now + timedelta(days=30),
            promo_code="SUMMER20",
        )
        engine.create_promotion(promo)
        assert promo.is_active is True

    def test_apply_percentage_discount(self):
        engine = PromotionEngine()
        now = datetime.now(timezone.utc)
        promo = Promotion(
            promo_id="promo1", name="Sale", description="25% off",
            discount_type=DiscountType.PERCENTAGE, discount_value=25,
            start_date=now - timedelta(days=1), end_date=now + timedelta(days=30),
        )
        engine.create_promotion(promo)
        final, redemption = engine.apply_discount("promo1", 100.0, {})
        assert final == 75.0
        assert redemption is not None

    def test_apply_fixed_discount(self):
        engine = PromotionEngine()
        now = datetime.now(timezone.utc)
        promo = Promotion(
            promo_id="promo1", name="Sale", description="$10 off",
            discount_type=DiscountType.FIXED_AMOUNT, discount_value=10,
            start_date=now - timedelta(days=1), end_date=now + timedelta(days=30),
        )
        engine.create_promotion(promo)
        final, _ = engine.apply_discount("promo1", 50.0, {})
        assert final == 40.0

    def test_max_redemptions(self):
        engine = PromotionEngine()
        now = datetime.now(timezone.utc)
        promo = Promotion(
            promo_id="p", name="Limited", description="",
            discount_type=DiscountType.PERCENTAGE, discount_value=10,
            start_date=now - timedelta(days=1), end_date=now + timedelta(days=30),
            max_redemptions=2,
        )
        engine.create_promotion(promo)
        engine.apply_discount("p", 100, {})
        engine.apply_discount("p", 100, {})
        # Third should not apply
        final, redemption = engine.apply_discount("p", 100, {})
        assert final == 100.0  # No discount
        assert redemption is None

    def test_find_by_code(self):
        engine = PromotionEngine()
        now = datetime.now(timezone.utc)
        promo = Promotion(
            promo_id="p1", name="Code", description="",
            discount_type=DiscountType.PERCENTAGE, discount_value=10,
            start_date=now - timedelta(days=1), end_date=now + timedelta(days=30),
            promo_code="SAVE10",
        )
        engine.create_promotion(promo)
        found = engine.find_by_code("save10")
        assert found is not None
        assert found.promo_id == "p1"

    def test_eligibility_rule(self):
        engine = PromotionEngine()
        now = datetime.now(timezone.utc)
        promo = Promotion(
            promo_id="p", name="Pro Only", description="",
            discount_type=DiscountType.PERCENTAGE, discount_value=10,
            start_date=now - timedelta(days=1), end_date=now + timedelta(days=30),
            eligibility_rules=[EligibilityRule("tier", ["pro", "growth"])],
        )
        engine.create_promotion(promo)
        ok, _ = engine.check_eligibility("p", {"tier": "pro"})
        assert ok is True
        ok, _ = engine.check_eligibility("p", {"tier": "community"})
        assert ok is False

    def test_expired_promotion(self):
        engine = PromotionEngine()
        now = datetime.now(timezone.utc)
        promo = Promotion(
            promo_id="expired", name="Old", description="",
            discount_type=DiscountType.PERCENTAGE, discount_value=50,
            start_date=now - timedelta(days=30), end_date=now - timedelta(days=1),
        )
        engine.create_promotion(promo)
        assert promo.is_active is False

    def test_disable_promotion(self):
        engine = PromotionEngine()
        now = datetime.now(timezone.utc)
        promo = Promotion(
            promo_id="p", name="Active", description="",
            discount_type=DiscountType.PERCENTAGE, discount_value=10,
            start_date=now - timedelta(days=1), end_date=now + timedelta(days=30),
        )
        engine.create_promotion(promo)
        engine.disable_promotion("p")
        assert promo.status == PromoStatus.DISABLED


# ── Tier Migration Analytics (284) ──

class TestTierMigration:
    def test_record_upgrade(self):
        tracker = TierMigrationTracker()
        m = tracker.record_migration("lic1", None, "pro", "growth", 99, 349)
        assert m.direction == MigrationDirection.UPGRADE
        assert m.revenue_impact == 250

    def test_record_downgrade(self):
        tracker = TierMigrationTracker()
        m = tracker.record_migration("lic1", None, "growth", "pro", 349, 99)
        assert m.direction == MigrationDirection.DOWNGRADE
        assert m.revenue_impact == -250

    def test_analyze_migrations(self):
        tracker = TierMigrationTracker()
        now = datetime.now(timezone.utc)
        tracker.record_migration("lic1", None, "pro", "growth", 99, 349)
        tracker.record_migration("lic2", None, "community", "pro", 0, 99)
        tracker.record_migration("lic3", None, "growth", "pro", 349, 99)

        analytics = tracker.analyze(now - timedelta(hours=1), now + timedelta(hours=1))
        assert analytics.total_migrations == 3
        assert analytics.upgrades == 2
        assert analytics.downgrades == 1

    def test_filter_by_direction(self):
        tracker = TierMigrationTracker()
        tracker.record_migration("lic1", None, "pro", "growth", 99, 349)
        tracker.record_migration("lic2", None, "growth", "pro", 349, 99)
        ups = tracker.get_migrations(direction=MigrationDirection.UPGRADE)
        assert len(ups) == 1


# ── Multi-Currency Settlement (290) ──

class TestMultiCurrencySettlement:
    def test_create_settlement(self):
        engine = MultiCurrencySettlement()
        record = engine.create_settlement("lic1", "EUR", 100, "USD")
        assert record.settlement_currency == "USD"
        assert record.settlement_amount > 0
        assert record.exchange_rate > 0

    def test_fee_calculation(self):
        engine = MultiCurrencySettlement()
        fee = engine.calculate_fee(100, "EUR")
        assert fee == 0.50  # 0.5% fee

    def test_usd_no_fee(self):
        engine = MultiCurrencySettlement()
        fee = engine.calculate_fee(100, "USD")
        assert fee == 0.0

    def test_complete_settlement(self):
        engine = MultiCurrencySettlement()
        record = engine.create_settlement("lic1", "USD", 100)
        engine.complete_settlement(record.settlement_id)
        assert record.status == "completed"

    def test_rate_history(self):
        engine = MultiCurrencySettlement()
        engine.update_exchange_rate("USD", "EUR", 0.93, "api")
        history = engine.get_rate_history(from_currency="USD")
        assert len(history) == 1

    def test_get_settlements(self):
        engine = MultiCurrencySettlement()
        engine.create_settlement("lic1", "USD", 100)
        engine.create_settlement("lic2", "EUR", 50)
        assert len(engine.get_settlements()) == 2
        assert len(engine.get_settlements(license_id="lic1")) == 1
