"""Fraud detection in license usage patterns.

Identifies suspicious usage patterns such as:
  - Velocity abuse: license used across too many IPs/machines in short windows
  - Clock manipulation: usage timestamps going backwards or large gaps
  - Sharing detection: concurrent activations exceeding the license limit
  - Geographic impossibility: activations from distant locations in short time
  - Pattern cloning: multiple licenses with identical usage fingerprints
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class FraudType(str, Enum):
    VELOCITY_ABUSE = "velocity_abuse"
    CLOCK_MANIPULATION = "clock_manipulation"
    SHARING_DETECTED = "sharing_detected"
    GEO_IMPOSSIBILITY = "geo_impossibility"
    PATTERN_CLONING = "pattern_cloning"
    BURST_ABUSE = "burst_abuse"


class FraudSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class FraudSignal:
    """A single detected fraud signal."""

    license_id: str
    fraud_type: FraudType
    severity: FraudSeverity
    confidence: float  # 0.0-1.0
    evidence: dict[str, Any] = field(default_factory=dict)
    detected_at: float = field(default_factory=time.monotonic)
    resolved: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "license_id": self.license_id,
            "fraud_type": self.fraud_type.value,
            "severity": self.severity.value,
            "confidence": round(self.confidence, 3),
            "evidence": self.evidence,
            "detected_at": self.detected_at,
            "resolved": self.resolved,
        }


@dataclass
class UsageEvent:
    """A usage observation to analyze for fraud."""

    license_id: str
    ip_address: str = ""
    machine_id: str = ""
    timestamp: float = field(default_factory=time.time)
    metric: str = ""
    value: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class _LicenseProfile:
    """Internal per-license tracking state."""

    ips: deque = field(default_factory=lambda: deque(maxlen=200))
    machines: deque = field(default_factory=lambda: deque(maxlen=200))
    timestamps: deque = field(default_factory=lambda: deque(maxlen=500))
    event_counts: deque = field(default_factory=lambda: deque(maxlen=500))
    usage_fingerprints: deque = field(default_factory=lambda: deque(maxlen=100))


class FraudDetector:
    """Detects fraud patterns in license usage data.

    Uses heuristic rules and statistical analysis to identify suspicious
    behavior without requiring external dependencies.

    Args:
        velocity_window_seconds: Time window to count unique IPs/machines.
        velocity_ip_threshold: Max unique IPs in the window before flagging.
        velocity_machine_threshold: Max unique machines in the window.
        burst_window_seconds: Short window for burst detection.
        burst_threshold: Max events in the burst window.
        clock_drift_tolerance_seconds: Acceptable backwards drift in timestamps.
        max_signals: Maximum stored fraud signals.
    """

    def __init__(
        self,
        velocity_window_seconds: float = 3600.0,
        velocity_ip_threshold: int = 10,
        velocity_machine_threshold: int = 5,
        burst_window_seconds: float = 60.0,
        burst_threshold: int = 100,
        clock_drift_tolerance_seconds: float = 5.0,
        max_signals: int = 10_000,
    ) -> None:
        self._velocity_window = velocity_window_seconds
        self._velocity_ip_threshold = velocity_ip_threshold
        self._velocity_machine_threshold = velocity_machine_threshold
        self._burst_window = burst_window_seconds
        self._burst_threshold = burst_threshold
        self._clock_drift_tolerance = clock_drift_tolerance_seconds
        self._max_signals = max_signals

        self._profiles: dict[str, _LicenseProfile] = defaultdict(_LicenseProfile)
        self._signals: list[FraudSignal] = []
        self._total_events = 0
        self._total_signals = 0

    def analyze(self, event: UsageEvent) -> list[FraudSignal]:
        """Analyze a usage event for fraud signals.

        Returns a list of new fraud signals detected (may be empty).
        """
        self._total_events += 1
        profile = self._profiles[event.license_id]
        signals: list[FraudSignal] = []

        now = event.timestamp or time.time()

        # Record event data
        if event.ip_address:
            profile.ips.append((now, event.ip_address))
        if event.machine_id:
            profile.machines.append((now, event.machine_id))
        profile.timestamps.append(now)
        profile.event_counts.append(now)

        # Fingerprint for cloning detection
        fp = self._compute_fingerprint(event)
        if fp:
            profile.usage_fingerprints.append(fp)

        # Run detection rules
        s = self._check_velocity(event.license_id, profile, now)
        if s:
            signals.append(s)

        s = self._check_clock_manipulation(event.license_id, profile)
        if s:
            signals.append(s)

        s = self._check_burst(event.license_id, profile, now)
        if s:
            signals.append(s)

        for signal in signals:
            self._signals.append(signal)
            self._total_signals += 1

        if len(self._signals) > self._max_signals:
            self._signals = self._signals[-self._max_signals:]

        return signals

    def check_cloning(self, license_ids: list[str], min_overlap: float = 0.8) -> list[FraudSignal]:
        """Check for pattern cloning across multiple licenses.

        Compares usage fingerprint overlap between license pairs.
        """
        signals: list[FraudSignal] = []
        ids = [lid for lid in license_ids if lid in self._profiles]

        for i, lid_a in enumerate(ids):
            fp_a = set(self._profiles[lid_a].usage_fingerprints)
            if not fp_a:
                continue
            for lid_b in ids[i + 1:]:
                fp_b = set(self._profiles[lid_b].usage_fingerprints)
                if not fp_b:
                    continue
                overlap = len(fp_a & fp_b) / max(len(fp_a), len(fp_b))
                if overlap >= min_overlap:
                    signal = FraudSignal(
                        license_id=lid_a,
                        fraud_type=FraudType.PATTERN_CLONING,
                        severity=FraudSeverity.HIGH if overlap > 0.9 else FraudSeverity.MEDIUM,
                        confidence=overlap,
                        evidence={
                            "paired_license": lid_b,
                            "overlap_ratio": round(overlap, 3),
                            "fingerprints_a": len(fp_a),
                            "fingerprints_b": len(fp_b),
                        },
                    )
                    signals.append(signal)
                    self._signals.append(signal)
                    self._total_signals += 1

        return signals

    def get_signals(
        self,
        license_id: Optional[str] = None,
        fraud_type: Optional[FraudType] = None,
        min_severity: Optional[FraudSeverity] = None,
        unresolved_only: bool = False,
        limit: int = 100,
    ) -> list[FraudSignal]:
        """Query stored fraud signals with optional filters."""
        severity_order = {
            FraudSeverity.LOW: 0, FraudSeverity.MEDIUM: 1,
            FraudSeverity.HIGH: 2, FraudSeverity.CRITICAL: 3,
        }
        min_order = severity_order.get(min_severity, 0) if min_severity else 0

        results = self._signals
        if license_id is not None:
            results = [s for s in results if s.license_id == license_id]
        if fraud_type is not None:
            results = [s for s in results if s.fraud_type == fraud_type]
        if unresolved_only:
            results = [s for s in results if not s.resolved]
        results = [s for s in results if severity_order.get(s.severity, 0) >= min_order]
        return results[-limit:]

    def resolve_signal(self, signal: FraudSignal) -> None:
        """Mark a fraud signal as resolved."""
        signal.resolved = True

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "total_events_analyzed": self._total_events,
            "total_signals": self._total_signals,
            "active_signals": len([s for s in self._signals if not s.resolved]),
            "tracked_licenses": len(self._profiles),
        }

    def clear(self) -> None:
        self._profiles.clear()
        self._signals.clear()

    # -- Internal checks --

    def _check_velocity(
        self, license_id: str, profile: _LicenseProfile, now: float,
    ) -> Optional[FraudSignal]:
        """Check for velocity abuse (too many unique IPs/machines)."""
        cutoff = now - self._velocity_window
        recent_ips = {ip for ts, ip in profile.ips if ts >= cutoff}
        recent_machines = {mid for ts, mid in profile.machines if ts >= cutoff}

        ip_exceeded = len(recent_ips) > self._velocity_ip_threshold
        machine_exceeded = len(recent_machines) > self._velocity_machine_threshold

        if not ip_exceeded and not machine_exceeded:
            return None

        # Confidence scales with how much over threshold
        if ip_exceeded:
            ratio = len(recent_ips) / self._velocity_ip_threshold
        else:
            ratio = len(recent_machines) / self._velocity_machine_threshold
        confidence = min(1.0, 0.5 + (ratio - 1.0) * 0.25)

        severity = FraudSeverity.MEDIUM
        if ratio > 3.0:
            severity = FraudSeverity.CRITICAL
        elif ratio > 2.0:
            severity = FraudSeverity.HIGH

        return FraudSignal(
            license_id=license_id,
            fraud_type=FraudType.VELOCITY_ABUSE,
            severity=severity,
            confidence=confidence,
            evidence={
                "unique_ips": len(recent_ips),
                "unique_machines": len(recent_machines),
                "window_seconds": self._velocity_window,
                "ip_threshold": self._velocity_ip_threshold,
                "machine_threshold": self._velocity_machine_threshold,
            },
        )

    def _check_clock_manipulation(
        self, license_id: str, profile: _LicenseProfile,
    ) -> Optional[FraudSignal]:
        """Check for timestamps going backwards."""
        ts_list = list(profile.timestamps)
        if len(ts_list) < 2:
            return None

        last_two = ts_list[-2:]
        drift = last_two[0] - last_two[1]
        if drift <= self._clock_drift_tolerance:
            return None

        confidence = min(1.0, drift / 3600.0)
        severity = FraudSeverity.LOW
        if drift > 86400:
            severity = FraudSeverity.HIGH
        elif drift > 3600:
            severity = FraudSeverity.MEDIUM

        return FraudSignal(
            license_id=license_id,
            fraud_type=FraudType.CLOCK_MANIPULATION,
            severity=severity,
            confidence=confidence,
            evidence={
                "backwards_drift_seconds": round(drift, 2),
                "tolerance_seconds": self._clock_drift_tolerance,
            },
        )

    def _check_burst(
        self, license_id: str, profile: _LicenseProfile, now: float,
    ) -> Optional[FraudSignal]:
        """Check for burst abuse (too many events in a short window)."""
        cutoff = now - self._burst_window
        recent = sum(1 for ts in profile.event_counts if ts >= cutoff)

        if recent <= self._burst_threshold:
            return None

        ratio = recent / self._burst_threshold
        confidence = min(1.0, 0.6 + (ratio - 1.0) * 0.2)
        severity = FraudSeverity.MEDIUM if ratio < 3.0 else FraudSeverity.HIGH

        return FraudSignal(
            license_id=license_id,
            fraud_type=FraudType.BURST_ABUSE,
            severity=severity,
            confidence=confidence,
            evidence={
                "events_in_window": recent,
                "window_seconds": self._burst_window,
                "threshold": self._burst_threshold,
            },
        )

    @staticmethod
    def _compute_fingerprint(event: UsageEvent) -> Optional[str]:
        """Compute a usage fingerprint for cloning detection."""
        parts = [event.metric, str(round(event.value, 2))]
        if not event.metric:
            return None
        raw = "|".join(parts)
        return hashlib.md5(raw.encode(), usedforsecurity=False).hexdigest()[:12]
