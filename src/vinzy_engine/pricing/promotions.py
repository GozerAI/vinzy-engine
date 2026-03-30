"""Time-limited promotional offers.

Item 309: Create and manage promotional pricing with expiration dates,
usage limits, and eligibility rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class DiscountType(str, Enum):
    PERCENTAGE = "percentage"
    FIXED_AMOUNT = "fixed_amount"
    FREE_TRIAL_EXTENSION = "free_trial_extension"
    BONUS_CREDITS = "bonus_credits"
    TIER_UPGRADE = "tier_upgrade"


class PromoStatus(str, Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    EXHAUSTED = "exhausted"
    DISABLED = "disabled"


@dataclass
class EligibilityRule:
    """Rule determining who can use a promotion."""
    rule_type: str  # tier, tenure_days, usage_min, new_customer, referral
    value: Any = None

    def evaluate(self, context: dict[str, Any]) -> bool:
        if self.rule_type == "tier":
            return context.get("tier") in (self.value if isinstance(self.value, list) else [self.value])
        elif self.rule_type == "tenure_days":
            return context.get("tenure_days", 0) >= self.value
        elif self.rule_type == "usage_min":
            return context.get("total_usage", 0) >= self.value
        elif self.rule_type == "new_customer":
            return context.get("is_new_customer", False) == self.value
        elif self.rule_type == "referral":
            return context.get("has_referral", False) == self.value
        return True


@dataclass
class Promotion:
    """A time-limited promotional offer."""
    promo_id: str
    name: str
    description: str
    discount_type: DiscountType
    discount_value: float  # percentage or fixed amount
    start_date: datetime
    end_date: datetime
    max_redemptions: int = 0  # 0 = unlimited
    current_redemptions: int = 0
    eligible_plans: list[str] = field(default_factory=list)  # empty = all plans
    eligibility_rules: list[EligibilityRule] = field(default_factory=list)
    stackable: bool = False
    promo_code: str = ""
    status: PromoStatus = PromoStatus.ACTIVE
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_active(self) -> bool:
        now = datetime.now(timezone.utc)
        start = self.start_date.replace(tzinfo=timezone.utc) if self.start_date.tzinfo is None else self.start_date
        end = self.end_date.replace(tzinfo=timezone.utc) if self.end_date.tzinfo is None else self.end_date
        return (
            self.status == PromoStatus.ACTIVE
            and start <= now <= end
            and (self.max_redemptions == 0 or self.current_redemptions < self.max_redemptions)
        )

    @property
    def remaining_redemptions(self) -> int | None:
        if self.max_redemptions == 0:
            return None
        return max(0, self.max_redemptions - self.current_redemptions)


@dataclass
class PromoRedemption:
    """Record of a promotion being redeemed."""
    promo_id: str
    license_id: str
    discount_applied: float
    original_price: float
    final_price: float
    redeemed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


class PromotionEngine:
    """Manage time-limited promotional offers."""

    def __init__(self):
        self._promos: dict[str, Promotion] = {}
        self._redemptions: list[PromoRedemption] = []
        self._code_index: dict[str, str] = {}  # code -> promo_id

    def create_promotion(self, promo: Promotion) -> Promotion:
        self._promos[promo.promo_id] = promo
        if promo.promo_code:
            self._code_index[promo.promo_code.upper()] = promo.promo_id
        return promo

    def get_promotion(self, promo_id: str) -> Promotion | None:
        return self._promos.get(promo_id)

    def find_by_code(self, code: str) -> Promotion | None:
        promo_id = self._code_index.get(code.upper())
        if promo_id:
            return self._promos.get(promo_id)
        return None

    def list_active(self) -> list[Promotion]:
        self._update_statuses()
        return [p for p in self._promos.values() if p.is_active]

    def check_eligibility(
        self, promo_id: str, context: dict[str, Any]
    ) -> tuple[bool, str]:
        """Check if a customer is eligible for a promotion."""
        promo = self._promos.get(promo_id)
        if promo is None:
            return False, "Promotion not found"
        if not promo.is_active:
            return False, "Promotion is not active"

        plan_id = context.get("plan_id")
        if promo.eligible_plans and plan_id not in promo.eligible_plans:
            return False, f"Plan {plan_id} not eligible for this promotion"

        for rule in promo.eligibility_rules:
            if not rule.evaluate(context):
                return False, f"Eligibility rule failed: {rule.rule_type}"

        return True, "Eligible"

    def apply_discount(
        self, promo_id: str, original_price: float, context: dict[str, Any]
    ) -> tuple[float, PromoRedemption | None]:
        """Apply a promotional discount. Returns (final_price, redemption_record)."""
        eligible, reason = self.check_eligibility(promo_id, context)
        if not eligible:
            return original_price, None

        promo = self._promos[promo_id]
        if promo.discount_type == DiscountType.PERCENTAGE:
            discount = round(original_price * promo.discount_value / 100, 2)
        elif promo.discount_type == DiscountType.FIXED_AMOUNT:
            discount = min(promo.discount_value, original_price)
        elif promo.discount_type == DiscountType.BONUS_CREDITS:
            discount = 0  # Credits handled separately
        else:
            discount = 0

        final_price = round(max(0, original_price - discount), 2)
        promo.current_redemptions += 1

        redemption = PromoRedemption(
            promo_id=promo_id,
            license_id=context.get("license_id", ""),
            discount_applied=discount,
            original_price=original_price,
            final_price=final_price,
        )
        self._redemptions.append(redemption)

        if promo.max_redemptions > 0 and promo.current_redemptions >= promo.max_redemptions:
            promo.status = PromoStatus.EXHAUSTED

        return final_price, redemption

    def get_redemptions(self, promo_id: str | None = None, license_id: str | None = None) -> list[PromoRedemption]:
        results = self._redemptions
        if promo_id:
            results = [r for r in results if r.promo_id == promo_id]
        if license_id:
            results = [r for r in results if r.license_id == license_id]
        return results

    def disable_promotion(self, promo_id: str) -> None:
        promo = self._promos.get(promo_id)
        if promo:
            promo.status = PromoStatus.DISABLED

    def _update_statuses(self) -> None:
        now = datetime.now(timezone.utc)
        for promo in self._promos.values():
            if promo.status == PromoStatus.ACTIVE:
                end = promo.end_date.replace(tzinfo=timezone.utc) if promo.end_date.tzinfo is None else promo.end_date
                if now > end:
                    promo.status = PromoStatus.EXPIRED
