"""Activation service — machine activation, deactivation, heartbeat."""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from vinzy_engine.common.config import VinzySettings
from vinzy_engine.common.exceptions import (
    ActivationLimitError,
    LicenseNotFoundError,
    VinzyError,
)
from vinzy_engine.activation.models import MachineModel
from vinzy_engine.licensing.models import LicenseModel
from vinzy_engine.licensing.service import LicensingService


class ActivationService:
    """Machine activation operations."""

    def __init__(self, settings: VinzySettings, licensing: LicensingService, audit_service=None, webhook_service=None):
        self.settings = settings
        self.licensing = licensing
        self.audit_service = audit_service
        self.webhook_service = webhook_service

    async def activate(
        self,
        session: AsyncSession,
        raw_key: str,
        fingerprint: str,
        hostname: str = "",
        platform: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict:
        """Activate a license on a machine."""
        # Validate the license first
        validation = await self.licensing.validate_license(session, raw_key)
        license_obj = await self.licensing.get_license_by_key(session, raw_key)
        if license_obj is None:
            raise LicenseNotFoundError()

        # Check if already activated on this fingerprint
        existing = await session.execute(
            select(MachineModel).where(
                and_(
                    MachineModel.license_id == license_obj.id,
                    MachineModel.fingerprint == fingerprint,
                )
            )
        )
        existing_machine = existing.scalar_one_or_none()
        if existing_machine:
            # Already activated — update heartbeat
            existing_machine.last_heartbeat = datetime.now(timezone.utc)
            existing_machine.hostname = hostname or existing_machine.hostname
            await session.flush()
            return {
                "success": True,
                "machine_id": existing_machine.id,
                "code": "ALREADY_ACTIVATED",
                "message": "Machine already activated",
                "license": validation.get("license"),
            }

        # Check activation limit
        if license_obj.machines_used >= license_obj.machines_limit:
            raise ActivationLimitError()

        # Create machine record
        machine = MachineModel(
            license_id=license_obj.id,
            fingerprint=fingerprint,
            hostname=hostname,
            platform=platform,
            last_heartbeat=datetime.now(timezone.utc),
            metadata_=metadata or {},
        )
        session.add(machine)

        # Increment machines_used
        license_obj.machines_used += 1
        await session.flush()

        # Audit: activation.created
        if self.audit_service:
            await self.audit_service.record_event(
                session, license_obj.id, "activation.created", "system",
                {"fingerprint": fingerprint, "machine_id": machine.id},
            )

        # Webhook: activation.created
        if self.webhook_service:
            await self.webhook_service.dispatch(
                session, "activation.created",
                {"license_id": license_obj.id, "fingerprint": fingerprint,
                 "machine_id": machine.id},
            )

        return {
            "success": True,
            "machine_id": machine.id,
            "code": "ACTIVATED",
            "message": "Machine activated successfully",
            "license": validation.get("license"),
        }

    async def deactivate(
        self,
        session: AsyncSession,
        raw_key: str,
        fingerprint: str,
    ) -> bool:
        """Deactivate a machine from a license."""
        license_obj = await self.licensing.get_license_by_key(session, raw_key)
        if license_obj is None:
            raise LicenseNotFoundError()

        result = await session.execute(
            select(MachineModel).where(
                and_(
                    MachineModel.license_id == license_obj.id,
                    MachineModel.fingerprint == fingerprint,
                )
            )
        )
        machine = result.scalar_one_or_none()
        if machine is None:
            return False

        await session.delete(machine)
        license_obj.machines_used = max(0, license_obj.machines_used - 1)
        await session.flush()

        # Audit: activation.removed
        if self.audit_service:
            await self.audit_service.record_event(
                session, license_obj.id, "activation.removed", "system",
                {"fingerprint": fingerprint},
            )

        # Webhook: activation.removed
        if self.webhook_service:
            await self.webhook_service.dispatch(
                session, "activation.removed",
                {"license_id": license_obj.id, "fingerprint": fingerprint},
            )

        return True

    async def heartbeat(
        self,
        session: AsyncSession,
        raw_key: str,
        fingerprint: str,
        version: str = "",
    ) -> bool:
        """Update heartbeat for an activated machine."""
        license_obj = await self.licensing.get_license_by_key(session, raw_key)
        if license_obj is None:
            raise LicenseNotFoundError()

        result = await session.execute(
            select(MachineModel).where(
                and_(
                    MachineModel.license_id == license_obj.id,
                    MachineModel.fingerprint == fingerprint,
                )
            )
        )
        machine = result.scalar_one_or_none()
        if machine is None:
            return False

        machine.last_heartbeat = datetime.now(timezone.utc)
        if version:
            machine.version = version
        await session.flush()
        return True
