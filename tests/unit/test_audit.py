"""Tests for the cryptographic audit chain service."""

import pytest

from vinzy_engine.common.config import VinzySettings
from vinzy_engine.common.database import DatabaseManager
from vinzy_engine.audit.service import AuditService
from vinzy_engine.licensing.service import LicensingService


HMAC_KEY = "test-hmac-key-for-unit-tests"


def make_settings(**overrides) -> VinzySettings:
    defaults = {"hmac_key": HMAC_KEY, "db_url": "sqlite+aiosqlite://"}
    defaults.update(overrides)
    return VinzySettings(**defaults)


@pytest.fixture
async def db():
    settings = make_settings()
    manager = DatabaseManager(settings)
    await manager.init()
    await manager.create_all()
    yield manager
    await manager.close()


@pytest.fixture
def audit_svc():
    return AuditService(make_settings())


@pytest.fixture
def licensing_svc():
    return LicensingService(make_settings())


async def _create_license(db, licensing_svc):
    async with db.get_session() as session:
        await licensing_svc.create_product(session, "ZUL", "Zuultimate")
        customer = await licensing_svc.create_customer(
            session, "Test", "test@example.com"
        )
    async with db.get_session() as session:
        lic, raw_key = await licensing_svc.create_license(
            session, "ZUL", customer.id
        )
    return lic, raw_key


class TestRecordEvent:
    async def test_record_first_event(self, db, audit_svc, licensing_svc):
        lic, _ = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            event = await audit_svc.record_event(
                session, lic.id, "license.created", "system",
                {"product_code": "ZUL"},
            )
            assert event.id is not None
            assert event.license_id == lic.id
            assert event.event_type == "license.created"
            assert event.prev_hash is None
            assert event.event_hash is not None
            assert event.signature is not None

    async def test_record_chained_event(self, db, audit_svc, licensing_svc):
        lic, _ = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            first = await audit_svc.record_event(
                session, lic.id, "license.created", "system", {},
            )
            second = await audit_svc.record_event(
                session, lic.id, "license.validated", "system", {},
            )
            assert second.prev_hash == first.event_hash
            assert second.event_hash != first.event_hash

    async def test_event_hash_deterministic(self, db, audit_svc):
        """Same inputs produce same hash."""
        h1 = AuditService._compute_event_hash("license.created", "system", {}, None)
        h2 = AuditService._compute_event_hash("license.created", "system", {}, None)
        assert h1 == h2

    async def test_signature_uses_hmac(self, db, audit_svc, licensing_svc):
        lic, _ = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            event = await audit_svc.record_event(
                session, lic.id, "license.created", "system", {},
            )
            assert len(event.signature) == 64  # SHA-256 hex digest


class TestVerifyChain:
    async def test_verify_intact_chain(self, db, audit_svc, licensing_svc):
        lic, _ = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            await audit_svc.record_event(session, lic.id, "license.created", "system", {})
            await audit_svc.record_event(session, lic.id, "license.validated", "system", {})
            await audit_svc.record_event(session, lic.id, "usage.recorded", "system", {})
        async with db.get_session() as session:
            result = await audit_svc.verify_chain(session, lic.id)
            assert result["valid"] is True
            assert result["events_checked"] == 3
            assert result["break_at"] is None

    async def test_verify_tampered_chain(self, db, audit_svc, licensing_svc):
        lic, _ = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            await audit_svc.record_event(session, lic.id, "license.created", "system", {})
            event2 = await audit_svc.record_event(session, lic.id, "license.validated", "system", {})
            # Tamper with the second event's hash
            event2.event_hash = "0" * 64
            await session.flush()
        async with db.get_session() as session:
            result = await audit_svc.verify_chain(session, lic.id)
            assert result["valid"] is False
            assert result["break_at"] is not None

    async def test_verify_empty_chain(self, db, audit_svc, licensing_svc):
        lic, _ = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            result = await audit_svc.verify_chain(session, lic.id)
            assert result["valid"] is True
            assert result["events_checked"] == 0


class TestGetEvents:
    async def test_get_events_filtered(self, db, audit_svc, licensing_svc):
        lic, _ = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            await audit_svc.record_event(session, lic.id, "license.created", "system", {})
            await audit_svc.record_event(session, lic.id, "license.validated", "system", {})
            await audit_svc.record_event(session, lic.id, "license.validated", "system", {})
        async with db.get_session() as session:
            validated = await audit_svc.get_events(
                session, lic.id, event_type="license.validated"
            )
            assert len(validated) == 2

    async def test_get_events_paginated(self, db, audit_svc, licensing_svc):
        lic, _ = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            for i in range(5):
                await audit_svc.record_event(session, lic.id, "license.validated", "system", {"i": i})
        async with db.get_session() as session:
            page1 = await audit_svc.get_events(session, lic.id, limit=2, offset=0)
            page2 = await audit_svc.get_events(session, lic.id, limit=2, offset=2)
            assert len(page1) == 2
            assert len(page2) == 2
            assert page1[0].id != page2[0].id

    async def test_get_chain_head(self, db, audit_svc, licensing_svc):
        lic, _ = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            await audit_svc.record_event(session, lic.id, "license.created", "system", {})
            last = await audit_svc.record_event(session, lic.id, "license.validated", "system", {})
        async with db.get_session() as session:
            head = await audit_svc.get_chain_head(session, lic.id)
            assert head is not None
            assert head.id == last.id
