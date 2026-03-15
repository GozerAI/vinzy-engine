"""Tests for billing module: prorated, revenue recognition, refunds, stripe connect, dunning, chargebacks."""

import pytest
from datetime import datetime, timedelta, timezone

from vinzy_engine.billing.prorated import ProratedBillingEngine
from vinzy_engine.billing.revenue_recognition import (
    RevenueRecognitionEngine, RecognitionMethod, RevenueStatus,
)
from vinzy_engine.billing.refunds import (
    RefundEngine, RefundReason, RefundStatus, ApprovalLevel, RefundPolicy,
)
from vinzy_engine.billing.stripe_connect import StripeConnectManager, PayoutStatus
from vinzy_engine.billing.dunning import (
    SmartDunningEngine, PaymentFailureType, DunningStage,
)
from vinzy_engine.billing.chargebacks import (
    ChargebackPreventionEngine, ChargebackRisk, ChargebackStatus, RiskSignal,
)


# ── Prorated Billing (441) ──

class TestProratedBilling:
    def test_upgrade_proration(self):
        engine = ProratedBillingEngine()
        now = datetime.now(timezone.utc)
        result = engine.calculate_proration(
            "lic1", "pro", "growth", 99, 349,
            now - timedelta(days=15), now + timedelta(days=15), now,
        )
        assert result.credit_amount > 0
        assert result.charge_amount > result.credit_amount
        assert result.net_amount > 0

    def test_downgrade_proration(self):
        engine = ProratedBillingEngine()
        now = datetime.now(timezone.utc)
        result = engine.calculate_proration(
            "lic1", "growth", "pro", 349, 99,
            now - timedelta(days=15), now + timedelta(days=15), now,
        )
        assert result.net_amount < 0  # Credit

    def test_mid_cycle_invoice(self):
        engine = ProratedBillingEngine()
        now = datetime.now(timezone.utc)
        invoice = engine.calculate_upgrade_invoice(
            "lic1", "pro", "growth", 99, 349,
            now - timedelta(days=10), now + timedelta(days=20),
        )
        assert invoice["type"] == "upgrade"
        assert invoice["immediate_charge"] > 0

    def test_same_price_zero_proration(self):
        engine = ProratedBillingEngine()
        now = datetime.now(timezone.utc)
        result = engine.calculate_proration(
            "lic1", "pro", "pro_v2", 99, 99,
            now - timedelta(days=15), now + timedelta(days=15), now,
        )
        assert result.net_amount == 0


# ── Revenue Recognition (443) ──

class TestRevenueRecognition:
    def test_create_schedule(self):
        engine = RevenueRecognitionEngine()
        now = datetime.now(timezone.utc)
        schedule = engine.create_schedule(
            "lic1", 1200, now, now + timedelta(days=365),
        )
        assert schedule.contract_amount == 1200
        assert schedule.deferred_amount == 1200
        assert schedule.status == RevenueStatus.DEFERRED

    def test_straight_line_entries(self):
        engine = RevenueRecognitionEngine()
        now = datetime.now(timezone.utc)
        schedule = engine.create_schedule(
            "lic1", 1200, now, now + timedelta(days=365),
        )
        entries = engine.generate_entries(schedule.schedule_id)
        assert len(entries) >= 11  # ~12 months
        total = sum(e.amount for e in entries)
        assert abs(total - 1200) < 0.02  # Rounding tolerance

    def test_point_in_time(self):
        engine = RevenueRecognitionEngine()
        now = datetime.now(timezone.utc)
        schedule = engine.create_schedule(
            "lic1", 500, now, now + timedelta(days=30),
            method=RecognitionMethod.POINT_IN_TIME,
        )
        entries = engine.generate_entries(schedule.schedule_id)
        assert len(entries) == 1
        assert entries[0].amount == 500

    def test_manual_recognition(self):
        engine = RevenueRecognitionEngine()
        now = datetime.now(timezone.utc)
        schedule = engine.create_schedule("lic1", 1000, now, now + timedelta(days=365))
        engine.recognize(schedule.schedule_id, 250, "2026-01")
        assert schedule.recognized_amount == 250
        assert schedule.status == RevenueStatus.PARTIALLY_RECOGNIZED

    def test_full_recognition(self):
        engine = RevenueRecognitionEngine()
        now = datetime.now(timezone.utc)
        schedule = engine.create_schedule("lic1", 100, now, now + timedelta(days=30))
        engine.recognize(schedule.schedule_id, 100, "2026-03")
        assert schedule.status == RevenueStatus.FULLY_RECOGNIZED

    def test_deferred_revenue_total(self):
        engine = RevenueRecognitionEngine()
        now = datetime.now(timezone.utc)
        engine.create_schedule("lic1", 1000, now, now + timedelta(days=365))
        engine.create_schedule("lic2", 500, now, now + timedelta(days=365))
        assert engine.get_deferred_revenue() == 1500


# ── Refund Automation (446) ──

class TestRefundAutomation:
    def test_auto_approve_small_amount(self):
        engine = RefundEngine()
        req = engine.request_refund("lic1", "chg1", 25.0, RefundReason.CUSTOMER_REQUEST)
        assert req.status == RefundStatus.APPROVED  # Auto-approved under $50

    def test_auto_approve_billing_error(self):
        engine = RefundEngine()
        req = engine.request_refund("lic1", "chg1", 200.0, RefundReason.BILLING_ERROR)
        assert req.status == RefundStatus.APPROVED  # Billing errors always auto-approved

    def test_manager_approval_needed(self):
        engine = RefundEngine()
        req = engine.request_refund("lic1", "chg1", 150.0, RefundReason.CUSTOMER_REQUEST)
        assert req.status == RefundStatus.PENDING_APPROVAL
        assert req.approval_level == ApprovalLevel.MANAGER

    def test_approve_refund(self):
        engine = RefundEngine()
        req = engine.request_refund("lic1", "chg1", 150.0, RefundReason.CUSTOMER_REQUEST)
        engine.approve(req.refund_id, "manager@test.com")
        assert req.status == RefundStatus.APPROVED

    def test_reject_refund(self):
        engine = RefundEngine()
        req = engine.request_refund("lic1", "chg1", 150.0, RefundReason.CUSTOMER_REQUEST)
        engine.reject(req.refund_id, "manager@test.com", "Not eligible")
        assert req.status == RefundStatus.REJECTED

    def test_process_approved(self):
        engine = RefundEngine()
        req = engine.request_refund("lic1", "chg1", 25.0, RefundReason.DUPLICATE_CHARGE)
        engine.process(req.refund_id)
        assert req.status == RefundStatus.COMPLETED

    def test_process_unapproved_raises(self):
        engine = RefundEngine()
        req = engine.request_refund("lic1", "chg1", 150.0, RefundReason.CUSTOMER_REQUEST)
        with pytest.raises(ValueError, match="not approved"):
            engine.process(req.refund_id)

    def test_get_pending(self):
        engine = RefundEngine()
        engine.request_refund("lic1", "chg1", 150.0, RefundReason.CUSTOMER_REQUEST)
        engine.request_refund("lic2", "chg2", 500.0, RefundReason.SERVICE_ISSUE)
        pending = engine.get_pending()
        assert len(pending) == 2


# ── Stripe Connect (450) ──

class TestStripeConnect:
    def test_create_account(self):
        mgr = StripeConnectManager()
        account = mgr.create_account("t1", "Reseller Co", "r@test.com")
        assert account.account_id.startswith("CACCT-")
        assert account.commission_pct == 20.0

    def test_payment_split(self):
        mgr = StripeConnectManager(platform_fee_pct=10)
        account = mgr.create_account("t1", "Reseller", "r@test.com", commission_pct=20)
        split = mgr.create_split("pay1", 100, account.account_id)
        assert split.connected_amount == 20.0  # 20% commission
        assert split.platform_amount == 80.0

    def test_create_payout(self):
        mgr = StripeConnectManager()
        account = mgr.create_account("t1", "R", "r@test.com")
        now = datetime.now(timezone.utc)
        mgr.create_split("pay1", 100, account.account_id)
        payout = mgr.create_payout(account.account_id, now - timedelta(hours=1), now + timedelta(hours=1))
        assert payout.amount == 20.0

    def test_complete_payout(self):
        mgr = StripeConnectManager()
        account = mgr.create_account("t1", "R", "r@test.com")
        now = datetime.now(timezone.utc)
        mgr.create_split("pay1", 100, account.account_id)
        payout = mgr.create_payout(account.account_id, now - timedelta(hours=1), now + timedelta(hours=1))
        mgr.complete_payout(payout.payout_id)
        assert payout.status == PayoutStatus.PAID

    def test_get_balance(self):
        mgr = StripeConnectManager()
        account = mgr.create_account("t1", "R", "r@test.com")
        mgr.create_split("pay1", 100, account.account_id)
        assert mgr.get_balance(account.account_id) == 20.0

    def test_activate_account(self):
        mgr = StripeConnectManager()
        account = mgr.create_account("t1", "R", "r@test.com")
        mgr.activate_account(account.account_id, "acct_stripe123")
        assert account.stripe_account_id == "acct_stripe123"


# ── Smart Dunning (453, 337, 348, 465) ──

class TestSmartDunning:
    def test_record_failure(self):
        engine = SmartDunningEngine()
        record = engine.record_failure(
            "lic1", "t1", 99.0, "USD", PaymentFailureType.INSUFFICIENT_FUNDS,
        )
        assert record.dunning_id.startswith("DUN-")
        assert record.next_retry_at is not None

    def test_card_expired_no_retry(self):
        engine = SmartDunningEngine()
        record = engine.record_failure(
            "lic1", "t1", 99.0, "USD", PaymentFailureType.CARD_EXPIRED,
        )
        assert record.next_retry_at is None  # Don't retry expired cards
        assert record.stage == DunningStage.SOFT_REMINDER

    def test_process_successful_retry(self):
        engine = SmartDunningEngine()
        record = engine.record_failure(
            "lic1", "t1", 99.0, "USD", PaymentFailureType.PROCESSING_ERROR,
        )
        engine.process_retry(record.dunning_id, success=True)
        assert record.resolved is True

    def test_process_failed_retry_advances(self):
        engine = SmartDunningEngine()
        record = engine.record_failure(
            "lic1", "t1", 99.0, "USD", PaymentFailureType.INSUFFICIENT_FUNDS,
        )
        engine.process_retry(record.dunning_id, success=False)
        assert record.retry_count == 1
        assert record.stage != DunningStage.INITIAL_RETRY

    def test_resolve_dunning(self):
        engine = SmartDunningEngine()
        record = engine.record_failure(
            "lic1", "t1", 99.0, "USD", PaymentFailureType.NETWORK_ERROR,
        )
        engine.resolve(record.dunning_id)
        assert record.resolved is True

    def test_recovery_stats(self):
        engine = SmartDunningEngine()
        r1 = engine.record_failure("lic1", "t1", 100, "USD", PaymentFailureType.INSUFFICIENT_FUNDS)
        r2 = engine.record_failure("lic2", "t1", 200, "USD", PaymentFailureType.CARD_DECLINED)
        engine.resolve(r1.dunning_id)
        stats = engine.get_recovery_stats()
        assert stats["total_records"] == 2
        assert stats["resolved"] == 1
        assert stats["recovered_amount"] == 100


# ── Chargeback Prevention (459) ──

class TestChargebackPrevention:
    def test_assess_low_risk(self):
        engine = ChargebackPreventionEngine()
        risk, score = engine.assess_risk("lic1", 50)
        assert risk == ChargebackRisk.LOW
        assert score < 0.25

    def test_assess_high_risk(self):
        engine = ChargebackPreventionEngine()
        risk, score = engine.assess_risk(
            "lic1", 3000,
            signals=[RiskSignal("velocity", 0.8, "Unusual pattern")],
            history={"previous_chargebacks": 1, "tenure_days": 10},
        )
        assert risk in (ChargebackRisk.HIGH, ChargebackRisk.CRITICAL)

    def test_create_case(self):
        engine = ChargebackPreventionEngine()
        case = engine.create_case("lic1", "chg1", 100, "USD", "fraud")
        assert case.case_id.startswith("CB-")

    def test_submit_evidence(self):
        engine = ChargebackPreventionEngine()
        case = engine.create_case("lic1", "chg1", 100, "USD", "fraud")
        engine.submit_evidence(case.case_id, {"ip_match": True, "delivery_proof": "yes"})
        assert case.status == ChargebackStatus.EVIDENCE_SUBMITTED

    def test_resolve_won(self):
        engine = ChargebackPreventionEngine()
        case = engine.create_case("lic1", "chg1", 100, "USD", "fraud")
        engine.resolve(case.case_id, won=True)
        assert case.status == ChargebackStatus.WON

    def test_preemptive_refund(self):
        engine = ChargebackPreventionEngine()
        case = engine.create_case("lic1", "chg1", 100, "USD", "fraud")
        engine.preemptive_refund(case.case_id)
        assert case.status == ChargebackStatus.REFUNDED

    def test_stats(self):
        engine = ChargebackPreventionEngine()
        c1 = engine.create_case("lic1", "chg1", 100, "USD", "fraud")
        c2 = engine.create_case("lic2", "chg2", 200, "USD", "fraud")
        engine.resolve(c1.case_id, won=True)
        engine.resolve(c2.case_id, won=False)
        stats = engine.get_stats()
        assert stats["won"] == 1
        assert stats["lost"] == 1
        assert stats["win_rate"] == 50.0
