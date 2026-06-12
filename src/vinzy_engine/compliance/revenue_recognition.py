"""License revenue recognition automation.

Tracks revenue events per license, applies recognition rules (immediate,
deferred, usage-based), and produces revenue reports suitable for
financial reporting.
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class RecognitionMethod(str, Enum):
    IMMEDIATE = "immediate"       # recognized at sale
    DEFERRED = "deferred"         # recognized over the license period
    USAGE_BASED = "usage_based"   # recognized as usage occurs
    MILESTONE = "milestone"       # recognized at activation milestones


class RevenueStatus(str, Enum):
    PENDING = "pending"
    RECOGNIZED = "recognized"
    DEFERRED_PARTIAL = "deferred_partial"
    REFUNDED = "refunded"


@dataclass
class RevenueEntry:
    """A single revenue recognition entry."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    license_id: str = ""
    customer_id: str = ""
    product_code: str = ""
    amount_usd: float = 0.0
    recognized_amount_usd: float = 0.0
    deferred_amount_usd: float = 0.0
    method: RecognitionMethod = RecognitionMethod.IMMEDIATE
    status: RevenueStatus = RevenueStatus.PENDING
    period_start: Optional[float] = None
    period_end: Optional[float] = None
    created_at: float = field(default_factory=time.time)
    recognized_at: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "license_id": self.license_id,
            "customer_id": self.customer_id,
            "product_code": self.product_code,
            "amount_usd": round(self.amount_usd, 2),
            "recognized_amount_usd": round(self.recognized_amount_usd, 2),
            "deferred_amount_usd": round(self.deferred_amount_usd, 2),
            "method": self.method.value,
            "status": self.status.value,
            "created_at": self.created_at,
            "recognized_at": self.recognized_at,
        }


@dataclass
class RevenueReport:
    """Aggregate revenue recognition report."""

    period_start: float = 0.0
    period_end: float = 0.0
    total_revenue_usd: float = 0.0
    recognized_usd: float = 0.0
    deferred_usd: float = 0.0
    refunded_usd: float = 0.0
    entry_count: int = 0
    by_product: dict[str, float] = field(default_factory=dict)
    by_method: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "period_start": self.period_start,
            "period_end": self.period_end,
            "total_revenue_usd": round(self.total_revenue_usd, 2),
            "recognized_usd": round(self.recognized_usd, 2),
            "deferred_usd": round(self.deferred_usd, 2),
            "refunded_usd": round(self.refunded_usd, 2),
            "entry_count": self.entry_count,
            "by_product": {k: round(v, 2) for k, v in self.by_product.items()},
            "by_method": {k: round(v, 2) for k, v in self.by_method.items()},
        }


class RevenueRecognizer:
    """Automates license revenue recognition.

    Supports immediate, deferred (ratably over license period),
    usage-based, and milestone recognition methods.

    Usage:
        recognizer = RevenueRecognizer()
        entry = recognizer.record_sale("lic-1", "cust-1", "TSC", 99.99,
                                        method=RecognitionMethod.DEFERRED,
                                        period_days=365)
        recognizer.recognize_deferred(as_of=time.time())
        report = recognizer.generate_report(start, end)
    """

    def __init__(self, max_entries: int = 100_000) -> None:
        self._entries: dict[str, RevenueEntry] = {}
        self._by_license: dict[str, list[str]] = defaultdict(list)
        self._max_entries = max_entries

    def record_sale(
        self,
        license_id: str,
        customer_id: str,
        product_code: str,
        amount_usd: float,
        method: RecognitionMethod = RecognitionMethod.IMMEDIATE,
        period_days: int = 365,
    ) -> RevenueEntry:
        """Record a license sale for revenue recognition."""
        now = time.time()
        entry = RevenueEntry(
            license_id=license_id,
            customer_id=customer_id,
            product_code=product_code,
            amount_usd=amount_usd,
            method=method,
            period_start=now,
            period_end=now + (period_days * 86400),
        )

        if method == RecognitionMethod.IMMEDIATE:
            entry.recognized_amount_usd = amount_usd
            entry.deferred_amount_usd = 0.0
            entry.status = RevenueStatus.RECOGNIZED
            entry.recognized_at = now
        else:
            entry.recognized_amount_usd = 0.0
            entry.deferred_amount_usd = amount_usd
            entry.status = RevenueStatus.PENDING

        self._entries[entry.id] = entry
        self._by_license[license_id].append(entry.id)
        self._enforce_limit()
        return entry

    def recognize_deferred(self, as_of: Optional[float] = None) -> int:
        """Process deferred revenue recognition up to `as_of` timestamp.

        For DEFERRED entries, recognizes revenue pro-rata based on elapsed time.
        Returns the number of entries updated.
        """
        now = as_of or time.time()
        updated = 0

        for entry in self._entries.values():
            if entry.method != RecognitionMethod.DEFERRED:
                continue
            if entry.status in (RevenueStatus.RECOGNIZED, RevenueStatus.REFUNDED):
                continue
            if entry.period_start is None or entry.period_end is None:
                continue

            total_period = entry.period_end - entry.period_start
            if total_period <= 0:
                continue

            elapsed = min(now - entry.period_start, total_period)
            if elapsed < 0:
                continue

            fraction = elapsed / total_period
            recognized = entry.amount_usd * fraction
            entry.recognized_amount_usd = round(recognized, 2)
            entry.deferred_amount_usd = round(entry.amount_usd - recognized, 2)

            if fraction >= 1.0:
                entry.status = RevenueStatus.RECOGNIZED
                entry.recognized_at = now
            else:
                entry.status = RevenueStatus.DEFERRED_PARTIAL

            updated += 1

        return updated

    def recognize_usage(
        self, license_id: str, usage_fraction: float,
    ) -> int:
        """Recognize revenue based on usage fraction (0.0-1.0) for usage-based entries."""
        updated = 0
        fraction = max(0.0, min(1.0, usage_fraction))

        for entry_id in self._by_license.get(license_id, []):
            entry = self._entries.get(entry_id)
            if entry is None or entry.method != RecognitionMethod.USAGE_BASED:
                continue
            if entry.status in (RevenueStatus.RECOGNIZED, RevenueStatus.REFUNDED):
                continue

            recognized = entry.amount_usd * fraction
            entry.recognized_amount_usd = round(recognized, 2)
            entry.deferred_amount_usd = round(entry.amount_usd - recognized, 2)

            if fraction >= 1.0:
                entry.status = RevenueStatus.RECOGNIZED
                entry.recognized_at = time.time()
            else:
                entry.status = RevenueStatus.DEFERRED_PARTIAL

            updated += 1

        return updated

    def refund(self, entry_id: str) -> bool:
        """Mark a revenue entry as refunded."""
        entry = self._entries.get(entry_id)
        if entry is None:
            return False
        entry.status = RevenueStatus.REFUNDED
        entry.recognized_amount_usd = 0.0
        entry.deferred_amount_usd = 0.0
        return True

    def get_entry(self, entry_id: str) -> Optional[RevenueEntry]:
        return self._entries.get(entry_id)

    def get_entries_for_license(self, license_id: str) -> list[RevenueEntry]:
        ids = self._by_license.get(license_id, [])
        return [self._entries[i] for i in ids if i in self._entries]

    def generate_report(
        self,
        period_start: Optional[float] = None,
        period_end: Optional[float] = None,
    ) -> RevenueReport:
        """Generate a revenue report, optionally filtered by time period."""
        report = RevenueReport(
            period_start=period_start or 0.0,
            period_end=period_end or time.time(),
        )

        by_product: dict[str, float] = defaultdict(float)
        by_method: dict[str, float] = defaultdict(float)

        for entry in self._entries.values():
            if period_start is not None and entry.created_at < period_start:
                continue
            if period_end is not None and entry.created_at > period_end:
                continue

            report.entry_count += 1
            report.total_revenue_usd += entry.amount_usd
            report.recognized_usd += entry.recognized_amount_usd
            report.deferred_usd += entry.deferred_amount_usd

            if entry.status == RevenueStatus.REFUNDED:
                report.refunded_usd += entry.amount_usd

            by_product[entry.product_code] += entry.recognized_amount_usd
            by_method[entry.method.value] += entry.recognized_amount_usd

        report.by_product = dict(by_product)
        report.by_method = dict(by_method)
        return report

    @property
    def stats(self) -> dict[str, Any]:
        total_recognized = sum(e.recognized_amount_usd for e in self._entries.values())
        total_deferred = sum(e.deferred_amount_usd for e in self._entries.values())
        return {
            "total_entries": len(self._entries),
            "total_recognized_usd": round(total_recognized, 2),
            "total_deferred_usd": round(total_deferred, 2),
            "tracked_licenses": len(self._by_license),
        }

    def clear(self) -> None:
        self._entries.clear()
        self._by_license.clear()

    def _enforce_limit(self) -> None:
        if len(self._entries) <= self._max_entries:
            return
        refunded = sorted(
            (e for e in self._entries.values() if e.status == RevenueStatus.REFUNDED),
            key=lambda e: e.created_at,
        )
        to_remove = len(self._entries) - self._max_entries
        for e in refunded[:to_remove]:
            del self._entries[e.id]
