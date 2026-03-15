"""License key format evolution.

Manages transitions between license key formats, supporting:
  - Version tracking and compatibility checks
  - Key re-signing with new HMAC keys
  - Batch key migration planning
  - Format validation for multiple key versions
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class KeyFormat(str, Enum):
    V0 = "v0"  # Original: PRD-XXXXX-...-HHHHH-HHHHH (random first char)
    V1 = "v1"  # Versioned: PRD-VXXXX-...-HHHHH-HHHHH (version-encoded first char)


class MigrationAction(str, Enum):
    RE_SIGN = "re_sign"
    DEPRECATE = "deprecate"
    NO_ACTION = "no_action"


@dataclass
class KeyFormatInfo:
    """Information about a key's format and version."""

    raw_key: str
    detected_format: KeyFormat
    hmac_version: int
    product_prefix: str
    segment_count: int
    is_valid_structure: bool
    needs_migration: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "detected_format": self.detected_format.value,
            "hmac_version": self.hmac_version,
            "product_prefix": self.product_prefix,
            "segment_count": self.segment_count,
            "is_valid_structure": self.is_valid_structure,
            "needs_migration": self.needs_migration,
        }


@dataclass
class MigrationEntry:
    """A planned key migration."""

    license_id: str
    old_key_hash: str
    current_format: KeyFormat
    target_format: KeyFormat
    action: MigrationAction
    reason: str = ""
    migrated: bool = False
    migrated_at: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "license_id": self.license_id,
            "old_key_hash": self.old_key_hash[:12] + "...",
            "current_format": self.current_format.value,
            "target_format": self.target_format.value,
            "action": self.action.value,
            "reason": self.reason,
            "migrated": self.migrated,
        }


@dataclass
class MigrationPlan:
    """Batch key migration plan."""

    entries: list[MigrationEntry] = field(default_factory=list)
    target_version: int = 0
    created_at: float = field(default_factory=time.monotonic)

    @property
    def total(self) -> int:
        return len(self.entries)

    @property
    def pending(self) -> int:
        return sum(1 for e in self.entries if not e.migrated)

    @property
    def completed(self) -> int:
        return sum(1 for e in self.entries if e.migrated)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "pending": self.pending,
            "completed": self.completed,
            "target_version": self.target_version,
            "entries": [e.to_dict() for e in self.entries],
        }


# Expected structure: PRD-XXXXX-XXXXX-XXXXX-XXXXX-XXXXX-HHHHH-HHHHH = 8 segments
_EXPECTED_SEGMENTS = 8
_BASE32_ALPHABET = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")


class KeyFormatEvolver:
    """Manages license key format evolution and migration.

    Usage:
        evolver = KeyFormatEvolver(current_version=1)
        info = evolver.analyze_key("ZUL-ABCDE-...")
        plan = evolver.create_migration_plan(keys_data, target_version=1)
    """

    def __init__(self, current_version: int = 1) -> None:
        self._current_version = current_version
        self._plans: list[MigrationPlan] = []
        self._total_analyzed = 0
        self._total_migrations = 0

    @property
    def current_version(self) -> int:
        return self._current_version

    def analyze_key(self, raw_key: str) -> KeyFormatInfo:
        """Analyze a license key and determine its format."""
        self._total_analyzed += 1
        parts = raw_key.split("-")

        prefix = parts[0] if parts else ""
        segment_count = len(parts)
        is_valid = segment_count == _EXPECTED_SEGMENTS and len(prefix) == 3

        # Validate all segments are base32
        if is_valid:
            for seg in parts[1:]:
                if len(seg) != 5 or not all(c in _BASE32_ALPHABET for c in seg):
                    is_valid = False
                    break

        # Detect format version
        hmac_version = 0
        detected_format = KeyFormat.V0
        if segment_count >= 2 and len(parts[1]) >= 1:
            first_char = parts[1][0]
            idx = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567".find(first_char)
            if idx >= 0:
                hmac_version = idx
                if hmac_version > 0:
                    detected_format = KeyFormat.V1

        needs_migration = (
            is_valid
            and detected_format == KeyFormat.V0
            and self._current_version > 0
        )

        return KeyFormatInfo(
            raw_key=raw_key,
            detected_format=detected_format,
            hmac_version=hmac_version,
            product_prefix=prefix,
            segment_count=segment_count,
            is_valid_structure=is_valid,
            needs_migration=needs_migration,
        )

    def create_migration_plan(
        self,
        keys_data: list[dict[str, Any]],
        target_version: int = 0,
    ) -> MigrationPlan:
        """Create a migration plan for a batch of keys.

        keys_data: list of {license_id, raw_key, key_hash}
        """
        if target_version == 0:
            target_version = self._current_version

        plan = MigrationPlan(target_version=target_version)

        for kd in keys_data:
            raw_key = kd.get("raw_key", "")
            license_id = kd.get("license_id", "")
            key_hash_val = kd.get("key_hash", "")

            if raw_key:
                info = self.analyze_key(raw_key)
            else:
                # Without the raw key, we can only mark for deprecation
                plan.entries.append(MigrationEntry(
                    license_id=license_id,
                    old_key_hash=key_hash_val,
                    current_format=KeyFormat.V0,
                    target_format=KeyFormat.V1 if target_version > 0 else KeyFormat.V0,
                    action=MigrationAction.DEPRECATE,
                    reason="raw_key_unavailable",
                ))
                continue

            if info.hmac_version >= target_version:
                plan.entries.append(MigrationEntry(
                    license_id=license_id,
                    old_key_hash=key_hash_val or hashlib.sha256(raw_key.encode()).hexdigest(),
                    current_format=info.detected_format,
                    target_format=info.detected_format,
                    action=MigrationAction.NO_ACTION,
                    reason="already_current",
                ))
            else:
                plan.entries.append(MigrationEntry(
                    license_id=license_id,
                    old_key_hash=key_hash_val or hashlib.sha256(raw_key.encode()).hexdigest(),
                    current_format=info.detected_format,
                    target_format=KeyFormat.V1 if target_version > 0 else KeyFormat.V0,
                    action=MigrationAction.RE_SIGN,
                    reason=f"upgrade_from_v{info.hmac_version}_to_v{target_version}",
                ))

        self._plans.append(plan)
        return plan

    def mark_migrated(self, entry: MigrationEntry) -> None:
        """Mark a migration entry as completed."""
        entry.migrated = True
        entry.migrated_at = time.monotonic()
        self._total_migrations += 1

    def get_plans(self, limit: int = 50) -> list[MigrationPlan]:
        return self._plans[-limit:]

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "current_version": self._current_version,
            "total_analyzed": self._total_analyzed,
            "total_migrations_completed": self._total_migrations,
            "total_plans": len(self._plans),
        }

    def clear(self) -> None:
        self._plans.clear()
