"""Offline anomaly detection on cached data.

Runs anomaly detection using only locally cached usage data when the
database is unavailable, leveraging the same statistical engine from
vinzy_engine.anomaly.detector.
"""

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional

from vinzy_engine.anomaly.detector import (
    AnomalyReport,
    compute_baseline,
    detect_anomalies,
)

logger = logging.getLogger(__name__)


@dataclass
class OfflineAnomalyRecord:
    """An anomaly detected while operating offline."""

    license_id: str
    anomaly_type: str
    severity: str
    metric: str
    z_score: float
    baseline_mean: float
    baseline_stddev: float
    observed_value: float
    detected_at: float = field(default_factory=time.monotonic)
    synced: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "license_id": self.license_id, "anomaly_type": self.anomaly_type,
            "severity": self.severity, "metric": self.metric,
            "z_score": self.z_score, "baseline_mean": self.baseline_mean,
            "baseline_stddev": self.baseline_stddev, "observed_value": self.observed_value,
            "detected_at": self.detected_at, "synced": self.synced,
        }


class OfflineAnomalyDetector:
    """Detect anomalies using locally cached usage history.

    Maintains per-license, per-metric rolling windows and runs z-score
    detection identical to the online AnomalyService.
    """

    def __init__(self, window_size: int = 30, min_history: int = 3, max_records: int = 10_000):
        self._window_size = window_size
        self._min_history = min_history
        self._max_records = max_records
        self._history: dict[tuple[str, str], list[float]] = defaultdict(list)
        self._records: list[OfflineAnomalyRecord] = []
        self._total_scanned = 0
        self._total_anomalies = 0

    def observe(self, license_id: str, metric: str, value: float) -> Optional[OfflineAnomalyRecord]:
        """Record an observation and check for anomalies."""
        key = (license_id, metric)
        history = self._history[key]
        self._total_scanned += 1

        record = None
        if len(history) >= self._min_history:
            report = detect_anomalies(value, history, metric)
            if report is not None:
                record = OfflineAnomalyRecord(
                    license_id=license_id, anomaly_type=report.anomaly_type,
                    severity=report.severity, metric=metric, z_score=report.z_score,
                    baseline_mean=report.baseline_mean, baseline_stddev=report.baseline_stddev,
                    observed_value=report.observed_value,
                )
                self._records.append(record)
                self._total_anomalies += 1
                if len(self._records) > self._max_records:
                    self._records = self._records[-self._max_records:]

        history.append(value)
        if len(history) > self._window_size:
            self._history[key] = history[-self._window_size:]

        return record

    def bulk_observe(self, license_id: str, metric: str, values: list[float]) -> list[OfflineAnomalyRecord]:
        """Record multiple observations, returning any anomalies found."""
        return [r for v in values if (r := self.observe(license_id, metric, v)) is not None]

    def seed_history(self, license_id: str, metric: str, values: list[float]) -> None:
        """Pre-populate history for a (license, metric) pair."""
        self._history[(license_id, metric)] = list(values[-self._window_size:])

    def get_anomalies(self, license_id: Optional[str] = None, severity: Optional[str] = None, unsynced_only: bool = False, limit: int = 100) -> list[OfflineAnomalyRecord]:
        """Query stored anomaly records with optional filters."""
        records = self._records
        if license_id is not None:
            records = [r for r in records if r.license_id == license_id]
        if severity is not None:
            records = [r for r in records if r.severity == severity]
        if unsynced_only:
            records = [r for r in records if not r.synced]
        return records[-limit:]

    def get_history(self, license_id: str, metric: str) -> list[float]:
        return list(self._history.get((license_id, metric), []))

    def get_baseline(self, license_id: str, metric: str) -> tuple[float, float]:
        history = self.get_history(license_id, metric)
        if not history:
            return 0.0, 0.0
        return compute_baseline(history, self._window_size)

    def get_unsynced_records(self) -> list[OfflineAnomalyRecord]:
        return [r for r in self._records if not r.synced]

    def mark_synced(self, records: list[OfflineAnomalyRecord]) -> int:
        record_set = set(id(r) for r in records)
        count = 0
        for r in self._records:
            if id(r) in record_set and not r.synced:
                r.synced = True
                count += 1
        return count

    def clear_history(self, license_id: Optional[str] = None) -> None:
        if license_id is None:
            self._history.clear()
        else:
            for k in [k for k in self._history if k[0] == license_id]:
                del self._history[k]

    def clear_records(self) -> None:
        self._records.clear()

    def clear(self) -> None:
        self._history.clear()
        self._records.clear()

    @property
    def stats(self) -> dict[str, Any]:
        return {"tracked_pairs": len(self._history), "total_scanned": self._total_scanned, "total_anomalies": self._total_anomalies, "stored_records": len(self._records), "unsynced_records": len(self.get_unsynced_records()), "max_records": self._max_records, "window_size": self._window_size, "min_history": self._min_history}
