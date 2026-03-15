"""Prepaid credit purchase with bonus.

Item 272: Allow customers to buy credits in advance with bonus credits
for larger purchases.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class CreditPackage:
    """A purchasable credit package."""
    package_id: str
    name: str
    credits: int
    price_usd: float
    bonus_credits: int = 0
    bonus_pct: float = 0.0  # Alternative: bonus as percentage
    valid_days: int = 365
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def total_credits(self) -> int:
        bonus = self.bonus_credits or int(self.credits * self.bonus_pct / 100)
        return self.credits + bonus

    @property
    def effective_cost_per_credit(self) -> float:
        if self.total_credits == 0:
            return 0.0
        return round(self.price_usd / self.total_credits, 4)


# Default credit packages
DEFAULT_PACKAGES = [
    CreditPackage("credits_500", "Starter Pack", credits=500, price_usd=9.99, bonus_credits=0),
    CreditPackage("credits_2000", "Growth Pack", credits=2000, price_usd=34.99, bonus_credits=200),
    CreditPackage("credits_5000", "Pro Pack", credits=5000, price_usd=79.99, bonus_credits=750),
    CreditPackage("credits_10000", "Business Pack", credits=10000, price_usd=149.99, bonus_credits=2000),
    CreditPackage("credits_25000", "Enterprise Pack", credits=25000, price_usd=349.99, bonus_credits=6250),
    CreditPackage("credits_100000", "Mega Pack", credits=100000, price_usd=1199.99, bonus_credits=30000),
]


@dataclass
class CreditBalance:
    """A customer's credit balance."""
    license_id: str
    purchased_credits: int = 0
    bonus_credits: int = 0
    used_credits: int = 0
    reserved_credits: int = 0
    expires_at: datetime | None = None

    @property
    def available(self) -> int:
        return self.purchased_credits + self.bonus_credits - self.used_credits - self.reserved_credits

    @property
    def total_credits(self) -> int:
        return self.purchased_credits + self.bonus_credits


@dataclass
class CreditTransaction:
    """A credit purchase or usage transaction."""
    transaction_id: str
    license_id: str
    type: str  # purchase, usage, bonus, refund, expiry
    amount: int  # positive = credit, negative = debit
    balance_after: int
    package_id: str | None = None
    description: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


class PrepaidCreditEngine:
    """Manage prepaid credit purchases, bonuses, and consumption."""

    def __init__(self, packages: list[CreditPackage] | None = None):
        self._packages = {p.package_id: p for p in (packages or DEFAULT_PACKAGES)}
        self._balances: dict[str, CreditBalance] = {}
        self._transactions: list[CreditTransaction] = []
        self._tx_counter = 0

    def _next_tx_id(self) -> str:
        self._tx_counter += 1
        return f"CTX-{self._tx_counter:08d}"

    def list_packages(self) -> list[CreditPackage]:
        return list(self._packages.values())

    def get_package(self, package_id: str) -> CreditPackage | None:
        return self._packages.get(package_id)

    def get_balance(self, license_id: str) -> CreditBalance:
        if license_id not in self._balances:
            self._balances[license_id] = CreditBalance(license_id=license_id)
        return self._balances[license_id]

    def purchase(self, license_id: str, package_id: str) -> CreditTransaction:
        """Purchase a credit package."""
        package = self._packages.get(package_id)
        if package is None:
            raise ValueError(f"Unknown package: {package_id}")

        balance = self.get_balance(license_id)
        bonus = package.bonus_credits or int(package.credits * package.bonus_pct / 100)

        balance.purchased_credits += package.credits
        balance.bonus_credits += bonus

        if package.valid_days > 0:
            from datetime import timedelta
            balance.expires_at = datetime.now(timezone.utc) + timedelta(days=package.valid_days)

        tx = CreditTransaction(
            transaction_id=self._next_tx_id(),
            license_id=license_id,
            type="purchase",
            amount=package.credits,
            balance_after=balance.available,
            package_id=package_id,
            description=f"Purchased {package.name}: {package.credits} credits + {bonus} bonus",
        )
        self._transactions.append(tx)

        if bonus > 0:
            bonus_tx = CreditTransaction(
                transaction_id=self._next_tx_id(),
                license_id=license_id,
                type="bonus",
                amount=bonus,
                balance_after=balance.available,
                package_id=package_id,
                description=f"Bonus credits from {package.name}",
            )
            self._transactions.append(bonus_tx)

        return tx

    def consume(
        self, license_id: str, amount: int, description: str = ""
    ) -> CreditTransaction:
        """Consume credits from balance."""
        balance = self.get_balance(license_id)
        if balance.available < amount:
            raise ValueError(
                f"Insufficient credits: need {amount}, have {balance.available}"
            )

        balance.used_credits += amount
        tx = CreditTransaction(
            transaction_id=self._next_tx_id(),
            license_id=license_id,
            type="usage",
            amount=-amount,
            balance_after=balance.available,
            description=description or f"Consumed {amount} credits",
        )
        self._transactions.append(tx)
        return tx

    def reserve(self, license_id: str, amount: int) -> bool:
        """Reserve credits for pending operations."""
        balance = self.get_balance(license_id)
        if balance.available < amount:
            return False
        balance.reserved_credits += amount
        return True

    def release_reservation(self, license_id: str, amount: int) -> None:
        """Release previously reserved credits."""
        balance = self.get_balance(license_id)
        balance.reserved_credits = max(0, balance.reserved_credits - amount)

    def refund(self, license_id: str, amount: int, reason: str = "") -> CreditTransaction:
        """Refund credits to balance."""
        balance = self.get_balance(license_id)
        balance.used_credits = max(0, balance.used_credits - amount)
        tx = CreditTransaction(
            transaction_id=self._next_tx_id(),
            license_id=license_id,
            type="refund",
            amount=amount,
            balance_after=balance.available,
            description=reason or f"Refunded {amount} credits",
        )
        self._transactions.append(tx)
        return tx

    def get_transactions(
        self, license_id: str, type_filter: str | None = None
    ) -> list[CreditTransaction]:
        txs = [t for t in self._transactions if t.license_id == license_id]
        if type_filter:
            txs = [t for t in txs if t.type == type_filter]
        return txs

    def check_expiry(self, license_id: str) -> bool:
        """Check and handle expired credits. Returns True if credits expired."""
        balance = self.get_balance(license_id)
        if balance.expires_at and balance.expires_at < datetime.now(timezone.utc):
            expired = balance.available
            if expired > 0:
                balance.used_credits += expired
                self._transactions.append(CreditTransaction(
                    transaction_id=self._next_tx_id(),
                    license_id=license_id,
                    type="expiry",
                    amount=-expired,
                    balance_after=0,
                    description=f"Credits expired: {expired} credits",
                ))
                return True
        return False
