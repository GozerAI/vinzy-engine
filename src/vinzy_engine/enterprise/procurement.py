"""Enterprise procurement integration.

Item 425: Integration with enterprise procurement systems.
Item 432: Reseller API for channel partners.
Item 438: Referral tracking and commission.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class ProcurementStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    FULFILLED = "fulfilled"
    CANCELLED = "cancelled"


@dataclass
class ProcurementOrder:
    """An enterprise procurement order."""
    order_id: str
    tenant_id: str
    requestor_email: str
    products: list[str]
    seats: int
    tier: str
    po_number: str | None = None
    budget_code: str | None = None
    approver_email: str | None = None
    status: ProcurementStatus = ProcurementStatus.PENDING
    total_amount: float = 0.0
    currency: str = "USD"
    notes: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    approved_at: datetime | None = None
    fulfilled_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResellerAccount:
    """A channel partner / reseller account."""
    reseller_id: str
    company_name: str
    contact_email: str
    tier: str = "standard"  # standard, gold, platinum
    commission_pct: float = 15.0
    status: str = "active"
    total_sales: float = 0.0
    total_commission: float = 0.0
    api_key: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResellerSale:
    """A sale made through a reseller."""
    sale_id: str
    reseller_id: str
    customer_email: str
    products: list[str]
    amount: float
    commission_amount: float
    commission_paid: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class Referral:
    """A referral from an existing customer."""
    referral_id: str
    referrer_license_id: str
    referred_email: str
    status: str = "pending"  # pending, converted, expired
    commission_pct: float = 10.0
    commission_amount: float = 0.0
    converted_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


class EnterpriseProcurementEngine:
    """Manage procurement orders, reseller API, and referrals."""

    def __init__(self):
        self._orders: dict[str, ProcurementOrder] = {}
        self._resellers: dict[str, ResellerAccount] = {}
        self._sales: list[ResellerSale] = []
        self._referrals: list[Referral] = []
        self._order_counter = 0
        self._reseller_counter = 0
        self._sale_counter = 0
        self._referral_counter = 0

    def _next_order_id(self) -> str:
        self._order_counter += 1
        return f"PO-{self._order_counter:08d}"

    def _next_reseller_id(self) -> str:
        self._reseller_counter += 1
        return f"RSL-{self._reseller_counter:06d}"

    def _next_sale_id(self) -> str:
        self._sale_counter += 1
        return f"RSALE-{self._sale_counter:08d}"

    def _next_referral_id(self) -> str:
        self._referral_counter += 1
        return f"REF-{self._referral_counter:06d}"

    # ── Procurement ──

    def submit_order(
        self,
        tenant_id: str,
        requestor_email: str,
        products: list[str],
        seats: int,
        tier: str,
        total_amount: float,
        po_number: str | None = None,
        budget_code: str | None = None,
        approver_email: str | None = None,
    ) -> ProcurementOrder:
        order = ProcurementOrder(
            order_id=self._next_order_id(),
            tenant_id=tenant_id,
            requestor_email=requestor_email,
            products=products,
            seats=seats,
            tier=tier,
            po_number=po_number,
            budget_code=budget_code,
            approver_email=approver_email,
            total_amount=total_amount,
        )
        self._orders[order.order_id] = order
        return order

    def approve_order(self, order_id: str, approver: str) -> ProcurementOrder:
        order = self._orders.get(order_id)
        if order is None:
            raise ValueError(f"Order not found: {order_id}")
        order.status = ProcurementStatus.APPROVED
        order.approver_email = approver
        order.approved_at = datetime.now(timezone.utc)
        return order

    def fulfill_order(self, order_id: str) -> ProcurementOrder:
        order = self._orders.get(order_id)
        if order is None:
            raise ValueError(f"Order not found: {order_id}")
        if order.status != ProcurementStatus.APPROVED:
            raise ValueError(f"Order {order_id} not approved")
        order.status = ProcurementStatus.FULFILLED
        order.fulfilled_at = datetime.now(timezone.utc)
        return order

    def get_orders(self, tenant_id: str | None = None, status: ProcurementStatus | None = None) -> list[ProcurementOrder]:
        results = list(self._orders.values())
        if tenant_id:
            results = [o for o in results if o.tenant_id == tenant_id]
        if status:
            results = [o for o in results if o.status == status]
        return results

    # ── Reseller API ──

    def register_reseller(
        self,
        company_name: str,
        contact_email: str,
        tier: str = "standard",
        commission_pct: float = 15.0,
    ) -> ResellerAccount:
        import secrets
        reseller = ResellerAccount(
            reseller_id=self._next_reseller_id(),
            company_name=company_name,
            contact_email=contact_email,
            tier=tier,
            commission_pct=commission_pct,
            api_key=f"rsl_{secrets.token_urlsafe(32)}",
        )
        self._resellers[reseller.reseller_id] = reseller
        return reseller

    def record_reseller_sale(
        self,
        reseller_id: str,
        customer_email: str,
        products: list[str],
        amount: float,
    ) -> ResellerSale:
        reseller = self._resellers.get(reseller_id)
        if reseller is None:
            raise ValueError(f"Reseller not found: {reseller_id}")

        commission = round(amount * reseller.commission_pct / 100, 2)
        sale = ResellerSale(
            sale_id=self._next_sale_id(),
            reseller_id=reseller_id,
            customer_email=customer_email,
            products=products,
            amount=amount,
            commission_amount=commission,
        )
        self._sales.append(sale)
        reseller.total_sales += amount
        reseller.total_commission += commission
        return sale

    def get_reseller(self, reseller_id: str) -> ResellerAccount | None:
        return self._resellers.get(reseller_id)

    def get_resellers(self) -> list[ResellerAccount]:
        return list(self._resellers.values())

    def get_reseller_sales(self, reseller_id: str) -> list[ResellerSale]:
        return [s for s in self._sales if s.reseller_id == reseller_id]

    # ── Referrals ──

    def create_referral(
        self,
        referrer_license_id: str,
        referred_email: str,
        commission_pct: float = 10.0,
    ) -> Referral:
        referral = Referral(
            referral_id=self._next_referral_id(),
            referrer_license_id=referrer_license_id,
            referred_email=referred_email,
            commission_pct=commission_pct,
        )
        self._referrals.append(referral)
        return referral

    def convert_referral(self, referral_id: str, sale_amount: float) -> Referral:
        for ref in self._referrals:
            if ref.referral_id == referral_id:
                ref.status = "converted"
                ref.converted_at = datetime.now(timezone.utc)
                ref.commission_amount = round(sale_amount * ref.commission_pct / 100, 2)
                return ref
        raise ValueError(f"Referral not found: {referral_id}")

    def get_referrals(
        self, referrer_license_id: str | None = None, status: str | None = None
    ) -> list[Referral]:
        results = self._referrals
        if referrer_license_id:
            results = [r for r in results if r.referrer_license_id == referrer_license_id]
        if status:
            results = [r for r in results if r.status == status]
        return results
