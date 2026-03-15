"""Tests for enterprise module: dashboard, volume licensing, contracts, compliance, procurement."""

import pytest
from datetime import datetime, timedelta, timezone

from vinzy_engine.enterprise.dashboard import EnterpriseDashboardService
from vinzy_engine.enterprise.volume_licensing import VolumeLicensingEngine
from vinzy_engine.enterprise.contracts import (
    EnterpriseContractManager, ContractStatus, PaymentTerms,
)
from vinzy_engine.enterprise.compliance_reporting import (
    ComplianceReportingEngine, ComplianceStatus,
)
from vinzy_engine.enterprise.procurement import EnterpriseProcurementEngine, ProcurementStatus


# ── Enterprise Dashboard (400) ──

class TestEnterpriseDashboard:
    def test_generate_dashboard(self):
        svc = EnterpriseDashboardService()
        licenses = [
            {"id": "l1", "status": "active", "tier": "pro", "email": "a@test.com", "product_code": "AGW"},
            {"id": "l2", "status": "active", "tier": "growth", "email": "b@test.com", "product_code": "NXS"},
            {"id": "l3", "status": "expired", "tier": "pro", "email": "c@test.com", "product_code": "AGW"},
        ]
        usage = [{"license_id": "l1", "value": 100}, {"license_id": "l2", "value": 200}]
        data = svc.generate_dashboard("t1", licenses, usage)
        assert data.total_licenses == 3
        assert data.active_licenses == 2
        assert data.expired_licenses == 1
        assert data.total_usage == 300
        assert len(data.alerts) > 0

    def test_add_alert(self):
        svc = EnterpriseDashboardService()
        alert = svc.add_alert("warning", "High usage detected", "usage")
        assert alert.alert_id.startswith("ALERT-")
        assert len(svc.get_alerts()) == 1

    def test_acknowledge_alert(self):
        svc = EnterpriseDashboardService()
        alert = svc.add_alert("info", "Test", "billing")
        svc.acknowledge_alert(alert.alert_id)
        assert alert.acknowledged is True

    def test_filter_alerts(self):
        svc = EnterpriseDashboardService()
        svc.add_alert("warning", "Usage", "usage")
        svc.add_alert("critical", "Billing", "billing")
        assert len(svc.get_alerts(category="usage")) == 1


# ── Volume Licensing (405, 418) ──

class TestVolumeLicensing:
    def test_create_pool(self):
        engine = VolumeLicensingEngine()
        pool = engine.create_pool("t1", "AGW", "growth", 50, price_per_seat=25.0)
        assert pool.pool_id.startswith("VPOOL-")
        assert pool.available_seats == 50

    def test_allocate_seat(self):
        engine = VolumeLicensingEngine()
        pool = engine.create_pool("t1", "AGW", "growth", 5)
        alloc = engine.allocate_seat(pool.pool_id, "lic1", "user@test.com")
        assert alloc.active is True
        assert pool.available_seats == 4

    def test_allocate_exceeds_pool(self):
        engine = VolumeLicensingEngine()
        pool = engine.create_pool("t1", "AGW", "growth", 1)
        engine.allocate_seat(pool.pool_id, "lic1", "a@test.com")
        with pytest.raises(ValueError, match="No available seats"):
            engine.allocate_seat(pool.pool_id, "lic2", "b@test.com")

    def test_release_seat(self):
        engine = VolumeLicensingEngine()
        pool = engine.create_pool("t1", "AGW", "growth", 5)
        alloc = engine.allocate_seat(pool.pool_id, "lic1", "a@test.com")
        engine.release_seat(alloc.allocation_id)
        assert pool.available_seats == 5

    def test_transfer_license(self):
        """Item 418: license transfer between users."""
        engine = VolumeLicensingEngine()
        pool = engine.create_pool("t1", "AGW", "growth", 5)
        engine.allocate_seat(pool.pool_id, "lic1", "old@test.com")
        transfer = engine.transfer_license(pool.pool_id, "old@test.com", "new@test.com", "lic2")
        assert transfer.from_email == "old@test.com"
        assert transfer.to_email == "new@test.com"
        # Pool size unchanged
        assert pool.allocated_seats == 1

    def test_resize_pool(self):
        engine = VolumeLicensingEngine()
        pool = engine.create_pool("t1", "AGW", "growth", 5)
        engine.resize_pool(pool.pool_id, 10)
        assert pool.total_seats == 10

    def test_resize_below_allocated_raises(self):
        engine = VolumeLicensingEngine()
        pool = engine.create_pool("t1", "AGW", "growth", 5)
        engine.allocate_seat(pool.pool_id, "lic1", "a@test.com")
        engine.allocate_seat(pool.pool_id, "lic2", "b@test.com")
        with pytest.raises(ValueError, match="Cannot shrink"):
            engine.resize_pool(pool.pool_id, 1)

    def test_utilization(self):
        engine = VolumeLicensingEngine()
        pool = engine.create_pool("t1", "AGW", "growth", 10)
        engine.allocate_seat(pool.pool_id, "lic1", "a@test.com")
        engine.allocate_seat(pool.pool_id, "lic2", "b@test.com")
        assert pool.utilization_pct == 20.0


# ── Enterprise Contracts (410, 414, 352) ──

class TestEnterpriseContracts:
    def test_create_contract(self):
        mgr = EnterpriseContractManager()
        now = datetime.now(timezone.utc)
        contract = mgr.create_contract(
            "t1", "Acme Corp", now, now + timedelta(days=365),
            annual_value=50000, products=["AGW", "NXS"],
            seats=50, po_number="PO-12345",
        )
        assert contract.contract_id.startswith("ENT-C-")
        assert contract.po_number == "PO-12345"
        assert contract.days_remaining > 360

    def test_activate_contract(self):
        mgr = EnterpriseContractManager()
        now = datetime.now(timezone.utc)
        contract = mgr.create_contract(
            "t1", "Acme", now, now + timedelta(days=365),
            annual_value=10000, products=["AGW"],
        )
        mgr.activate_contract(contract.contract_id)
        assert contract.status == ContractStatus.ACTIVE

    def test_generate_invoice_with_po(self):
        """Item 414: billing with PO numbers."""
        mgr = EnterpriseContractManager()
        now = datetime.now(timezone.utc)
        contract = mgr.create_contract(
            "t1", "Acme", now, now + timedelta(days=365),
            annual_value=12000, products=["AGW"],
            po_number="PO-99",
        )
        invoice = mgr.generate_invoice(
            contract.contract_id, 1000, now, now + timedelta(days=30),
        )
        assert invoice.po_number == "PO-99"
        assert invoice.amount == 1000

    def test_payment_terms_affect_due_date(self):
        mgr = EnterpriseContractManager()
        now = datetime.now(timezone.utc)
        contract = mgr.create_contract(
            "t1", "Acme", now, now + timedelta(days=365),
            annual_value=12000, products=["AGW"],
            payment_terms=PaymentTerms.NET_90,
        )
        invoice = mgr.generate_invoice(contract.contract_id, 1000, now, now + timedelta(days=30))
        assert (invoice.due_date - now).days >= 89

    def test_renewal_offer(self):
        """Item 352: contract end date reminders with renewal offers."""
        mgr = EnterpriseContractManager()
        now = datetime.now(timezone.utc)
        contract = mgr.create_contract(
            "t1", "Acme", now, now + timedelta(days=365),
            annual_value=10000, products=["AGW"],
        )
        mgr.activate_contract(contract.contract_id)
        offer = mgr.generate_renewal_offer(contract.contract_id, discount_pct=10)
        assert offer.discount_pct == 10
        assert offer.new_annual_value < 10000

    def test_accept_renewal(self):
        mgr = EnterpriseContractManager()
        now = datetime.now(timezone.utc)
        contract = mgr.create_contract(
            "t1", "Acme", now, now + timedelta(days=365),
            annual_value=10000, products=["AGW"],
        )
        mgr.activate_contract(contract.contract_id)
        offer = mgr.generate_renewal_offer(contract.contract_id)
        mgr.accept_renewal(offer.offer_id)
        assert contract.status == ContractStatus.RENEWED

    def test_expiring_contracts(self):
        mgr = EnterpriseContractManager()
        now = datetime.now(timezone.utc)
        c1 = mgr.create_contract(
            "t1", "Acme", now, now + timedelta(days=30),
            annual_value=10000, products=["AGW"],
        )
        mgr.activate_contract(c1.contract_id)
        c2 = mgr.create_contract(
            "t2", "Beta", now, now + timedelta(days=365),
            annual_value=10000, products=["NXS"],
        )
        mgr.activate_contract(c2.contract_id)
        expiring = mgr.get_expiring_contracts(within_days=60)
        assert len(expiring) == 1


# ── Compliance Reporting (422) ──

class TestComplianceReporting:
    def test_record_violation(self):
        engine = ComplianceReportingEngine()
        v = engine.record_violation("t1", "over_usage", "high", "Exceeded limits", "lic1")
        assert v.violation_id.startswith("VIOL-")

    def test_resolve_violation(self):
        engine = ComplianceReportingEngine()
        v = engine.record_violation("t1", "expired_license", "medium", "License expired")
        engine.resolve_violation(v.violation_id)
        assert v.resolved is True

    def test_generate_report(self):
        engine = ComplianceReportingEngine()
        engine.record_violation("t1", "over_usage", "high", "Over limit")
        now = datetime.now(timezone.utc)
        report = engine.generate_report(
            "t1", now - timedelta(days=30), now,
            licenses=[
                {"id": "l1", "status": "active", "features": {"api": True}},
                {"id": "l2", "status": "active", "features": {"api": True}},
            ],
        )
        assert report.overall_status in (ComplianceStatus.WARNING, ComplianceStatus.NON_COMPLIANT)
        assert len(report.violations) == 1
        assert len(report.recommendations) > 0

    def test_compliant_report(self):
        engine = ComplianceReportingEngine()
        now = datetime.now(timezone.utc)
        report = engine.generate_report(
            "t1", now - timedelta(days=30), now,
            licenses=[{"id": "l1", "status": "active", "features": {}}],
        )
        assert report.overall_status == ComplianceStatus.COMPLIANT


# ── Procurement, Reseller, Referral (425, 432, 438) ──

class TestProcurement:
    def test_submit_order(self):
        engine = EnterpriseProcurementEngine()
        order = engine.submit_order(
            "t1", "buyer@test.com", ["AGW", "NXS"], 50, "growth", 25000,
            po_number="PO-100",
        )
        assert order.status == ProcurementStatus.PENDING

    def test_approve_and_fulfill(self):
        engine = EnterpriseProcurementEngine()
        order = engine.submit_order("t1", "buyer@test.com", ["AGW"], 10, "pro", 5000)
        engine.approve_order(order.order_id, "approver@test.com")
        assert order.status == ProcurementStatus.APPROVED
        engine.fulfill_order(order.order_id)
        assert order.status == ProcurementStatus.FULFILLED

    def test_fulfill_unapproved_raises(self):
        engine = EnterpriseProcurementEngine()
        order = engine.submit_order("t1", "buyer@test.com", ["AGW"], 10, "pro", 5000)
        with pytest.raises(ValueError, match="not approved"):
            engine.fulfill_order(order.order_id)

    def test_register_reseller(self):
        engine = EnterpriseProcurementEngine()
        reseller = engine.register_reseller("Partner Co", "partner@test.com", commission_pct=20)
        assert reseller.reseller_id.startswith("RSL-")
        assert reseller.api_key.startswith("rsl_")

    def test_reseller_sale(self):
        engine = EnterpriseProcurementEngine()
        reseller = engine.register_reseller("Partner", "p@test.com", commission_pct=15)
        sale = engine.record_reseller_sale(reseller.reseller_id, "cust@test.com", ["AGW"], 1000)
        assert sale.commission_amount == 150
        assert reseller.total_sales == 1000

    def test_create_referral(self):
        engine = EnterpriseProcurementEngine()
        ref = engine.create_referral("lic1", "friend@test.com")
        assert ref.referral_id.startswith("REF-")
        assert ref.status == "pending"

    def test_convert_referral(self):
        engine = EnterpriseProcurementEngine()
        ref = engine.create_referral("lic1", "friend@test.com", commission_pct=10)
        engine.convert_referral(ref.referral_id, 500)
        assert ref.status == "converted"
        assert ref.commission_amount == 50
