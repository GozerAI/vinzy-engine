"""Enterprise contract management.

Item 410: Manage enterprise contracts with terms, renewals, and compliance.
Item 414: Enterprise billing with PO numbers.
Item 352: Contract end date reminders with renewal offers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any


class ContractStatus(str, Enum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    ACTIVE = "active"
    EXPIRING_SOON = "expiring_soon"
    EXPIRED = "expired"
    RENEWED = "renewed"
    CANCELLED = "cancelled"


class PaymentTerms(str, Enum):
    NET_30 = "net_30"
    NET_60 = "net_60"
    NET_90 = "net_90"
    PREPAID = "prepaid"
    UPON_RECEIPT = "upon_receipt"


@dataclass
class EnterpriseContract:
    """An enterprise contract."""
    contract_id: str
    tenant_id: str
    company_name: str
    start_date: datetime
    end_date: datetime
    total_value: float
    annual_value: float
    payment_terms: PaymentTerms = PaymentTerms.NET_30
    po_number: str | None = None
    billing_contact: str = ""
    billing_email: str = ""
    status: ContractStatus = ContractStatus.DRAFT
    auto_renew: bool = False
    renewal_notice_days: int = 60
    products: list[str] = field(default_factory=list)
    seats: int = 0
    sla_tier: str = "standard"
    custom_terms: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def days_remaining(self) -> int:
        end = self.end_date.replace(tzinfo=timezone.utc) if self.end_date.tzinfo is None else self.end_date
        return max(0, (end - datetime.now(timezone.utc)).days)

    @property
    def is_expiring_soon(self) -> bool:
        return 0 < self.days_remaining <= self.renewal_notice_days

    @property
    def is_expired(self) -> bool:
        return self.days_remaining == 0 and self.status not in (
            ContractStatus.RENEWED, ContractStatus.CANCELLED
        )

    @property
    def monthly_value(self) -> float:
        return round(self.annual_value / 12, 2)


@dataclass
class ContractInvoice:
    """An invoice against an enterprise contract."""
    invoice_id: str
    contract_id: str
    po_number: str | None
    amount: float
    currency: str = "USD"
    due_date: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "pending"  # pending, sent, paid, overdue
    period_start: datetime | None = None
    period_end: datetime | None = None
    line_items: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class RenewalOffer:
    """A renewal offer for an expiring contract."""
    offer_id: str
    contract_id: str
    new_total_value: float
    new_annual_value: float
    discount_pct: float
    new_end_date: datetime
    valid_until: datetime
    accepted: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class EnterpriseContractManager:
    """Manage enterprise contracts, billing with PO numbers, and renewals."""

    def __init__(self):
        self._contracts: dict[str, EnterpriseContract] = {}
        self._invoices: list[ContractInvoice] = []
        self._renewal_offers: list[RenewalOffer] = []
        self._contract_counter = 0
        self._invoice_counter = 0
        self._offer_counter = 0

    def _next_contract_id(self) -> str:
        self._contract_counter += 1
        return f"ENT-C-{self._contract_counter:06d}"

    def _next_invoice_id(self) -> str:
        self._invoice_counter += 1
        return f"ENT-INV-{self._invoice_counter:08d}"

    def _next_offer_id(self) -> str:
        self._offer_counter += 1
        return f"RNW-{self._offer_counter:06d}"

    def create_contract(
        self,
        tenant_id: str,
        company_name: str,
        start_date: datetime,
        end_date: datetime,
        annual_value: float,
        products: list[str],
        seats: int = 0,
        po_number: str | None = None,
        payment_terms: PaymentTerms = PaymentTerms.NET_30,
        auto_renew: bool = False,
        sla_tier: str = "standard",
        custom_terms: dict[str, Any] | None = None,
    ) -> EnterpriseContract:
        start_tz = start_date.replace(tzinfo=timezone.utc) if start_date.tzinfo is None else start_date
        end_tz = end_date.replace(tzinfo=timezone.utc) if end_date.tzinfo is None else end_date
        months = max(1, (end_tz - start_tz).days // 30)
        total_value = round(annual_value * months / 12, 2)

        contract = EnterpriseContract(
            contract_id=self._next_contract_id(),
            tenant_id=tenant_id,
            company_name=company_name,
            start_date=start_tz,
            end_date=end_tz,
            total_value=total_value,
            annual_value=annual_value,
            payment_terms=payment_terms,
            po_number=po_number,
            products=products,
            seats=seats,
            auto_renew=auto_renew,
            sla_tier=sla_tier,
            custom_terms=custom_terms or {},
        )
        self._contracts[contract.contract_id] = contract
        return contract

    def activate_contract(self, contract_id: str) -> EnterpriseContract:
        contract = self._contracts.get(contract_id)
        if contract is None:
            raise ValueError(f"Contract not found: {contract_id}")
        contract.status = ContractStatus.ACTIVE
        return contract

    def generate_invoice(
        self,
        contract_id: str,
        amount: float,
        period_start: datetime,
        period_end: datetime,
        line_items: list[dict[str, Any]] | None = None,
    ) -> ContractInvoice:
        """Generate an invoice for a contract period."""
        contract = self._contracts.get(contract_id)
        if contract is None:
            raise ValueError(f"Contract not found: {contract_id}")

        # Calculate due date based on payment terms
        due_days = {
            PaymentTerms.NET_30: 30,
            PaymentTerms.NET_60: 60,
            PaymentTerms.NET_90: 90,
            PaymentTerms.PREPAID: 0,
            PaymentTerms.UPON_RECEIPT: 0,
        }
        due_date = datetime.now(timezone.utc) + timedelta(days=due_days.get(contract.payment_terms, 30))

        invoice = ContractInvoice(
            invoice_id=self._next_invoice_id(),
            contract_id=contract_id,
            po_number=contract.po_number,
            amount=amount,
            due_date=due_date,
            period_start=period_start,
            period_end=period_end,
            line_items=line_items or [],
        )
        self._invoices.append(invoice)
        return invoice

    def generate_renewal_offer(
        self,
        contract_id: str,
        discount_pct: float = 5.0,
        extension_months: int = 12,
    ) -> RenewalOffer:
        """Generate a renewal offer for an expiring contract."""
        contract = self._contracts.get(contract_id)
        if contract is None:
            raise ValueError(f"Contract not found: {contract_id}")

        new_annual = round(contract.annual_value * (1 - discount_pct / 100), 2)
        new_end = contract.end_date + timedelta(days=extension_months * 30)
        valid_until = contract.end_date  # Offer valid until contract expires

        offer = RenewalOffer(
            offer_id=self._next_offer_id(),
            contract_id=contract_id,
            new_total_value=round(new_annual * extension_months / 12, 2),
            new_annual_value=new_annual,
            discount_pct=discount_pct,
            new_end_date=new_end,
            valid_until=valid_until,
        )
        self._renewal_offers.append(offer)
        return offer

    def accept_renewal(self, offer_id: str) -> EnterpriseContract:
        """Accept a renewal offer, extending the contract."""
        offer = None
        for o in self._renewal_offers:
            if o.offer_id == offer_id:
                offer = o
                break
        if offer is None:
            raise ValueError(f"Offer not found: {offer_id}")

        contract = self._contracts.get(offer.contract_id)
        if contract is None:
            raise ValueError(f"Contract not found: {offer.contract_id}")

        offer.accepted = True
        contract.end_date = offer.new_end_date
        contract.annual_value = offer.new_annual_value
        contract.total_value = offer.new_total_value
        contract.status = ContractStatus.RENEWED
        return contract

    def get_expiring_contracts(self, within_days: int = 60) -> list[EnterpriseContract]:
        """Get contracts expiring within N days."""
        return [
            c for c in self._contracts.values()
            if c.status == ContractStatus.ACTIVE and c.days_remaining <= within_days
        ]

    def check_expiry_reminders(self) -> list[tuple[EnterpriseContract, int]]:
        """Check for contracts needing renewal reminders. Returns (contract, days_remaining)."""
        reminders = []
        for contract in self._contracts.values():
            if contract.status == ContractStatus.ACTIVE and contract.is_expiring_soon:
                reminders.append((contract, contract.days_remaining))
        return reminders

    def get_contract(self, contract_id: str) -> EnterpriseContract | None:
        return self._contracts.get(contract_id)

    def get_contracts(self, tenant_id: str | None = None, status: ContractStatus | None = None) -> list[EnterpriseContract]:
        results = list(self._contracts.values())
        if tenant_id:
            results = [c for c in results if c.tenant_id == tenant_id]
        if status:
            results = [c for c in results if c.status == status]
        return results

    def get_invoices(self, contract_id: str | None = None) -> list[ContractInvoice]:
        if contract_id:
            return [i for i in self._invoices if i.contract_id == contract_id]
        return list(self._invoices)
