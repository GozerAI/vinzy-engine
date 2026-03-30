"""Per-feature usage metering.

Item 269: Track usage per feature with configurable metering rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class MeterType(str, Enum):
    COUNTER = "counter"        # Monotonically increasing count
    GAUGE = "gauge"            # Current value (e.g., active seats)
    HISTOGRAM = "histogram"    # Distribution of values
    RATE = "rate"              # Events per time window


class AggregationMethod(str, Enum):
    SUM = "sum"
    MAX = "max"
    AVERAGE = "average"
    LAST = "last"
    P95 = "p95"
    P99 = "p99"


@dataclass
class MeterDefinition:
    """Definition of a metered feature."""
    meter_id: str
    feature: str
    meter_type: MeterType
    aggregation: AggregationMethod = AggregationMethod.SUM
    unit_name: str = "units"
    billable: bool = True
    rate_per_unit: float = 0.0
    included_free: float = 0.0
    reset_period: str = "monthly"  # monthly, daily, never
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MeterReading:
    """A single metered reading."""
    meter_id: str
    license_id: str
    value: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MeterSummary:
    """Aggregated meter summary for a period."""
    meter_id: str
    license_id: str
    feature: str
    total_value: float
    reading_count: int
    billable_value: float
    estimated_charge: float
    period_start: datetime
    period_end: datetime
    unit_name: str = "units"


class FeatureUsageMeter:
    """Track and aggregate per-feature usage with configurable metering."""

    def __init__(self):
        self._meters: dict[str, MeterDefinition] = {}
        self._readings: list[MeterReading] = []

    def define_meter(self, meter: MeterDefinition) -> None:
        self._meters[meter.meter_id] = meter

    def get_meter(self, meter_id: str) -> MeterDefinition | None:
        return self._meters.get(meter_id)

    def list_meters(self) -> list[MeterDefinition]:
        return list(self._meters.values())

    def record(
        self,
        meter_id: str,
        license_id: str,
        value: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> MeterReading:
        """Record a meter reading."""
        meter = self._meters.get(meter_id)
        if meter is None:
            raise ValueError(f"Unknown meter: {meter_id}")

        reading = MeterReading(
            meter_id=meter_id,
            license_id=license_id,
            value=value,
            metadata=metadata or {},
        )
        self._readings.append(reading)
        return reading

    def get_readings(
        self,
        meter_id: str,
        license_id: str,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[MeterReading]:
        """Get readings for a meter and license, optionally filtered by time."""
        results = [
            r for r in self._readings
            if r.meter_id == meter_id and r.license_id == license_id
        ]
        if since:
            results = [r for r in results if r.timestamp >= since]
        if until:
            results = [r for r in results if r.timestamp <= until]
        return results

    def aggregate(
        self,
        meter_id: str,
        license_id: str,
        period_start: datetime,
        period_end: datetime,
    ) -> MeterSummary:
        """Aggregate readings for a meter in a billing period."""
        meter = self._meters.get(meter_id)
        if meter is None:
            raise ValueError(f"Unknown meter: {meter_id}")

        readings = self.get_readings(meter_id, license_id, period_start, period_end)
        values = [r.value for r in readings]

        if not values:
            total = 0.0
        elif meter.aggregation == AggregationMethod.SUM:
            total = sum(values)
        elif meter.aggregation == AggregationMethod.MAX:
            total = max(values)
        elif meter.aggregation == AggregationMethod.AVERAGE:
            total = sum(values) / len(values)
        elif meter.aggregation == AggregationMethod.LAST:
            total = values[-1]
        elif meter.aggregation == AggregationMethod.P95:
            sorted_vals = sorted(values)
            idx = int(len(sorted_vals) * 0.95)
            total = sorted_vals[min(idx, len(sorted_vals) - 1)]
        elif meter.aggregation == AggregationMethod.P99:
            sorted_vals = sorted(values)
            idx = int(len(sorted_vals) * 0.99)
            total = sorted_vals[min(idx, len(sorted_vals) - 1)]
        else:
            total = sum(values)

        billable = max(0, total - meter.included_free)
        charge = round(billable * meter.rate_per_unit, 2) if meter.billable else 0.0

        return MeterSummary(
            meter_id=meter_id,
            license_id=license_id,
            feature=meter.feature,
            total_value=total,
            reading_count=len(readings),
            billable_value=billable,
            estimated_charge=charge,
            period_start=period_start,
            period_end=period_end,
            unit_name=meter.unit_name,
        )

    def get_all_summaries(
        self,
        license_id: str,
        period_start: datetime,
        period_end: datetime,
    ) -> list[MeterSummary]:
        """Get summaries for all meters for a license."""
        summaries = []
        for meter_id in self._meters:
            readings = self.get_readings(meter_id, license_id, period_start, period_end)
            if readings:
                summaries.append(self.aggregate(meter_id, license_id, period_start, period_end))
        return summaries

    def estimate_charges(
        self,
        license_id: str,
        period_start: datetime,
        period_end: datetime,
    ) -> float:
        """Estimate total charges across all meters."""
        summaries = self.get_all_summaries(license_id, period_start, period_end)
        return round(sum(s.estimated_charge for s in summaries), 2)
