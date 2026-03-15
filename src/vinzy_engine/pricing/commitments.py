"""Minimum commitment contracts.

Item 287: Enforce minimum spend/usage commitments with true-up billing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class CommitmentType(str, Enum):
    SPEND = "spend"      # Minimum dollar amount
    USAGE = "usage"      # Minimum usage units
    SEATS = "seats"      # Minimum seat count


class CommitmentStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    BREACHED = "breached"
    CANCELLED = "cancelled"


@dataclass
class CommitmentContract:
    """A minimum commitment contract."""
    contract_id: str
    license_id: str
    tenant_id: str | None
    commitment_type: CommitmentType
    minimum_value: float
    period_months: int
    start_date: datetime
    end_date: datetime
    actual_value: float = 0.0
    status: CommitmentStatus = CommitmentStatus.ACTIVE
    true_up_rate: float = 1.0  # multiplier for shortfall billing
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def shortfall(self) -> float:
        return max(0, self.minimum_value - self.actual_value)

    @property
    def fulfillment_pct(self) -> float:
        if self.minimum_value == 0:
            return 100.0
        return round(min(100, (self.actual_value / self.minimum_value) * 100), 2)

    @property
    def is_fulfilled(self) -> bool:
        return self.actual_value >= self.minimum_value

    @property
    def true_up_amount(self) -> float:
        return round(self.shortfall * self.true_up_rate, 2)

    @property
    def is_expired(self) -> bool:
        now = datetime.now(timezone.utc)
        end = self.end_date
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        return now > end


@dataclass
class TrueUpInvoice:
    """Invoice for commitment shortfall."""
    contract_id: str
    license_id: str
    shortfall: float
    rate: float
    amount: float
    period_start: datetime
    period_end: datetime
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class CommitmentEngine:
    """Manage minimum commitment contracts with true-up billing."""

    def __init__(self):
        self._contracts: dict[str, CommitmentContract] = {}
        self._counter = 0

    def _next_id(self) -> str:
        self._counter += 1
        return f"CMT-{self._counter:06d}"

    def create_contract(
        self,
        license_id: str,
        tenant_id: str | None,
        commitment_type: CommitmentType,
        minimum_value: float,
        period_months: int,
        start_date: datetime | None = None,
        true_up_rate: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> CommitmentContract:
        """Create a new commitment contract."""
        from datetime import timedelta
        start = start_date or datetime.now(timezone.utc)
        end = start + timedelta(days=period_months * 30)

        contract = CommitmentContract(
            contract_id=self._next_id(),
            license_id=license_id,
            tenant_id=tenant_id,
            commitment_type=commitment_type,
            minimum_value=minimum_value,
            period_months=period_months,
            start_date=start,
            end_date=end,
            true_up_rate=true_up_rate,
            metadata=metadata or {},
        )
        self._contracts[contract.contract_id] = contract
        return contract

    def record_value(self, contract_id: str, value: float) -> CommitmentContract:
        """Record actual spend/usage against a commitment."""
        contract = self._contracts.get(contract_id)
        if contract is None:
            raise ValueError(f"Unknown contract: {contract_id}")
        contract.actual_value += value
        if contract.actual_value >= contract.minimum_value:
            if contract.status == CommitmentStatus.ACTIVE:
                pass  # Still active until period ends
        return contract

    def check_status(self, contract_id: str) -> CommitmentContract:
        """Check and update contract status."""
        contract = self._contracts.get(contract_id)
        if contract is None:
            raise ValueError(f"Unknown contract: {contract_id}")

        if contract.status == CommitmentStatus.ACTIVE and contract.is_expired:
            if contract.is_fulfilled:
                contract.status = CommitmentStatus.COMPLETED
            else:
                contract.status = CommitmentStatus.BREACHED
        return contract

    def generate_true_up(self, contract_id: str) -> TrueUpInvoice | None:
        """Generate true-up invoice for unfulfilled commitment."""
        contract = self.check_status(contract_id)
        if contract.is_fulfilled or contract.status not in (
            CommitmentStatus.BREACHED, CommitmentStatus.ACTIVE
        ):
            return None

        return TrueUpInvoice(
            contract_id=contract_id,
            license_id=contract.license_id,
            shortfall=contract.shortfall,
            rate=contract.true_up_rate,
            amount=contract.true_up_amount,
            period_start=contract.start_date,
            period_end=contract.end_date,
        )

    def get_contract(self, contract_id: str) -> CommitmentContract | None:
        return self._contracts.get(contract_id)

    def get_contracts(
        self, license_id: str | None = None, status: CommitmentStatus | None = None
    ) -> list[CommitmentContract]:
        contracts = list(self._contracts.values())
        if license_id:
            contracts = [c for c in contracts if c.license_id == license_id]
        if status:
            contracts = [c for c in contracts if c.status == status]
        return contracts

    def cancel_contract(self, contract_id: str) -> CommitmentContract:
        contract = self._contracts.get(contract_id)
        if contract is None:
            raise ValueError(f"Unknown contract: {contract_id}")
        contract.status = CommitmentStatus.CANCELLED
        return contract
