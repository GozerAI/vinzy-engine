"""Stripe Connect for marketplace payouts.

Item 450: Manage connected accounts, splits, and payouts via Stripe Connect model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class PayoutStatus(str, Enum):
    PENDING = "pending"
    IN_TRANSIT = "in_transit"
    PAID = "paid"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ConnectedAccountStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    RESTRICTED = "restricted"
    DISABLED = "disabled"


@dataclass
class ConnectedAccount:
    """A Stripe Connect connected account (reseller/partner)."""
    account_id: str
    tenant_id: str
    business_name: str
    email: str
    country: str = "US"
    currency: str = "USD"
    commission_pct: float = 20.0  # Default 20% commission
    status: ConnectedAccountStatus = ConnectedAccountStatus.PENDING
    stripe_account_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PaymentSplit:
    """A payment split between platform and connected account."""
    split_id: str
    payment_id: str
    total_amount: float
    platform_amount: float
    connected_amount: float
    connected_account_id: str
    currency: str = "USD"
    status: str = "pending"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class Payout:
    """A payout to a connected account."""
    payout_id: str
    connected_account_id: str
    amount: float
    currency: str = "USD"
    status: PayoutStatus = PayoutStatus.PENDING
    period_start: datetime | None = None
    period_end: datetime | None = None
    split_ids: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    paid_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class StripeConnectManager:
    """Manage Stripe Connect accounts, payment splits, and payouts."""

    def __init__(self, platform_fee_pct: float = 10.0):
        self._platform_fee_pct = platform_fee_pct
        self._accounts: dict[str, ConnectedAccount] = {}
        self._splits: list[PaymentSplit] = []
        self._payouts: list[Payout] = []
        self._acct_counter = 0
        self._split_counter = 0
        self._payout_counter = 0

    def _next_acct_id(self) -> str:
        self._acct_counter += 1
        return f"CACCT-{self._acct_counter:06d}"

    def _next_split_id(self) -> str:
        self._split_counter += 1
        return f"SPLT-{self._split_counter:08d}"

    def _next_payout_id(self) -> str:
        self._payout_counter += 1
        return f"PYT-{self._payout_counter:08d}"

    def create_account(
        self,
        tenant_id: str,
        business_name: str,
        email: str,
        country: str = "US",
        commission_pct: float | None = None,
    ) -> ConnectedAccount:
        account = ConnectedAccount(
            account_id=self._next_acct_id(),
            tenant_id=tenant_id,
            business_name=business_name,
            email=email,
            country=country,
            commission_pct=commission_pct if commission_pct is not None else 20.0,
        )
        self._accounts[account.account_id] = account
        return account

    def activate_account(self, account_id: str, stripe_account_id: str) -> ConnectedAccount:
        account = self._accounts.get(account_id)
        if account is None:
            raise ValueError(f"Account not found: {account_id}")
        account.stripe_account_id = stripe_account_id
        account.status = ConnectedAccountStatus.ACTIVE
        return account

    def create_split(
        self,
        payment_id: str,
        total_amount: float,
        connected_account_id: str,
        currency: str = "USD",
    ) -> PaymentSplit:
        """Split a payment between platform and connected account."""
        account = self._accounts.get(connected_account_id)
        if account is None:
            raise ValueError(f"Account not found: {connected_account_id}")

        platform_fee = round(total_amount * self._platform_fee_pct / 100, 2)
        connected_share = round(total_amount * account.commission_pct / 100, 2)
        # Platform gets the rest after connected account commission
        platform_amount = round(total_amount - connected_share, 2)

        split = PaymentSplit(
            split_id=self._next_split_id(),
            payment_id=payment_id,
            total_amount=total_amount,
            platform_amount=platform_amount,
            connected_amount=connected_share,
            connected_account_id=connected_account_id,
            currency=currency,
        )
        self._splits.append(split)
        return split

    def create_payout(
        self,
        connected_account_id: str,
        period_start: datetime,
        period_end: datetime,
    ) -> Payout:
        """Create a payout for all pending splits in a period."""
        splits = [
            s for s in self._splits
            if s.connected_account_id == connected_account_id
            and s.status == "pending"
            and s.created_at >= period_start
            and s.created_at <= period_end
        ]

        total = round(sum(s.connected_amount for s in splits), 2)
        for s in splits:
            s.status = "included_in_payout"

        payout = Payout(
            payout_id=self._next_payout_id(),
            connected_account_id=connected_account_id,
            amount=total,
            period_start=period_start,
            period_end=period_end,
            split_ids=[s.split_id for s in splits],
        )
        self._payouts.append(payout)
        return payout

    def complete_payout(self, payout_id: str) -> Payout:
        for p in self._payouts:
            if p.payout_id == payout_id:
                p.status = PayoutStatus.PAID
                p.paid_at = datetime.now(timezone.utc)
                return p
        raise ValueError(f"Payout not found: {payout_id}")

    def get_account(self, account_id: str) -> ConnectedAccount | None:
        return self._accounts.get(account_id)

    def get_accounts(self, tenant_id: str | None = None) -> list[ConnectedAccount]:
        accounts = list(self._accounts.values())
        if tenant_id:
            accounts = [a for a in accounts if a.tenant_id == tenant_id]
        return accounts

    def get_payouts(self, account_id: str | None = None) -> list[Payout]:
        payouts = self._payouts
        if account_id:
            payouts = [p for p in payouts if p.connected_account_id == account_id]
        return payouts

    def get_balance(self, account_id: str) -> float:
        """Get pending balance for a connected account."""
        pending = [
            s for s in self._splits
            if s.connected_account_id == account_id and s.status == "pending"
        ]
        return round(sum(s.connected_amount for s in pending), 2)
