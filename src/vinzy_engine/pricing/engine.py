"""Usage-based pricing engine with graduated, volume, and tiered pricing.

Items: 251 (usage-based pricing), 257 (volume discount tiers),
       260 (annual billing discount), 275 (graduated pricing),
       278 (currency-specific pricing), 281 (bundle pricing).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class BillingCycle(str, Enum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"


class PricingModel(str, Enum):
    FLAT = "flat"
    USAGE_BASED = "usage_based"
    TIERED = "tiered"
    GRADUATED = "graduated"
    VOLUME = "volume"
    PER_UNIT = "per_unit"


@dataclass
class PricingTier:
    """A single tier in a graduated or volume pricing schedule."""
    min_units: int
    max_units: int | None  # None = unlimited
    unit_price: float
    flat_fee: float = 0.0

    def contains(self, units: int) -> bool:
        if self.max_units is None:
            return units >= self.min_units
        return self.min_units <= units <= self.max_units

    def units_in_tier(self, total_units: int) -> int:
        if total_units < self.min_units:
            return 0
        cap = total_units if self.max_units is None else min(total_units, self.max_units)
        return cap - self.min_units + 1


@dataclass
class CurrencyConfig:
    """Currency-specific pricing configuration."""
    code: str  # ISO 4217
    symbol: str
    decimal_places: int = 2
    exchange_rate: float = 1.0  # relative to USD
    rounding_mode: str = "half_up"  # half_up, ceil, floor
    min_charge: float = 0.50

    def convert(self, usd_amount: float) -> float:
        raw = usd_amount * self.exchange_rate
        factor = 10 ** self.decimal_places
        if self.rounding_mode == "ceil":
            return math.ceil(raw * factor) / factor
        elif self.rounding_mode == "floor":
            return math.floor(raw * factor) / factor
        return round(raw, self.decimal_places)


# Default supported currencies
SUPPORTED_CURRENCIES: dict[str, CurrencyConfig] = {
    "USD": CurrencyConfig(code="USD", symbol="$", exchange_rate=1.0),
    "EUR": CurrencyConfig(code="EUR", symbol="€", exchange_rate=0.92),
    "GBP": CurrencyConfig(code="GBP", symbol="£", exchange_rate=0.79),
    "CAD": CurrencyConfig(code="CAD", symbol="C$", exchange_rate=1.36),
    "AUD": CurrencyConfig(code="AUD", symbol="A$", exchange_rate=1.53),
    "JPY": CurrencyConfig(code="JPY", symbol="¥", decimal_places=0, exchange_rate=149.50),
    "BRL": CurrencyConfig(code="BRL", symbol="R$", exchange_rate=4.97),
    "INR": CurrencyConfig(code="INR", symbol="₹", exchange_rate=83.12),
}


@dataclass
class PricingPlan:
    """A complete pricing plan definition."""
    plan_id: str
    name: str
    model: PricingModel
    base_price: float  # USD monthly
    currency: str = "USD"
    billing_cycle: BillingCycle = BillingCycle.MONTHLY
    included_units: int = 0
    overage_price: float = 0.0  # per unit over included
    tiers: list[PricingTier] = field(default_factory=list)
    features: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    # Annual billing discount
    annual_discount_pct: float = 16.67  # ~2 months free
    quarterly_discount_pct: float = 10.0

    def effective_monthly_price(self, cycle: BillingCycle | None = None) -> float:
        cycle = cycle or self.billing_cycle
        if cycle == BillingCycle.ANNUAL:
            return self.base_price * (1 - self.annual_discount_pct / 100)
        elif cycle == BillingCycle.QUARTERLY:
            return self.base_price * (1 - self.quarterly_discount_pct / 100)
        return self.base_price

    def cycle_price(self, cycle: BillingCycle | None = None) -> float:
        cycle = cycle or self.billing_cycle
        monthly = self.effective_monthly_price(cycle)
        if cycle == BillingCycle.ANNUAL:
            return round(monthly * 12, 2)
        elif cycle == BillingCycle.QUARTERLY:
            return round(monthly * 3, 2)
        return round(monthly, 2)


@dataclass
class BundleDefinition:
    """Multi-product bundle pricing."""
    bundle_id: str
    name: str
    product_ids: list[str]
    discount_pct: float  # discount vs buying individually
    base_price_usd: float  # monthly
    features: dict[str, Any] = field(default_factory=dict)

    def individual_total(self, product_prices: dict[str, float]) -> float:
        return sum(product_prices.get(pid, 0) for pid in self.product_ids)

    def savings(self, product_prices: dict[str, float]) -> float:
        return self.individual_total(product_prices) - self.base_price_usd


@dataclass
class LineItem:
    """A single line item in a pricing calculation."""
    description: str
    quantity: float
    unit_price: float
    total: float
    tier_label: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PricingResult:
    """Result of a pricing calculation."""
    plan_id: str
    subtotal: float
    currency: str
    line_items: list[LineItem]
    discount_amount: float = 0.0
    tax_amount: float = 0.0
    total: float = 0.0
    billing_cycle: BillingCycle = BillingCycle.MONTHLY
    calculated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


class UsageBasedPricingEngine:
    """Core pricing engine supporting multiple pricing models.

    Handles: flat, usage-based, tiered, graduated, volume, and per-unit pricing.
    Also handles annual/quarterly billing discounts and currency conversion.
    """

    def __init__(self, currency_configs: dict[str, CurrencyConfig] | None = None):
        self._currencies = currency_configs or dict(SUPPORTED_CURRENCIES)
        self._plans: dict[str, PricingPlan] = {}
        self._bundles: dict[str, BundleDefinition] = {}

    def register_plan(self, plan: PricingPlan) -> None:
        self._plans[plan.plan_id] = plan

    def register_bundle(self, bundle: BundleDefinition) -> None:
        self._bundles[bundle.bundle_id] = bundle

    def get_plan(self, plan_id: str) -> PricingPlan | None:
        return self._plans.get(plan_id)

    def get_bundle(self, bundle_id: str) -> BundleDefinition | None:
        return self._bundles.get(bundle_id)

    def list_plans(self) -> list[PricingPlan]:
        return list(self._plans.values())

    def list_bundles(self) -> list[BundleDefinition]:
        return list(self._bundles.values())

    def calculate_price(
        self,
        plan_id: str,
        units_consumed: float = 0,
        billing_cycle: BillingCycle | None = None,
        currency: str = "USD",
    ) -> PricingResult:
        """Calculate the total price for a plan given usage."""
        plan = self._plans.get(plan_id)
        if plan is None:
            raise ValueError(f"Unknown plan: {plan_id}")

        cycle = billing_cycle or plan.billing_cycle
        line_items: list[LineItem] = []

        # Base subscription fee
        base = plan.cycle_price(cycle)
        if base > 0:
            line_items.append(LineItem(
                description=f"{plan.name} - {cycle.value} subscription",
                quantity=1,
                unit_price=base,
                total=base,
            ))

        # Usage-based charges
        usage_total = 0.0
        if plan.model == PricingModel.FLAT:
            pass  # No usage charges
        elif plan.model == PricingModel.USAGE_BASED:
            usage_total = self._calc_usage_based(plan, units_consumed, line_items)
        elif plan.model == PricingModel.TIERED:
            usage_total = self._calc_tiered(plan, units_consumed, line_items)
        elif plan.model == PricingModel.GRADUATED:
            usage_total = self._calc_graduated(plan, units_consumed, line_items)
        elif plan.model == PricingModel.VOLUME:
            usage_total = self._calc_volume(plan, units_consumed, line_items)
        elif plan.model == PricingModel.PER_UNIT:
            usage_total = self._calc_per_unit(plan, units_consumed, line_items)

        subtotal = base + usage_total

        # Currency conversion
        if currency != "USD":
            cc = self._currencies.get(currency)
            if cc is None:
                raise ValueError(f"Unsupported currency: {currency}")
            subtotal = cc.convert(subtotal)
            for item in line_items:
                item.total = cc.convert(item.total)
                item.unit_price = cc.convert(item.unit_price)

        return PricingResult(
            plan_id=plan_id,
            subtotal=round(subtotal, 2),
            currency=currency,
            line_items=line_items,
            total=round(subtotal, 2),
            billing_cycle=cycle,
        )

    def calculate_bundle_price(
        self,
        bundle_id: str,
        billing_cycle: BillingCycle = BillingCycle.MONTHLY,
        currency: str = "USD",
    ) -> PricingResult:
        """Calculate bundle pricing with discount."""
        bundle = self._bundles.get(bundle_id)
        if bundle is None:
            raise ValueError(f"Unknown bundle: {bundle_id}")

        # Apply cycle discount
        monthly = bundle.base_price_usd
        if billing_cycle == BillingCycle.ANNUAL:
            monthly *= (1 - 16.67 / 100)
            period_total = round(monthly * 12, 2)
        elif billing_cycle == BillingCycle.QUARTERLY:
            monthly *= (1 - 10.0 / 100)
            period_total = round(monthly * 3, 2)
        else:
            period_total = round(monthly, 2)

        line_items = [LineItem(
            description=f"{bundle.name} - {billing_cycle.value}",
            quantity=1,
            unit_price=period_total,
            total=period_total,
            metadata={"products": bundle.product_ids},
        )]

        if currency != "USD":
            cc = self._currencies.get(currency)
            if cc is None:
                raise ValueError(f"Unsupported currency: {currency}")
            period_total = cc.convert(period_total)
            for item in line_items:
                item.total = cc.convert(item.total)
                item.unit_price = cc.convert(item.unit_price)

        return PricingResult(
            plan_id=bundle_id,
            subtotal=period_total,
            currency=currency,
            line_items=line_items,
            total=period_total,
            billing_cycle=billing_cycle,
        )

    def convert_currency(self, amount: float, from_currency: str, to_currency: str) -> float:
        """Convert between two currencies via USD."""
        if from_currency == to_currency:
            return amount
        # Convert to USD first
        from_cc = self._currencies.get(from_currency)
        to_cc = self._currencies.get(to_currency)
        if from_cc is None:
            raise ValueError(f"Unsupported currency: {from_currency}")
        if to_cc is None:
            raise ValueError(f"Unsupported currency: {to_currency}")
        usd = amount / from_cc.exchange_rate
        return to_cc.convert(usd)

    # ── Private calculation methods ──

    def _calc_usage_based(
        self, plan: PricingPlan, units: float, items: list[LineItem]
    ) -> float:
        """Simple usage-based: included units free, overage charged per unit."""
        overage = max(0, units - plan.included_units)
        if overage <= 0:
            return 0.0
        total = round(overage * plan.overage_price, 2)
        items.append(LineItem(
            description=f"Overage: {overage:.0f} units @ ${plan.overage_price}/unit",
            quantity=overage,
            unit_price=plan.overage_price,
            total=total,
        ))
        return total

    def _calc_tiered(
        self, plan: PricingPlan, units: float, items: list[LineItem]
    ) -> float:
        """Tiered: find the tier the total units falls into, apply that rate to ALL units."""
        if not plan.tiers or units <= 0:
            return 0.0
        applicable_tier = plan.tiers[-1]  # default to highest
        for tier in plan.tiers:
            if tier.contains(int(units)):
                applicable_tier = tier
                break
        total = round(units * applicable_tier.unit_price + applicable_tier.flat_fee, 2)
        items.append(LineItem(
            description=f"Tiered: {units:.0f} units @ ${applicable_tier.unit_price}/unit",
            quantity=units,
            unit_price=applicable_tier.unit_price,
            total=total,
            tier_label=f"{applicable_tier.min_units}-{applicable_tier.max_units or '∞'}",
        ))
        return total

    def _calc_graduated(
        self, plan: PricingPlan, units: float, items: list[LineItem]
    ) -> float:
        """Graduated: each tier charges only for units within that tier's range."""
        if not plan.tiers or units <= 0:
            return 0.0
        running_total = 0.0
        remaining = units
        for tier in plan.tiers:
            if remaining <= 0:
                break
            tier_cap = (tier.max_units - tier.min_units + 1) if tier.max_units else remaining
            in_tier = min(remaining, tier_cap)
            tier_cost = round(in_tier * tier.unit_price + tier.flat_fee, 2)
            running_total += tier_cost
            items.append(LineItem(
                description=f"Graduated tier {tier.min_units}-{tier.max_units or '∞'}: {in_tier:.0f} units",
                quantity=in_tier,
                unit_price=tier.unit_price,
                total=tier_cost,
                tier_label=f"{tier.min_units}-{tier.max_units or '∞'}",
            ))
            remaining -= in_tier
        return round(running_total, 2)

    def _calc_volume(
        self, plan: PricingPlan, units: float, items: list[LineItem]
    ) -> float:
        """Volume: all units priced at the tier matching total volume."""
        if not plan.tiers or units <= 0:
            return 0.0
        applicable_tier = plan.tiers[0]
        for tier in plan.tiers:
            if units >= tier.min_units:
                applicable_tier = tier
        total = round(units * applicable_tier.unit_price, 2)
        items.append(LineItem(
            description=f"Volume: {units:.0f} units @ ${applicable_tier.unit_price}/unit",
            quantity=units,
            unit_price=applicable_tier.unit_price,
            total=total,
            tier_label=f"{applicable_tier.min_units}+",
        ))
        return total

    def _calc_per_unit(
        self, plan: PricingPlan, units: float, items: list[LineItem]
    ) -> float:
        """Per-unit: simple multiplication."""
        if units <= 0:
            return 0.0
        total = round(units * plan.overage_price, 2)
        items.append(LineItem(
            description=f"{units:.0f} units @ ${plan.overage_price}/unit",
            quantity=units,
            unit_price=plan.overage_price,
            total=total,
        ))
        return total
