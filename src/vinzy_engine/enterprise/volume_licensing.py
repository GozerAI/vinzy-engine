"""Enterprise volume licensing.

Item 405: Volume license management for enterprise customers.
Item 418: License transfer between enterprise users.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class VolumeLicensePool:
    """A pool of licenses for enterprise volume licensing."""
    pool_id: str
    tenant_id: str
    product_code: str
    tier: str
    total_seats: int
    allocated_seats: int = 0
    reserved_seats: int = 0
    price_per_seat: float = 0.0
    auto_provision: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def available_seats(self) -> int:
        return self.total_seats - self.allocated_seats - self.reserved_seats

    @property
    def utilization_pct(self) -> float:
        if self.total_seats == 0:
            return 0.0
        return round(self.allocated_seats / self.total_seats * 100, 2)


@dataclass
class SeatAllocation:
    """An individual seat allocation from a pool."""
    allocation_id: str
    pool_id: str
    license_id: str
    user_email: str
    allocated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    released_at: datetime | None = None
    active: bool = True


@dataclass
class LicenseTransfer:
    """Record of a license transfer between users."""
    transfer_id: str
    pool_id: str
    from_allocation_id: str
    to_allocation_id: str
    from_email: str
    to_email: str
    reason: str = ""
    transferred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class VolumeLicensingEngine:
    """Manage enterprise volume license pools and seat allocations."""

    def __init__(self):
        self._pools: dict[str, VolumeLicensePool] = {}
        self._allocations: list[SeatAllocation] = []
        self._transfers: list[LicenseTransfer] = []
        self._pool_counter = 0
        self._alloc_counter = 0
        self._transfer_counter = 0

    def _next_pool_id(self) -> str:
        self._pool_counter += 1
        return f"VPOOL-{self._pool_counter:06d}"

    def _next_alloc_id(self) -> str:
        self._alloc_counter += 1
        return f"SEAT-{self._alloc_counter:08d}"

    def _next_transfer_id(self) -> str:
        self._transfer_counter += 1
        return f"XFER-{self._transfer_counter:06d}"

    def create_pool(
        self,
        tenant_id: str,
        product_code: str,
        tier: str,
        total_seats: int,
        price_per_seat: float = 0.0,
        auto_provision: bool = True,
        expires_at: datetime | None = None,
    ) -> VolumeLicensePool:
        pool = VolumeLicensePool(
            pool_id=self._next_pool_id(),
            tenant_id=tenant_id,
            product_code=product_code,
            tier=tier,
            total_seats=total_seats,
            price_per_seat=price_per_seat,
            auto_provision=auto_provision,
            expires_at=expires_at,
        )
        self._pools[pool.pool_id] = pool
        return pool

    def allocate_seat(
        self, pool_id: str, license_id: str, user_email: str
    ) -> SeatAllocation:
        """Allocate a seat from a pool."""
        pool = self._pools.get(pool_id)
        if pool is None:
            raise ValueError(f"Pool not found: {pool_id}")
        if pool.available_seats <= 0:
            raise ValueError(f"No available seats in pool {pool_id}")

        allocation = SeatAllocation(
            allocation_id=self._next_alloc_id(),
            pool_id=pool_id,
            license_id=license_id,
            user_email=user_email,
        )
        pool.allocated_seats += 1
        self._allocations.append(allocation)
        return allocation

    def release_seat(self, allocation_id: str) -> SeatAllocation:
        """Release a seat back to the pool."""
        for alloc in self._allocations:
            if alloc.allocation_id == allocation_id and alloc.active:
                alloc.active = False
                alloc.released_at = datetime.now(timezone.utc)
                pool = self._pools.get(alloc.pool_id)
                if pool:
                    pool.allocated_seats = max(0, pool.allocated_seats - 1)
                return alloc
        raise ValueError(f"Active allocation not found: {allocation_id}")

    def transfer_license(
        self, pool_id: str, from_email: str, to_email: str, to_license_id: str, reason: str = ""
    ) -> LicenseTransfer:
        """Transfer a license from one user to another within the same pool."""
        # Find the current allocation
        from_alloc = None
        for alloc in self._allocations:
            if alloc.pool_id == pool_id and alloc.user_email == from_email and alloc.active:
                from_alloc = alloc
                break
        if from_alloc is None:
            raise ValueError(f"No active allocation for {from_email} in pool {pool_id}")

        # Release old allocation
        from_alloc.active = False
        from_alloc.released_at = datetime.now(timezone.utc)

        # Create new allocation (no seat count change)
        to_alloc = SeatAllocation(
            allocation_id=self._next_alloc_id(),
            pool_id=pool_id,
            license_id=to_license_id,
            user_email=to_email,
        )
        self._allocations.append(to_alloc)

        transfer = LicenseTransfer(
            transfer_id=self._next_transfer_id(),
            pool_id=pool_id,
            from_allocation_id=from_alloc.allocation_id,
            to_allocation_id=to_alloc.allocation_id,
            from_email=from_email,
            to_email=to_email,
            reason=reason,
        )
        self._transfers.append(transfer)
        return transfer

    def resize_pool(self, pool_id: str, new_total: int) -> VolumeLicensePool:
        """Resize a pool (expand or shrink)."""
        pool = self._pools.get(pool_id)
        if pool is None:
            raise ValueError(f"Pool not found: {pool_id}")
        if new_total < pool.allocated_seats:
            raise ValueError(
                f"Cannot shrink pool below allocated seats ({pool.allocated_seats})"
            )
        pool.total_seats = new_total
        return pool

    def get_pool(self, pool_id: str) -> VolumeLicensePool | None:
        return self._pools.get(pool_id)

    def get_pools(self, tenant_id: str | None = None) -> list[VolumeLicensePool]:
        pools = list(self._pools.values())
        if tenant_id:
            pools = [p for p in pools if p.tenant_id == tenant_id]
        return pools

    def get_allocations(self, pool_id: str | None = None, active_only: bool = True) -> list[SeatAllocation]:
        results = self._allocations
        if pool_id:
            results = [a for a in results if a.pool_id == pool_id]
        if active_only:
            results = [a for a in results if a.active]
        return results

    def get_transfers(self, pool_id: str | None = None) -> list[LicenseTransfer]:
        results = self._transfers
        if pool_id:
            results = [t for t in results if t.pool_id == pool_id]
        return results
