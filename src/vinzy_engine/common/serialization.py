"""Response serialization benchmarking and schema versioning.

Provides:
- Serialization performance measurement (item 79/97)
- Schema versioning with content negotiation (item 88)
"""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from fastapi import Header, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Serialization Benchmarking (items 79 & 97)
# ---------------------------------------------------------------------------

@dataclass
class SerializationMetrics:
    """Accumulated serialization performance metrics."""
    total_calls: int = 0
    total_time_ms: float = 0.0
    min_time_ms: float = float("inf")
    max_time_ms: float = 0.0
    total_bytes: int = 0

    @property
    def avg_time_ms(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return self.total_time_ms / self.total_calls

    @property
    def avg_bytes(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return self.total_bytes / self.total_calls

    @property
    def ops_per_sec(self) -> float:
        if self.total_time_ms == 0:
            return 0.0
        return self.total_calls / (self.total_time_ms / 1000)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_calls": self.total_calls,
            "total_time_ms": round(self.total_time_ms, 4),
            "avg_time_ms": round(self.avg_time_ms, 4),
            "min_time_ms": round(self.min_time_ms, 4) if self.min_time_ms != float("inf") else 0.0,
            "max_time_ms": round(self.max_time_ms, 4),
            "avg_bytes": round(self.avg_bytes, 1),
            "ops_per_sec": round(self.ops_per_sec),
        }


class SerializationBenchmark:
    """Tracks serialization performance for different response types.

    Usage:
        bench = get_serialization_benchmark()
        with bench.measure("validation_response"):
            data = response.model_dump_json()
    """

    def __init__(self):
        self._metrics: dict[str, SerializationMetrics] = {}

    def measure(self, label: str):
        """Context manager that times a serialization operation."""
        return _MeasureContext(self, label)

    def record(self, label: str, elapsed_ms: float, byte_size: int = 0) -> None:
        """Record a measurement directly."""
        if label not in self._metrics:
            self._metrics[label] = SerializationMetrics()
        m = self._metrics[label]
        m.total_calls += 1
        m.total_time_ms += elapsed_ms
        m.min_time_ms = min(m.min_time_ms, elapsed_ms)
        m.max_time_ms = max(m.max_time_ms, elapsed_ms)
        m.total_bytes += byte_size

    def get_metrics(self, label: str | None = None) -> dict[str, Any]:
        """Get metrics for a specific label or all labels."""
        if label is not None:
            m = self._metrics.get(label)
            return m.to_dict() if m else {}
        return {k: v.to_dict() for k, v in self._metrics.items()}

    def reset(self) -> None:
        """Clear all metrics."""
        self._metrics.clear()


class _MeasureContext:
    def __init__(self, bench: SerializationBenchmark, label: str):
        self._bench = bench
        self._label = label
        self._start = 0.0
        self.byte_size = 0

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, *args):
        elapsed_ms = (time.perf_counter() - self._start) * 1000
        self._bench.record(self._label, elapsed_ms, self.byte_size)


_benchmark: SerializationBenchmark | None = None


def get_serialization_benchmark() -> SerializationBenchmark:
    """Get the singleton serialization benchmark."""
    global _benchmark
    if _benchmark is None:
        _benchmark = SerializationBenchmark()
    return _benchmark


def reset_serialization_benchmark() -> None:
    """Reset the singleton (for testing)."""
    global _benchmark
    _benchmark = None


# ---------------------------------------------------------------------------
# Schema Versioning with Content Negotiation (item 88)
# ---------------------------------------------------------------------------

# Version registry: maps (resource_type, version) -> transformer function
_schema_versions: dict[tuple[str, str], Callable[[dict], dict]] = {}

DEFAULT_API_VERSION = "v1"
SUPPORTED_API_VERSIONS = {"v1", "v2"}


def register_schema_version(
    resource_type: str,
    version: str,
    transformer: Callable[[dict], dict],
) -> None:
    """Register a response transformer for a specific resource type and version.

    The transformer receives the v1 (canonical) response dict and returns
    the version-appropriate dict.
    """
    _schema_versions[(resource_type, version)] = transformer


def transform_response(
    resource_type: str,
    version: str,
    data: dict,
) -> dict:
    """Apply version-specific transformation to a response dict.

    If no transformer is registered for the version, returns data as-is (v1 default).
    """
    transformer = _schema_versions.get((resource_type, version))
    if transformer is not None:
        return transformer(data)
    return data


def negotiate_version(
    accept: str | None = None,
    x_api_version: str | None = None,
) -> str:
    """Determine API version from content negotiation headers.

    Priority:
    1. X-Api-Version header (explicit)
    2. Accept header with version parameter (e.g., application/json;version=v2)
    3. Default to v1

    Raises ValueError if requested version is not supported.
    """
    # Check explicit header first
    if x_api_version:
        version = x_api_version.strip().lower()
        if version not in SUPPORTED_API_VERSIONS:
            raise ValueError(
                f"Unsupported API version: {version}. "
                f"Supported: {sorted(SUPPORTED_API_VERSIONS)}"
            )
        return version

    # Parse Accept header for version parameter
    if accept:
        for part in accept.split(","):
            part = part.strip()
            if "version=" in part:
                for param in part.split(";"):
                    param = param.strip()
                    if param.startswith("version="):
                        version = param.split("=", 1)[1].strip().lower()
                        if version in SUPPORTED_API_VERSIONS:
                            return version

    return DEFAULT_API_VERSION


# ---------------------------------------------------------------------------
# Register v2 transformers for key resource types
# ---------------------------------------------------------------------------

def _validation_response_v2(data: dict) -> dict:
    """V2 validation response: flatten license into top-level fields."""
    result = dict(data)
    license_data = result.pop("license", None)
    if license_data:
        result["license_id"] = license_data.get("id")
        result["license_status"] = license_data.get("status")
        result["product_code"] = license_data.get("product_code")
        result["tier"] = license_data.get("tier")
        result["expires_at"] = license_data.get("expires_at")
    result["schema_version"] = "v2"
    return result


def _license_response_v2(data: dict) -> dict:
    """V2 license response: add schema_version marker."""
    result = dict(data)
    result["schema_version"] = "v2"
    return result


# Register them
register_schema_version("validation", "v2", _validation_response_v2)
register_schema_version("license", "v2", _license_response_v2)
