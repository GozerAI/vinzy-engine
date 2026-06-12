"""Custom enterprise pricing calculator.

Item 266: Calculate custom pricing for enterprise deals based on
volume, commitment, features, and support level.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EnterpriseQuoteRequest:
    """Input for enterprise pricing calculation."""
    company_name: str
    estimated_users: int
    estimated_monthly_usage: int  # AI credits
    products: list[str]  # product codes
    commitment_months: int = 12
    support_level: str = "standard"  # standard, premium, dedicated
    sla_tier: str = "standard"  # standard, enhanced, mission_critical
    custom_features: list[str] = field(default_factory=list)
    payment_terms: str = "net30"  # net30, net60, net90, prepaid


@dataclass
class EnterpriseQuoteLine:
    description: str
    quantity: int
    unit_price: float
    total: float
    discount_pct: float = 0.0
    notes: str = ""


@dataclass
class EnterpriseQuote:
    """Output of enterprise pricing calculation."""
    quote_id: str
    company_name: str
    lines: list[EnterpriseQuoteLine]
    subtotal: float
    total_discount: float
    total_monthly: float
    total_annual: float
    commitment_months: int
    commitment_total: float
    support_level: str
    sla_tier: str
    notes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


# Support level pricing (monthly per user)
SUPPORT_PRICING = {
    "standard": 0,
    "premium": 15,
    "dedicated": 50,
}

# SLA tier multipliers
SLA_MULTIPLIERS = {
    "standard": 1.0,
    "enhanced": 1.15,
    "mission_critical": 1.35,
}

# Volume discount brackets (user count -> discount %)
VOLUME_BRACKETS = [
    (1, 9, 0),
    (10, 49, 5),
    (50, 99, 10),
    (100, 249, 15),
    (250, 499, 20),
    (500, 999, 25),
    (1000, None, 30),
]

# Commitment discount (months -> discount %)
COMMITMENT_DISCOUNTS = {
    1: 0,
    3: 5,
    6: 10,
    12: 15,
    24: 20,
    36: 25,
}

# Base per-user pricing per product
PRODUCT_PER_USER_PRICING = {
    "AGW": 25.0,
    "NXS": 20.0,
    "ZUL": 15.0,
    "VNZ": 10.0,
    "CSM": 30.0,
    "STD": 15.0,
    "TS": 12.0,
    "SF": 12.0,
    "BG": 10.0,
    "TP": 10.0,
    "CS": 20.0,
    "ARC": 25.0,
}


class EnterprisePricingCalculator:
    """Calculate custom enterprise pricing based on volume, commitment, and requirements."""

    def __init__(self, quote_counter: int = 0):
        self._counter = quote_counter

    def _next_quote_id(self) -> str:
        self._counter += 1
        return f"ENT-Q-{self._counter:06d}"

    def _volume_discount(self, users: int) -> float:
        for min_u, max_u, discount in VOLUME_BRACKETS:
            if max_u is None and users >= min_u:
                return discount
            if max_u is not None and min_u <= users <= max_u:
                return discount
        return 0

    def _commitment_discount(self, months: int) -> float:
        best = 0
        for threshold, discount in sorted(COMMITMENT_DISCOUNTS.items()):
            if months >= threshold:
                best = discount
        return best

    def calculate(self, request: EnterpriseQuoteRequest) -> EnterpriseQuote:
        """Generate an enterprise pricing quote."""
        lines: list[EnterpriseQuoteLine] = []
        notes: list[str] = []

        # Volume discount
        vol_discount = self._volume_discount(request.estimated_users)
        commit_discount = self._commitment_discount(request.commitment_months)

        # Combined discount (additive, capped at 40%)
        combined_discount = min(vol_discount + commit_discount, 40)

        # Product line items
        product_subtotal = 0.0
        for product_code in request.products:
            base_price = PRODUCT_PER_USER_PRICING.get(product_code, 15.0)
            line_total = base_price * request.estimated_users
            discounted = line_total * (1 - combined_discount / 100)
            lines.append(EnterpriseQuoteLine(
                description=f"{product_code} license ({request.estimated_users} users)",
                quantity=request.estimated_users,
                unit_price=base_price,
                total=round(discounted, 2),
                discount_pct=combined_discount,
            ))
            product_subtotal += discounted

        # Support
        support_per_user = SUPPORT_PRICING.get(request.support_level, 0)
        if support_per_user > 0:
            support_total = support_per_user * request.estimated_users
            lines.append(EnterpriseQuoteLine(
                description=f"{request.support_level.title()} Support ({request.estimated_users} users)",
                quantity=request.estimated_users,
                unit_price=support_per_user,
                total=round(support_total, 2),
            ))
            product_subtotal += support_total

        # SLA multiplier
        sla_mult = SLA_MULTIPLIERS.get(request.sla_tier, 1.0)
        if sla_mult > 1.0:
            sla_surcharge = product_subtotal * (sla_mult - 1.0)
            lines.append(EnterpriseQuoteLine(
                description=f"SLA: {request.sla_tier} tier ({(sla_mult - 1.0) * 100:.0f}% surcharge)",
                quantity=1,
                unit_price=round(sla_surcharge, 2),
                total=round(sla_surcharge, 2),
            ))
            product_subtotal += sla_surcharge

        # Usage credits
        if request.estimated_monthly_usage > 0:
            credit_rate = 0.012  # per AI credit
            usage_cost = request.estimated_monthly_usage * credit_rate
            lines.append(EnterpriseQuoteLine(
                description=f"AI credits ({request.estimated_monthly_usage:,}/month)",
                quantity=request.estimated_monthly_usage,
                unit_price=credit_rate,
                total=round(usage_cost, 2),
            ))
            product_subtotal += usage_cost

        total_monthly = round(product_subtotal, 2)
        total_annual = round(total_monthly * 12, 2)
        commitment_total = round(total_monthly * request.commitment_months, 2)

        # Discount amount
        raw_total = sum(
            PRODUCT_PER_USER_PRICING.get(p, 15.0) * request.estimated_users
            for p in request.products
        )
        total_discount = round(raw_total - product_subtotal + (raw_total * (sla_mult - 1.0) if sla_mult > 1.0 else 0), 2)

        if vol_discount > 0:
            notes.append(f"Volume discount: {vol_discount}% ({request.estimated_users} users)")
        if commit_discount > 0:
            notes.append(f"Commitment discount: {commit_discount}% ({request.commitment_months} months)")
        if request.payment_terms == "prepaid":
            notes.append("Additional 5% discount for prepaid commitment")
            total_monthly *= 0.95
            commitment_total = round(total_monthly * request.commitment_months, 2)

        return EnterpriseQuote(
            quote_id=self._next_quote_id(),
            company_name=request.company_name,
            lines=lines,
            subtotal=round(sum(l.total for l in lines), 2),
            total_discount=max(0, total_discount),
            total_monthly=round(total_monthly, 2),
            total_annual=round(total_monthly * 12, 2),
            commitment_months=request.commitment_months,
            commitment_total=commitment_total,
            support_level=request.support_level,
            sla_tier=request.sla_tier,
            notes=notes,
        )
