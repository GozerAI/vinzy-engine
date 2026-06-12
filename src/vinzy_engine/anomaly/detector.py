"""Statistical anomaly detection for usage patterns."""

import math
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class AnomalyReport:
    """Result of anomaly detection for a single observation."""
    anomaly_type: str
    severity: str
    metric: str
    z_score: float
    baseline_mean: float
    baseline_stddev: float
    observed_value: float


def compute_baseline(values: list[float], window: int = 30) -> tuple[float, float]:
    """
    Compute mean and standard deviation from a list of values.

    Uses the last `window` values if the list is longer.
    Returns (mean, stddev). If fewer than 2 values, stddev is 0.0.
    """
    if not values:
        return 0.0, 0.0
    recent = values[-window:]
    n = len(recent)
    mean = sum(recent) / n
    if n < 2:
        return mean, 0.0
    variance = sum((x - mean) ** 2 for x in recent) / (n - 1)
    return mean, math.sqrt(variance)


def compute_z_score(value: float, mean: float, stddev: float) -> float:
    """Compute the z-score of a value given mean and stddev.

    When stddev is 0 and value differs from mean, returns 999.0
    (a finite sentinel that is always classified as critical).
    """
    if stddev == 0.0:
        return 0.0 if value == mean else 999.0
    return (value - mean) / stddev


def classify_severity(z_score: float) -> Optional[str]:
    """
    Classify anomaly severity based on z-score.

    abs(z) > 3.0 → "critical"
    abs(z) > 2.0 → "high"
    abs(z) > 1.5 → "medium"
    else → None (not anomalous)
    """
    az = abs(z_score)
    if az > 3.0:
        return "critical"
    if az > 2.0:
        return "high"
    if az > 1.5:
        return "medium"
    return None


def detect_anomalies(
    current: float,
    history: list[float],
    metric: str,
    anomaly_type: str = "usage_spike",
) -> Optional[AnomalyReport]:
    """
    Detect if the current value is anomalous given history.

    Returns AnomalyReport if anomalous, None if normal.
    """
    mean, stddev = compute_baseline(history)
    z = compute_z_score(current, mean, stddev)
    severity = classify_severity(z)

    if severity is None:
        return None

    return AnomalyReport(
        anomaly_type=anomaly_type,
        severity=severity,
        metric=metric,
        z_score=z,
        baseline_mean=mean,
        baseline_stddev=stddev,
        observed_value=current,
    )
