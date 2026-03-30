"""Audit service — record, verify, and query the cryptographic event chain."""

import hashlib
import hmac as hmac_mod
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vinzy_engine.common.config import VinzySettings
from vinzy_engine.audit.models import AuditEventModel


class AuditService:
    """Immutable, hash-chained event log per license."""

    def __init__(self, settings: VinzySettings):
        self.settings = settings

    # ── Write ──

    async def record_event(
        self,
        session: AsyncSession,
        license_id: str,
        event_type: str,
        actor: str = "system",
        detail: dict[str, Any] | None = None,
    ) -> AuditEventModel:
        """Append a new event to the license's audit chain."""
        detail = detail or {}

        # Fetch chain head (latest event for this license)
        head = await self.get_chain_head(session, license_id)
        prev_hash = head.event_hash if head else None

        # Compute event_hash = SHA-256 of canonical JSON
        event_hash = self._compute_event_hash(
            event_type, actor, detail, prev_hash,
        )

        # HMAC-SHA256 signature with current key
        signature = self._sign(event_hash)

        event = AuditEventModel(
            license_id=license_id,
            event_type=event_type,
            actor=actor,
            detail=detail,
            prev_hash=prev_hash,
            event_hash=event_hash,
            signature=signature,
        )
        session.add(event)
        await session.flush()
        return event

    # ── Read ──

    async def get_chain_head(
        self, session: AsyncSession, license_id: str,
    ) -> AuditEventModel | None:
        """Return the most recent event for a license."""
        result = await session.execute(
            select(AuditEventModel)
            .where(AuditEventModel.license_id == license_id)
            .order_by(AuditEventModel.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_events(
        self,
        session: AsyncSession,
        license_id: str,
        event_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AuditEventModel]:
        """Paginated event list, newest first."""
        query = (
            select(AuditEventModel)
            .where(AuditEventModel.license_id == license_id)
        )
        if event_type:
            query = query.where(AuditEventModel.event_type == event_type)
        query = (
            query.order_by(AuditEventModel.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await session.execute(query)
        return list(result.scalars().all())

    # ── Verify ──

    async def verify_chain(
        self, session: AsyncSession, license_id: str,
    ) -> dict[str, Any]:
        """Walk the chain oldest→newest, verify hashes and signatures."""
        result = await session.execute(
            select(AuditEventModel)
            .where(AuditEventModel.license_id == license_id)
            .order_by(AuditEventModel.created_at.asc())
        )
        events = list(result.scalars().all())

        if not events:
            return {"valid": True, "events_checked": 0, "break_at": None}

        prev_hash = None
        for event in events:
            # Check prev_hash linkage
            if event.prev_hash != prev_hash:
                return {
                    "valid": False,
                    "events_checked": events.index(event),
                    "break_at": event.id,
                }

            # Recompute event_hash
            expected_hash = self._compute_event_hash(
                event.event_type, event.actor, event.detail, event.prev_hash,
            )
            if event.event_hash != expected_hash:
                return {
                    "valid": False,
                    "events_checked": events.index(event),
                    "break_at": event.id,
                }

            # Verify HMAC signature against keyring (supports rotated keys)
            if not self._verify_signature(event.event_hash, event.signature):
                return {
                    "valid": False,
                    "events_checked": events.index(event),
                    "break_at": event.id,
                }

            prev_hash = event.event_hash

        return {"valid": True, "events_checked": len(events), "break_at": None}

    # ── Internal helpers ──

    @staticmethod
    def _compute_event_hash(
        event_type: str,
        actor: str,
        detail: dict[str, Any],
        prev_hash: str | None,
    ) -> str:
        """SHA-256 of canonical JSON of the event fields."""
        canonical = json.dumps(
            {
                "event_type": event_type,
                "actor": actor,
                "detail": detail,
                "prev_hash": prev_hash,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    def _sign(self, event_hash: str) -> str:
        """HMAC-SHA256 of event_hash with the current HMAC key."""
        return hmac_mod.new(
            self.settings.current_hmac_key.encode(),
            event_hash.encode(),
            hashlib.sha256,
        ).hexdigest()

    def _verify_signature(self, event_hash: str, signature: str) -> bool:
        """Verify signature against all keys in the keyring."""
        for _version, key in self.settings.hmac_keyring.items():
            expected = hmac_mod.new(
                key.encode(), event_hash.encode(), hashlib.sha256,
            ).hexdigest()
            if hmac_mod.compare_digest(expected, signature):
                return True
        return False
