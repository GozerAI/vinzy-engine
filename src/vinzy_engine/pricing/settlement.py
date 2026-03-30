"""Multi-currency settlement support.

Item 290: Handle settlements in multiple currencies with exchange rate
management and conversion tracking.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from vinzy_engine.pricing.engine import CurrencyConfig, SUPPORTED_CURRENCIES


@dataclass
class ExchangeRate:
    """A point-in-time exchange rate."""
    from_currency: str
    to_currency: str
    rate: float
    source: str = "manual"
    effective_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class SettlementRecord:
    """A settlement transaction in a specific currency."""
    settlement_id: str
    license_id: str
    original_currency: str
    original_amount: float
    settlement_currency: str
    settlement_amount: float
    exchange_rate: float
    fee_amount: float = 0.0
    net_amount: float = 0.0
    status: str = "pending"  # pending, completed, failed
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class MultiCurrencySettlement:
    """Handle multi-currency settlements with exchange rate tracking."""

    def __init__(self, base_currency: str = "USD"):
        self.base_currency = base_currency
        self._currencies = dict(SUPPORTED_CURRENCIES)
        self._rate_history: list[ExchangeRate] = []
        self._settlements: list[SettlementRecord] = []
        self._counter = 0
        # Fee schedule by currency
        self._fees: dict[str, float] = {
            "USD": 0.0,
            "EUR": 0.005,
            "GBP": 0.005,
            "CAD": 0.005,
            "AUD": 0.01,
            "JPY": 0.01,
            "BRL": 0.02,
            "INR": 0.02,
        }

    def _next_id(self) -> str:
        self._counter += 1
        return f"STL-{self._counter:08d}"

    def update_exchange_rate(
        self, from_currency: str, to_currency: str, rate: float, source: str = "manual"
    ) -> ExchangeRate:
        """Update an exchange rate."""
        record = ExchangeRate(
            from_currency=from_currency,
            to_currency=to_currency,
            rate=rate,
            source=source,
        )
        self._rate_history.append(record)
        # Update currency config if it's a base currency rate
        if from_currency == "USD" and to_currency in self._currencies:
            self._currencies[to_currency] = CurrencyConfig(
                code=to_currency,
                symbol=self._currencies[to_currency].symbol,
                decimal_places=self._currencies[to_currency].decimal_places,
                exchange_rate=rate,
            )
        return record

    def get_rate(self, from_currency: str, to_currency: str) -> float:
        """Get the current exchange rate between two currencies."""
        if from_currency == to_currency:
            return 1.0
        # Convert via base currency
        from_cc = self._currencies.get(from_currency)
        to_cc = self._currencies.get(to_currency)
        if from_cc is None or to_cc is None:
            raise ValueError(f"Unsupported currency pair: {from_currency}/{to_currency}")
        # from -> USD -> to
        usd_amount = 1.0 / from_cc.exchange_rate
        return round(usd_amount * to_cc.exchange_rate, 6)

    def convert(self, amount: float, from_currency: str, to_currency: str) -> float:
        """Convert an amount between currencies."""
        rate = self.get_rate(from_currency, to_currency)
        cc = self._currencies.get(to_currency)
        decimals = cc.decimal_places if cc else 2
        return round(amount * rate, decimals)

    def calculate_fee(self, amount: float, currency: str) -> float:
        """Calculate settlement fee for a currency."""
        fee_rate = self._fees.get(currency, 0.01)
        return round(amount * fee_rate, 2)

    def create_settlement(
        self,
        license_id: str,
        original_currency: str,
        original_amount: float,
        settlement_currency: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SettlementRecord:
        """Create a settlement record, converting to settlement currency."""
        settle_currency = settlement_currency or self.base_currency
        rate = self.get_rate(original_currency, settle_currency)
        settlement_amount = self.convert(original_amount, original_currency, settle_currency)
        fee = self.calculate_fee(settlement_amount, settle_currency)
        net = round(settlement_amount - fee, 2)

        record = SettlementRecord(
            settlement_id=self._next_id(),
            license_id=license_id,
            original_currency=original_currency,
            original_amount=original_amount,
            settlement_currency=settle_currency,
            settlement_amount=settlement_amount,
            exchange_rate=rate,
            fee_amount=fee,
            net_amount=net,
            metadata=metadata or {},
        )
        self._settlements.append(record)
        return record

    def complete_settlement(self, settlement_id: str) -> SettlementRecord:
        """Mark a settlement as completed."""
        for s in self._settlements:
            if s.settlement_id == settlement_id:
                s.status = "completed"
                s.completed_at = datetime.now(timezone.utc)
                return s
        raise ValueError(f"Settlement not found: {settlement_id}")

    def get_settlements(
        self, license_id: str | None = None, status: str | None = None
    ) -> list[SettlementRecord]:
        results = self._settlements
        if license_id:
            results = [s for s in results if s.license_id == license_id]
        if status:
            results = [s for s in results if s.status == status]
        return results

    def get_rate_history(
        self, from_currency: str | None = None, to_currency: str | None = None
    ) -> list[ExchangeRate]:
        results = self._rate_history
        if from_currency:
            results = [r for r in results if r.from_currency == from_currency]
        if to_currency:
            results = [r for r in results if r.to_currency == to_currency]
        return results
