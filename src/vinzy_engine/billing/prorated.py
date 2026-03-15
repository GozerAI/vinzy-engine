"""Prorated billing for mid-cycle upgrades.

Item 441: Calculate prorated charges when customers upgrade/downgrade mid-cycle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass
class ProratedCharge:
    """A prorated billing charge."""
    license_id: str
    old_plan: str
    new_plan: str
    old_price: float
    new_price: float
    days_remaining: int
    days_in_period: int
    credit_amount: float  # Credit for unused portion of old plan
    charge_amount: float  # Charge for remaining portion of new plan
    net_amount: float     # charge - credit
    effective_date: datetime
    period_end: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


class ProratedBillingEngine:
    """Calculate prorated charges for mid-cycle plan changes."""

    def calculate_proration(
        self,
        license_id: str,
        old_plan: str,
        new_plan: str,
        old_monthly_price: float,
        new_monthly_price: float,
        current_period_start: datetime,
        current_period_end: datetime,
        change_date: datetime | None = None,
    ) -> ProratedCharge:
        """Calculate prorated amount for a plan change."""
        now = change_date or datetime.now(timezone.utc)
        # Ensure tz-aware
        if current_period_start.tzinfo is None:
            current_period_start = current_period_start.replace(tzinfo=timezone.utc)
        if current_period_end.tzinfo is None:
            current_period_end = current_period_end.replace(tzinfo=timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        total_days = max(1, (current_period_end - current_period_start).days)
        days_used = max(0, (now - current_period_start).days)
        days_remaining = max(0, total_days - days_used)

        daily_old = old_monthly_price / total_days
        daily_new = new_monthly_price / total_days

        credit = round(daily_old * days_remaining, 2)
        charge = round(daily_new * days_remaining, 2)
        net = round(charge - credit, 2)

        return ProratedCharge(
            license_id=license_id,
            old_plan=old_plan,
            new_plan=new_plan,
            old_price=old_monthly_price,
            new_price=new_monthly_price,
            days_remaining=days_remaining,
            days_in_period=total_days,
            credit_amount=credit,
            charge_amount=charge,
            net_amount=net,
            effective_date=now,
            period_end=current_period_end,
        )

    def calculate_upgrade_invoice(
        self,
        license_id: str,
        old_plan: str,
        new_plan: str,
        old_monthly_price: float,
        new_monthly_price: float,
        current_period_start: datetime,
        current_period_end: datetime,
    ) -> dict[str, Any]:
        """Generate a complete upgrade invoice with proration."""
        proration = self.calculate_proration(
            license_id, old_plan, new_plan,
            old_monthly_price, new_monthly_price,
            current_period_start, current_period_end,
        )
        return {
            "license_id": license_id,
            "type": "upgrade" if new_monthly_price > old_monthly_price else "downgrade",
            "proration": {
                "credit": proration.credit_amount,
                "charge": proration.charge_amount,
                "net": proration.net_amount,
                "days_remaining": proration.days_remaining,
            },
            "immediate_charge": max(0, proration.net_amount),
            "immediate_credit": abs(min(0, proration.net_amount)),
            "next_period_price": new_monthly_price,
        }
