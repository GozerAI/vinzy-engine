"""Comprehensive tests for the audit logging module — event creation, chaining,
querying, immutability, and serialization."""

import hashlib
import hmac as hmac_mod
import json
from datetime import datetime, timezone

import pytest

from vinzy_engine.audit.models import AuditEventModel
from vinzy_engine.audit.schemas import AuditChainVerification, AuditEventResponse
from vinzy_engine.audit.service import AuditService
from vinzy_engine.common.config import VinzySettings
from vinzy_engine.common.database import DatabaseManager
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


async def _create_license(db, licensing_svc, product_code="ZUL"):
    async with db.get_session() as session:
        await licensing_svc.create_product(session, product_code, f"Product-{product_code}")
        customer = await licensing_svc.create_customer(
            session, "Test User", "test@example.com"
        )
    async with db.get_session() as session:
        lic, raw_key = await licensing_svc.create_license(
            session, product_code, customer.id
        )
    return lic, raw_key


# ── Event Creation ──


class TestAuditEventCreation:
    """Test audit event creation with all required fields."""

    async def test_event_has_all_required_fields(self, db, audit_svc, licensing_svc):
        lic, _ = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            event = await audit_svc.record_event(
                session, lic.id, "license.created", "admin-user",
                {"product_code": "ZUL"},
            )
            assert event.id is not None
            assert event.license_id == lic.id
            assert event.event_type == "license.created"
            assert event.actor == "admin-user"
            assert event.detail == {"product_code": "ZUL"}
            assert event.event_hash is not None
            assert event.signature is not None
            assert event.created_at is not None

    async def test_event_default_actor_is_system(self, db, audit_svc, licensing_svc):
        lic, _ = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            event = await audit_svc.record_event(
                session, lic.id, "license.created"
            )
            assert event.actor == "system"

    async def test_event_default_detail_is_empty_dict(self, db, audit_svc, licensing_svc):
        lic, _ = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            event = await audit_svc.record_event(
                session, lic.id, "license.created"
            )
            assert event.detail == {}

    async def test_event_id_is_uuid_format(self, db, audit_svc, licensing_svc):
        lic, _ = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            event = await audit_svc.record_event(
                session, lic.id, "license.created"
            )
            # UUID4 is 36 chars with hyphens
            assert len(event.id) == 36
            assert event.id.count("-") == 4


# ── Event Types ──


class TestAuditEventTypes:
    """Test various event types are stored correctly."""

    @pytest.mark.parametrize("event_type", [
        "license.created",
        "license.validated",
        "license.updated",
        "license.deleted",
        "usage.recorded",
        "activation.created",
        "activation.revoked",
        "key.generated",
    ])
    async def test_event_type_stored_correctly(
        self, db, audit_svc, licensing_svc, event_type
    ):
        lic, _ = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            event = await audit_svc.record_event(
                session, lic.id, event_type
            )
            assert event.event_type == event_type

    async def test_different_event_types_produce_different_hashes(
        self, db, audit_svc
    ):
        h1 = AuditService._compute_event_hash("license.created", "system", {}, None)
        h2 = AuditService._compute_event_hash("license.validated", "system", {}, None)
        assert h1 != h2


# ── Timestamp Accuracy ──


class TestTimestampAccuracy:
    """Test that timestamps are set correctly."""

    async def test_created_at_is_set(self, db, audit_svc, licensing_svc):
        before = datetime.now(timezone.utc)
        lic, _ = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            event = await audit_svc.record_event(
                session, lic.id, "license.created"
            )
        after = datetime.now(timezone.utc)
        created = event.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        assert before <= created <= after

    async def test_events_are_ordered_by_creation_time(
        self, db, audit_svc, licensing_svc
    ):
        lic, _ = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            e1 = await audit_svc.record_event(session, lic.id, "license.created")
            e2 = await audit_svc.record_event(session, lic.id, "license.validated")
            e3 = await audit_svc.record_event(session, lic.id, "usage.recorded")
        async with db.get_session() as session:
            events = await audit_svc.get_events(session, lic.id)
            # Newest first
            assert events[0].id == e3.id
            assert events[2].id == e1.id


# ── Actor Identification ──


class TestActorIdentification:
    """Test actor identification — user_id, service, system."""

    async def test_actor_user_id(self, db, audit_svc, licensing_svc):
        lic, _ = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            event = await audit_svc.record_event(
                session, lic.id, "license.created", actor="user:12345"
            )
            assert event.actor == "user:12345"

    async def test_actor_service(self, db, audit_svc, licensing_svc):
        lic, _ = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            event = await audit_svc.record_event(
                session, lic.id, "license.validated", actor="service:provisioning"
            )
            assert event.actor == "service:provisioning"

    async def test_actor_system_default(self, db, audit_svc, licensing_svc):
        lic, _ = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            event = await audit_svc.record_event(
                session, lic.id, "usage.recorded"
            )
            assert event.actor == "system"

    async def test_different_actors_produce_different_hashes(self, db, audit_svc):
        h1 = AuditService._compute_event_hash("license.created", "admin", {}, None)
        h2 = AuditService._compute_event_hash("license.created", "system", {}, None)
        assert h1 != h2


# ── Resource Identification ──


class TestResourceIdentification:
    """Test that events are correctly linked to license resources."""

    async def test_event_linked_to_license(self, db, audit_svc, licensing_svc):
        lic, _ = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            event = await audit_svc.record_event(
                session, lic.id, "license.created"
            )
            assert event.license_id == lic.id

    async def test_events_scoped_to_license(self, db, audit_svc, licensing_svc):
        """Events for license A should not appear when querying license B."""
        lic_a, _ = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            await audit_svc.record_event(session, lic_a.id, "license.created")
            await audit_svc.record_event(session, lic_a.id, "license.validated")
        # Create second license with different product code
        async with db.get_session() as session:
            await licensing_svc.create_product(session, "TSC", "Trendscope")
            customer = await licensing_svc.create_customer(
                session, "User B", "b@example.com"
            )
        async with db.get_session() as session:
            lic_b, _ = await licensing_svc.create_license(
                session, "TSC", customer.id
            )
        async with db.get_session() as session:
            await audit_svc.record_event(session, lic_b.id, "license.created")
        async with db.get_session() as session:
            events_a = await audit_svc.get_events(session, lic_a.id)
            events_b = await audit_svc.get_events(session, lic_b.id)
            assert len(events_a) == 2
            assert len(events_b) == 1
            assert all(e.license_id == lic_a.id for e in events_a)
            assert all(e.license_id == lic_b.id for e in events_b)


# ── Event Metadata/Payload Storage ──


class TestEventMetadata:
    """Test that event detail/payload is stored correctly."""

    async def test_empty_detail(self, db, audit_svc, licensing_svc):
        lic, _ = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            event = await audit_svc.record_event(session, lic.id, "license.created")
            assert event.detail == {}

    async def test_simple_detail(self, db, audit_svc, licensing_svc):
        lic, _ = await _create_license(db, licensing_svc)
        detail = {"product_code": "ZUL", "tier": "pro"}
        async with db.get_session() as session:
            event = await audit_svc.record_event(
                session, lic.id, "license.created", detail=detail
            )
            assert event.detail == detail

    async def test_nested_detail(self, db, audit_svc, licensing_svc):
        lic, _ = await _create_license(db, licensing_svc)
        detail = {
            "product_code": "ZUL",
            "entitlements": {"tokens": {"limit": 1000}, "api-calls": {"limit": 500}},
            "tags": ["production", "premium"],
        }
        async with db.get_session() as session:
            event = await audit_svc.record_event(
                session, lic.id, "license.created", detail=detail
            )
            assert event.detail == detail
            assert event.detail["entitlements"]["tokens"]["limit"] == 1000

    async def test_detail_with_numeric_values(self, db, audit_svc, licensing_svc):
        lic, _ = await _create_license(db, licensing_svc)
        detail = {"value": 42.5, "count": 100, "enabled": True}
        async with db.get_session() as session:
            event = await audit_svc.record_event(
                session, lic.id, "usage.recorded", detail=detail
            )
            assert event.detail["value"] == 42.5
            assert event.detail["count"] == 100

    async def test_detail_included_in_hash(self, db, audit_svc):
        h1 = AuditService._compute_event_hash(
            "license.created", "system", {"key": "val1"}, None
        )
        h2 = AuditService._compute_event_hash(
            "license.created", "system", {"key": "val2"}, None
        )
        assert h1 != h2


# ── Query Audit Trail by Resource ──


class TestQueryByResource:
    """Test querying audit trail by license_id (resource)."""

    async def test_get_events_for_license(self, db, audit_svc, licensing_svc):
        lic, _ = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            await audit_svc.record_event(session, lic.id, "license.created")
            await audit_svc.record_event(session, lic.id, "license.validated")
        async with db.get_session() as session:
            events = await audit_svc.get_events(session, lic.id)
            assert len(events) == 2
            assert all(e.license_id == lic.id for e in events)

    async def test_get_events_empty_for_nonexistent_license(
        self, db, audit_svc, licensing_svc
    ):
        async with db.get_session() as session:
            events = await audit_svc.get_events(session, "nonexistent-id")
            assert events == []

    async def test_get_chain_head_returns_latest(self, db, audit_svc, licensing_svc):
        lic, _ = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            await audit_svc.record_event(session, lic.id, "license.created")
            last = await audit_svc.record_event(session, lic.id, "license.validated")
        async with db.get_session() as session:
            head = await audit_svc.get_chain_head(session, lic.id)
            assert head is not None
            assert head.id == last.id

    async def test_get_chain_head_none_for_empty(self, db, audit_svc, licensing_svc):
        lic, _ = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            head = await audit_svc.get_chain_head(session, lic.id)
            assert head is None


# ── Query Audit Trail by Actor ──


class TestQueryByActor:
    """Test querying/filtering events by actor."""

    async def test_events_preserve_actor(self, db, audit_svc, licensing_svc):
        lic, _ = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            await audit_svc.record_event(
                session, lic.id, "license.created", actor="admin"
            )
            await audit_svc.record_event(
                session, lic.id, "license.validated", actor="system"
            )
            await audit_svc.record_event(
                session, lic.id, "usage.recorded", actor="admin"
            )
        async with db.get_session() as session:
            all_events = await audit_svc.get_events(session, lic.id)
            admin_events = [e for e in all_events if e.actor == "admin"]
            system_events = [e for e in all_events if e.actor == "system"]
            assert len(admin_events) == 2
            assert len(system_events) == 1


# ── Query by Date Range ──


class TestQueryByDateRange:
    """Test querying events with pagination to simulate date-range filtering."""

    async def test_paginated_events_offset(self, db, audit_svc, licensing_svc):
        lic, _ = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            for i in range(10):
                await audit_svc.record_event(
                    session, lic.id, "usage.recorded", detail={"i": i}
                )
        async with db.get_session() as session:
            page1 = await audit_svc.get_events(session, lic.id, limit=3, offset=0)
            page2 = await audit_svc.get_events(session, lic.id, limit=3, offset=3)
            page3 = await audit_svc.get_events(session, lic.id, limit=3, offset=6)
            page4 = await audit_svc.get_events(session, lic.id, limit=3, offset=9)
            assert len(page1) == 3
            assert len(page2) == 3
            assert len(page3) == 3
            assert len(page4) == 1
            # All unique events
            all_ids = {e.id for e in page1 + page2 + page3 + page4}
            assert len(all_ids) == 10

    async def test_events_returned_newest_first(self, db, audit_svc, licensing_svc):
        lic, _ = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            e1 = await audit_svc.record_event(
                session, lic.id, "license.created", detail={"order": 1}
            )
            e2 = await audit_svc.record_event(
                session, lic.id, "license.validated", detail={"order": 2}
            )
        async with db.get_session() as session:
            events = await audit_svc.get_events(session, lic.id)
            assert events[0].id == e2.id  # newest first
            assert events[1].id == e1.id


# ── Audit Log Immutability (Chain Integrity) ──


class TestAuditLogImmutability:
    """Test that the hash chain detects tampering."""

    async def test_intact_chain_verifies(self, db, audit_svc, licensing_svc):
        lic, _ = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            await audit_svc.record_event(session, lic.id, "license.created")
            await audit_svc.record_event(session, lic.id, "license.validated")
            await audit_svc.record_event(session, lic.id, "usage.recorded")
        async with db.get_session() as session:
            result = await audit_svc.verify_chain(session, lic.id)
            assert result["valid"] is True
            assert result["events_checked"] == 3

    async def test_tampered_hash_detected(self, db, audit_svc, licensing_svc):
        lic, _ = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            await audit_svc.record_event(session, lic.id, "license.created")
            e2 = await audit_svc.record_event(session, lic.id, "license.validated")
            e2.event_hash = "a" * 64
            await session.flush()
        async with db.get_session() as session:
            result = await audit_svc.verify_chain(session, lic.id)
            assert result["valid"] is False
            assert result["break_at"] is not None

    async def test_tampered_prev_hash_detected(self, db, audit_svc, licensing_svc):
        lic, _ = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            await audit_svc.record_event(session, lic.id, "license.created")
            e2 = await audit_svc.record_event(session, lic.id, "license.validated")
            e2.prev_hash = "b" * 64
            await session.flush()
        async with db.get_session() as session:
            result = await audit_svc.verify_chain(session, lic.id)
            assert result["valid"] is False

    async def test_tampered_signature_detected(self, db, audit_svc, licensing_svc):
        lic, _ = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            e1 = await audit_svc.record_event(session, lic.id, "license.created")
            e1.signature = "c" * 64
            await session.flush()
        async with db.get_session() as session:
            result = await audit_svc.verify_chain(session, lic.id)
            assert result["valid"] is False

    async def test_first_event_has_no_prev_hash(self, db, audit_svc, licensing_svc):
        lic, _ = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            event = await audit_svc.record_event(session, lic.id, "license.created")
            assert event.prev_hash is None

    async def test_subsequent_events_chain_prev_hash(
        self, db, audit_svc, licensing_svc
    ):
        lic, _ = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            e1 = await audit_svc.record_event(session, lic.id, "license.created")
            e2 = await audit_svc.record_event(session, lic.id, "license.validated")
            e3 = await audit_svc.record_event(session, lic.id, "usage.recorded")
            assert e2.prev_hash == e1.event_hash
            assert e3.prev_hash == e2.event_hash

    async def test_verify_empty_chain_is_valid(self, db, audit_svc, licensing_svc):
        lic, _ = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            result = await audit_svc.verify_chain(session, lic.id)
            assert result["valid"] is True
            assert result["events_checked"] == 0
            assert result["break_at"] is None


# ── Bulk Event Logging ──


class TestBulkEventLogging:
    """Test recording multiple events efficiently."""

    async def test_many_events_in_single_session(self, db, audit_svc, licensing_svc):
        lic, _ = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            for i in range(20):
                await audit_svc.record_event(
                    session, lic.id, "usage.recorded", detail={"i": i}
                )
        async with db.get_session() as session:
            events = await audit_svc.get_events(session, lic.id, limit=50)
            assert len(events) == 20

    async def test_many_events_chain_integrity(self, db, audit_svc, licensing_svc):
        lic, _ = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            for i in range(15):
                await audit_svc.record_event(
                    session, lic.id, "usage.recorded", detail={"i": i}
                )
        async with db.get_session() as session:
            result = await audit_svc.verify_chain(session, lic.id)
            assert result["valid"] is True
            assert result["events_checked"] == 15

    async def test_events_across_multiple_sessions(self, db, audit_svc, licensing_svc):
        lic, _ = await _create_license(db, licensing_svc)
        for i in range(5):
            async with db.get_session() as session:
                await audit_svc.record_event(
                    session, lic.id, "usage.recorded", detail={"batch": i}
                )
        async with db.get_session() as session:
            events = await audit_svc.get_events(session, lic.id, limit=50)
            assert len(events) == 5
        async with db.get_session() as session:
            result = await audit_svc.verify_chain(session, lic.id)
            assert result["valid"] is True


# ── Event Serialization/Deserialization ──


class TestEventSerialization:
    """Test Pydantic schema serialization of audit events."""

    async def test_event_response_schema(self, db, audit_svc, licensing_svc):
        lic, _ = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            event = await audit_svc.record_event(
                session, lic.id, "license.created", actor="admin",
                detail={"product_code": "ZUL"},
            )
            response = AuditEventResponse.model_validate(event)
            assert response.id == event.id
            assert response.license_id == event.license_id
            assert response.event_type == "license.created"
            assert response.actor == "admin"
            assert response.detail == {"product_code": "ZUL"}
            assert response.event_hash == event.event_hash
            assert response.signature == event.signature
            assert isinstance(response.created_at, datetime)

    async def test_chain_verification_schema(self, db, audit_svc, licensing_svc):
        lic, _ = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            await audit_svc.record_event(session, lic.id, "license.created")
        async with db.get_session() as session:
            raw = await audit_svc.verify_chain(session, lic.id)
            verification = AuditChainVerification(**raw)
            assert verification.valid is True
            assert verification.events_checked == 1
            assert verification.break_at is None

    async def test_event_response_json_round_trip(self, db, audit_svc, licensing_svc):
        lic, _ = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            event = await audit_svc.record_event(
                session, lic.id, "license.created", detail={"key": "value"}
            )
            response = AuditEventResponse.model_validate(event)
            json_str = response.model_dump_json()
            restored = AuditEventResponse.model_validate_json(json_str)
            assert restored.id == response.id
            assert restored.event_type == response.event_type
            assert restored.detail == response.detail

    def test_compute_event_hash_is_deterministic(self):
        h1 = AuditService._compute_event_hash(
            "license.created", "system", {"key": "val"}, None
        )
        h2 = AuditService._compute_event_hash(
            "license.created", "system", {"key": "val"}, None
        )
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex digest

    def test_compute_event_hash_is_sha256(self):
        event_type = "license.created"
        actor = "system"
        detail = {"key": "val"}
        prev_hash = None
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
        expected = hashlib.sha256(canonical.encode()).hexdigest()
        actual = AuditService._compute_event_hash(event_type, actor, detail, prev_hash)
        assert actual == expected

    def test_signature_is_hmac_sha256(self):
        svc = AuditService(make_settings())
        event_hash = "a" * 64
        sig = svc._sign(event_hash)
        expected = hmac_mod.new(
            HMAC_KEY.encode(), event_hash.encode(), hashlib.sha256
        ).hexdigest()
        assert sig == expected

    def test_verify_signature_with_correct_key(self):
        svc = AuditService(make_settings())
        event_hash = "b" * 64
        sig = svc._sign(event_hash)
        assert svc._verify_signature(event_hash, sig) is True

    def test_verify_signature_with_wrong_signature(self):
        svc = AuditService(make_settings())
        event_hash = "c" * 64
        assert svc._verify_signature(event_hash, "d" * 64) is False


# ── Filtered Queries ──


class TestFilteredQueries:
    """Test filtering events by event_type."""

    async def test_filter_by_event_type(self, db, audit_svc, licensing_svc):
        lic, _ = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            await audit_svc.record_event(session, lic.id, "license.created")
            await audit_svc.record_event(session, lic.id, "license.validated")
            await audit_svc.record_event(session, lic.id, "license.validated")
            await audit_svc.record_event(session, lic.id, "usage.recorded")
        async with db.get_session() as session:
            validated = await audit_svc.get_events(
                session, lic.id, event_type="license.validated"
            )
            assert len(validated) == 2
            assert all(e.event_type == "license.validated" for e in validated)

    async def test_filter_returns_empty_for_no_match(
        self, db, audit_svc, licensing_svc
    ):
        lic, _ = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            await audit_svc.record_event(session, lic.id, "license.created")
        async with db.get_session() as session:
            events = await audit_svc.get_events(
                session, lic.id, event_type="nonexistent.type"
            )
            assert events == []

    async def test_no_filter_returns_all(self, db, audit_svc, licensing_svc):
        lic, _ = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            await audit_svc.record_event(session, lic.id, "license.created")
            await audit_svc.record_event(session, lic.id, "license.validated")
            await audit_svc.record_event(session, lic.id, "usage.recorded")
        async with db.get_session() as session:
            events = await audit_svc.get_events(session, lic.id)
            assert len(events) == 3
