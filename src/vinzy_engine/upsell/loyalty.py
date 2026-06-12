"""Loyalty program with tier progression.

Item 315: Loyalty program with tier progression.
Item 319: Renewal incentive automation.
Item 344: Loyalty rewards for long-tenure customers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class LoyaltyTier(str, Enum):
    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"
    PLATINUM = "platinum"
    DIAMOND = "diamond"


# Tier thresholds (cumulative spend in USD)
TIER_THRESHOLDS = {
    LoyaltyTier.BRONZE: 0,
    LoyaltyTier.SILVER: 500,
    LoyaltyTier.GOLD: 2000,
    LoyaltyTier.PLATINUM: 5000,
    LoyaltyTier.DIAMOND: 15000,
}

# Tier benefits
TIER_BENEFITS = {
    LoyaltyTier.BRONZE: {"discount_pct": 0, "bonus_credits_pct": 0, "priority_support": False},
    LoyaltyTier.SILVER: {"discount_pct": 3, "bonus_credits_pct": 5, "priority_support": False},
    LoyaltyTier.GOLD: {"discount_pct": 5, "bonus_credits_pct": 10, "priority_support": True},
    LoyaltyTier.PLATINUM: {"discount_pct": 8, "bonus_credits_pct": 15, "priority_support": True},
    LoyaltyTier.DIAMOND: {"discount_pct": 12, "bonus_credits_pct": 25, "priority_support": True},
}

# Tenure milestones (months) and rewards
TENURE_REWARDS = {
    3: {"type": "bonus_credits", "amount": 100, "description": "3-month loyalty bonus"},
    6: {"type": "bonus_credits", "amount": 250, "description": "6-month loyalty bonus"},
    12: {"type": "discount", "amount": 10, "description": "1-year anniversary: 10% off next renewal"},
    24: {"type": "bonus_credits", "amount": 1000, "description": "2-year loyalty bonus"},
    36: {"type": "discount", "amount": 15, "description": "3-year anniversary: 15% off next renewal"},
}


@dataclass
class LoyaltyMember:
    """A loyalty program member."""
    member_id: str
    license_id: str
    tier: LoyaltyTier = LoyaltyTier.BRONZE
    points: int = 0
    lifetime_spend: float = 0.0
    tenure_months: int = 0
    rewards_claimed: list[str] = field(default_factory=list)
    joined_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def benefits(self) -> dict[str, Any]:
        return dict(TIER_BENEFITS.get(self.tier, {}))

    @property
    def next_tier(self) -> LoyaltyTier | None:
        tiers = list(LoyaltyTier)
        idx = tiers.index(self.tier)
        return tiers[idx + 1] if idx + 1 < len(tiers) else None

    @property
    def spend_to_next_tier(self) -> float | None:
        next_t = self.next_tier
        if next_t is None:
            return None
        threshold = TIER_THRESHOLDS.get(next_t, 0)
        return max(0, threshold - self.lifetime_spend)


@dataclass
class LoyaltyReward:
    """A loyalty reward."""
    reward_id: str
    member_id: str
    reward_type: str  # bonus_credits, discount, free_month, feature_unlock
    amount: float
    description: str
    reason: str  # tenure, spend, referral, promotion
    claimed: bool = False
    claimed_at: datetime | None = None
    expires_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class RenewalIncentive:
    """An automated renewal incentive."""
    incentive_id: str
    license_id: str
    incentive_type: str  # discount, bonus_credits, tier_lock
    value: float
    description: str
    valid_until: datetime
    applied: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class LoyaltyEngine:
    """Manage loyalty program with tier progression and tenure rewards."""

    def __init__(self):
        self._members: dict[str, LoyaltyMember] = {}
        self._rewards: list[LoyaltyReward] = []
        self._incentives: list[RenewalIncentive] = []
        self._member_counter = 0
        self._reward_counter = 0
        self._incentive_counter = 0

    def _next_member_id(self) -> str:
        self._member_counter += 1
        return f"LYL-{self._member_counter:06d}"

    def _next_reward_id(self) -> str:
        self._reward_counter += 1
        return f"RWD-{self._reward_counter:06d}"

    def _next_incentive_id(self) -> str:
        self._incentive_counter += 1
        return f"INC-{self._incentive_counter:06d}"

    def enroll(self, license_id: str) -> LoyaltyMember:
        """Enroll a customer in the loyalty program."""
        # Check if already enrolled
        for m in self._members.values():
            if m.license_id == license_id:
                return m

        member = LoyaltyMember(
            member_id=self._next_member_id(),
            license_id=license_id,
        )
        self._members[member.member_id] = member
        return member

    def record_spend(self, member_id: str, amount: float) -> LoyaltyMember:
        """Record a purchase and update tier if needed."""
        member = self._members.get(member_id)
        if member is None:
            raise ValueError(f"Member not found: {member_id}")

        member.lifetime_spend += amount
        member.points += int(amount)  # 1 point per dollar

        # Check tier advancement
        self._evaluate_tier(member)
        return member

    def update_tenure(self, member_id: str, months: int) -> list[LoyaltyReward]:
        """Update tenure and check for milestone rewards."""
        member = self._members.get(member_id)
        if member is None:
            raise ValueError(f"Member not found: {member_id}")

        old_months = member.tenure_months
        member.tenure_months = months
        new_rewards = []

        for milestone, reward_info in TENURE_REWARDS.items():
            if old_months < milestone <= months:
                reward_key = f"tenure_{milestone}"
                if reward_key not in member.rewards_claimed:
                    reward = LoyaltyReward(
                        reward_id=self._next_reward_id(),
                        member_id=member_id,
                        reward_type=reward_info["type"],
                        amount=reward_info["amount"],
                        description=reward_info["description"],
                        reason="tenure",
                    )
                    self._rewards.append(reward)
                    new_rewards.append(reward)
                    member.rewards_claimed.append(reward_key)

        return new_rewards

    def _evaluate_tier(self, member: LoyaltyMember) -> None:
        """Evaluate and update member tier based on spend."""
        for tier in reversed(list(LoyaltyTier)):
            if member.lifetime_spend >= TIER_THRESHOLDS[tier]:
                if tier != member.tier:
                    old_tier = member.tier
                    member.tier = tier
                    # Award tier-up bonus
                    if list(LoyaltyTier).index(tier) > list(LoyaltyTier).index(old_tier):
                        reward = LoyaltyReward(
                            reward_id=self._next_reward_id(),
                            member_id=member.member_id,
                            reward_type="tier_upgrade",
                            amount=0,
                            description=f"Upgraded from {old_tier.value} to {tier.value}",
                            reason="spend",
                        )
                        self._rewards.append(reward)
                break

    def create_renewal_incentive(
        self,
        license_id: str,
        incentive_type: str,
        value: float,
        description: str,
        valid_until: datetime,
    ) -> RenewalIncentive:
        """Create a renewal incentive for a customer."""
        incentive = RenewalIncentive(
            incentive_id=self._next_incentive_id(),
            license_id=license_id,
            incentive_type=incentive_type,
            value=value,
            description=description,
            valid_until=valid_until,
        )
        self._incentives.append(incentive)
        return incentive

    def generate_renewal_incentives(
        self, member_id: str, renewal_date: datetime
    ) -> list[RenewalIncentive]:
        """Auto-generate renewal incentives based on loyalty tier."""
        member = self._members.get(member_id)
        if member is None:
            raise ValueError(f"Member not found: {member_id}")

        incentives = []
        benefits = member.benefits
        discount = benefits.get("discount_pct", 0)

        if discount > 0:
            inc = self.create_renewal_incentive(
                member.license_id,
                "discount",
                discount,
                f"{member.tier.value} loyalty discount: {discount}% off renewal",
                renewal_date,
            )
            incentives.append(inc)

        bonus_pct = benefits.get("bonus_credits_pct", 0)
        if bonus_pct > 0:
            inc = self.create_renewal_incentive(
                member.license_id,
                "bonus_credits",
                bonus_pct,
                f"{member.tier.value} bonus: {bonus_pct}% extra credits on renewal",
                renewal_date,
            )
            incentives.append(inc)

        return incentives

    def get_member(self, member_id: str) -> LoyaltyMember | None:
        return self._members.get(member_id)

    def get_member_by_license(self, license_id: str) -> LoyaltyMember | None:
        for m in self._members.values():
            if m.license_id == license_id:
                return m
        return None

    def get_rewards(self, member_id: str | None = None) -> list[LoyaltyReward]:
        if member_id:
            return [r for r in self._rewards if r.member_id == member_id]
        return list(self._rewards)

    def claim_reward(self, reward_id: str) -> LoyaltyReward:
        for r in self._rewards:
            if r.reward_id == reward_id:
                r.claimed = True
                r.claimed_at = datetime.now(timezone.utc)
                return r
        raise ValueError(f"Reward not found: {reward_id}")

    def get_incentives(self, license_id: str | None = None) -> list[RenewalIncentive]:
        if license_id:
            return [i for i in self._incentives if i.license_id == license_id]
        return list(self._incentives)
