"""Automated expired license cleanup.

Finds expired licenses, archives them, and performs cleanup cycles
with configurable retention policies."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from vinzy_engine.licensing.models import LicenseModel

logger = logging.getLogger(__name__)


class CleanupPolicy(str, Enum):
    """Policy for handling expired licenses."""
    SOFT_DELETE = "soft_delete"
    ARCHIVE = "archive"
    HARD_DELETE = "hard_delete"


@dataclass
class CleanupResult:
    """Result of a cleanup cycle."""
    expired_found: int = 0
    archived: int = 0
    soft_deleted: int = 0
    hard_deleted: int = 0
    errors: list[str] = field(default_factory=list)
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "expired_found": self.expired_found,
            "archived": self.archived,
            "soft_deleted": self.soft_deleted,
            "hard_deleted": self.hard_deleted,
            "errors": self.errors,
            "duration_ms": self.duration_ms,
        }


class LicenseCleanupService:
    """Automated cleanup of expired licenses."""

    def __init__(self, policy: CleanupPolicy = CleanupPolicy.SOFT_DELETE, grace_days: int = 30):
        self._policy = policy
        self._grace_days = grace_days
        self._total_cleaned = 0

    @property
    def policy(self) -> CleanupPolicy:
        return self._policy

    @property
    def total_cleaned(self) -> int:
        return self._total_cleaned

    async def find_expired(self, session: AsyncSession, include_grace: bool = True) -> list[LicenseModel]:
        """Find all expired licenses, optionally respecting grace period."""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=self._grace_days) if include_grace else now
        query = (
            select(LicenseModel)
            .where(
                LicenseModel.is_deleted == False,
                LicenseModel.expires_at.isnot(None),
                LicenseModel.expires_at < cutoff,
            )
            .order_by(LicenseModel.expires_at.asc())
        )
        result = await session.execute(query)
        return list(result.scalars().all())

    async def archive_expired(self, session: AsyncSession, licenses: list[LicenseModel]) -> int:
        """Mark expired licenses as archived via soft-delete with status change."""
        archived = 0
        now = datetime.now(timezone.utc)
        for lic in licenses:
            try:
                lic.status = "expired"
                lic.is_deleted = True
                lic.deleted_at = now
                archived += 1
            except Exception as exc:
                logger.exception("Failed to archive license %s", lic.id)
        if archived:
            await session.flush()
            logger.info("Archived %d expired licenses", archived)
        return archived

    async def cleanup(self, session: AsyncSession) -> CleanupResult:
        """Run a full cleanup cycle."""
        import time
        start = time.monotonic()
        result = CleanupResult()

        try:
            expired = await self.find_expired(session)
            result.expired_found = len(expired)
            if not expired:
                result.duration_ms = round((time.monotonic() - start) * 1000, 2)
                return result

            if self._policy == CleanupPolicy.SOFT_DELETE:
                now = datetime.now(timezone.utc)
                for lic in expired:
                    lic.status = "expired"
                    lic.is_deleted = True
                    lic.deleted_at = now
                    result.soft_deleted += 1
                await session.flush()
            elif self._policy == CleanupPolicy.ARCHIVE:
                result.archived = await self.archive_expired(session, expired)
            elif self._policy == CleanupPolicy.HARD_DELETE:
                for lic in expired:
                    await session.delete(lic)
                    result.hard_deleted += 1
                await session.flush()

            self._total_cleaned += result.expired_found
        except Exception as exc:
            logger.exception("Cleanup cycle failed")
            result.errors.append(str(exc))

        result.duration_ms = round((time.monotonic() - start) * 1000, 2)
        logger.info("Cleanup cycle: found=%d, policy=%s, duration=%.1fms", result.expired_found, self._policy.value, result.duration_ms)
        return result


_cleanup_service: LicenseCleanupService | None = None


def get_license_cleanup_service() -> LicenseCleanupService:
    """Get the singleton cleanup service."""
    global _cleanup_service
    if _cleanup_service is None:
        _cleanup_service = LicenseCleanupService()
    return _cleanup_service


def reset_license_cleanup_service() -> None:
    """Reset singleton (for testing)."""
    global _cleanup_service
    _cleanup_service = None
