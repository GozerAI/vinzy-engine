"""Tests for webhook service — CRUD, dispatch, signing, delivery lifecycle."""

import asyncio
import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vinzy_engine.client import LicenseClient
from vinzy_engine.common.config import VinzySettings
from vinzy_engine.common.database import DatabaseManager
from vinzy_engine.webhooks.service import (
    VALID_EVENT_TYPES,
    WebhookService,
    sign_payload,
)

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
def webhook_svc():
    return WebhookService(make_settings())


# ── HMAC Signing ──


class TestSignPayload:
    def test_deterministic(self):
        payload = '{"event_type":"license.created","data":{}}'
        secret = "my-webhook-secret-key"
        sig1 = sign_payload(payload, secret)
        sig2 = sign_payload(payload, secret)
        assert sig1 == sig2
        assert len(sig1) == 64  # SHA-256 hex digest

    def test_different_secrets_different_sigs(self):
        payload = '{"event_type":"license.created"}'
        sig1 = sign_payload(payload, "secret-one-abcdef")
        sig2 = sign_payload(payload, "secret-two-ghijkl")
        assert sig1 != sig2

    def test_different_payloads_different_sigs(self):
        secret = "my-webhook-secret-key"
        sig1 = sign_payload('{"a":1}', secret)
        sig2 = sign_payload('{"a":2}', secret)
        assert sig1 != sig2

    def test_matches_manual_hmac(self):
        payload = '{"test":"data"}'
        secret = "test-secret-12345678"
        expected = hmac.new(
            secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        assert sign_payload(payload, secret) == expected


# ── SDK Verification ──


class TestSDKVerifySignature:
    def test_valid_signature(self):
        payload = '{"event_type":"license.created","data":{}}'
        secret = "my-webhook-secret-key"
        sig = sign_payload(payload, secret)
        assert LicenseClient.verify_webhook_signature(payload, sig, secret) is True

    def test_invalid_signature(self):
        payload = '{"event_type":"license.created"}'
        secret = "my-webhook-secret-key"
        assert LicenseClient.verify_webhook_signature(payload, "bad-sig", secret) is False

    def test_wrong_secret(self):
        payload = '{"event_type":"license.created"}'
        secret = "my-webhook-secret-key"
        sig = sign_payload(payload, secret)
        assert LicenseClient.verify_webhook_signature(payload, sig, "wrong-secret-abcdef") is False

    def test_bytes_payload(self):
        payload = '{"event_type":"license.created"}'
        secret = "my-webhook-secret-key"
        sig = sign_payload(payload, secret)
        assert LicenseClient.verify_webhook_signature(payload.encode(), sig, secret) is True


# ── Valid Event Types ──


class TestValidEventTypes:
    def test_all_eight_types(self):
        expected = {
            "license.created", "license.updated", "license.deleted", "license.validated",
            "activation.created", "activation.removed",
            "usage.recorded", "anomaly.detected",
        }
        assert VALID_EVENT_TYPES == expected


# ── Endpoint CRUD ──


class TestEndpointCRUD:
    async def test_create_endpoint(self, db, webhook_svc):
        async with db.get_session() as session:
            ep = await webhook_svc.create_endpoint(
                session,
                url="https://example.com/hook",
                secret="my-super-secret-key-1234",
                event_types=["license.created"],
                description="Test webhook",
            )
            assert ep.id is not None
            assert ep.url == "https://example.com/hook"
            assert ep.status == "active"
            assert ep.event_types == ["license.created"]
            assert ep.max_retries == 3
            assert ep.timeout_seconds == 10

    async def test_get_endpoint(self, db, webhook_svc):
        async with db.get_session() as session:
            ep = await webhook_svc.create_endpoint(
                session, url="https://example.com/hook",
                secret="my-super-secret-key-1234",
            )
            ep_id = ep.id
        async with db.get_session() as session:
            found = await webhook_svc.get_endpoint(session, ep_id)
            assert found is not None
            assert found.id == ep_id

    async def test_get_nonexistent_endpoint(self, db, webhook_svc):
        async with db.get_session() as session:
            found = await webhook_svc.get_endpoint(session, "fake-id")
            assert found is None

    async def test_list_endpoints(self, db, webhook_svc):
        async with db.get_session() as session:
            await webhook_svc.create_endpoint(
                session, url="https://a.com/hook", secret="secret-key-aaaaaaa1",
            )
            await webhook_svc.create_endpoint(
                session, url="https://b.com/hook", secret="secret-key-bbbbbbb2",
            )
        async with db.get_session() as session:
            endpoints = await webhook_svc.list_endpoints(session)
            assert len(endpoints) == 2

    async def test_list_endpoints_filter_status(self, db, webhook_svc):
        async with db.get_session() as session:
            ep = await webhook_svc.create_endpoint(
                session, url="https://a.com/hook", secret="secret-key-aaaaaaa1",
            )
            await webhook_svc.create_endpoint(
                session, url="https://b.com/hook", secret="secret-key-bbbbbbb2",
            )
            ep_id = ep.id
        async with db.get_session() as session:
            await webhook_svc.update_endpoint(session, ep_id, status="paused")
        async with db.get_session() as session:
            active = await webhook_svc.list_endpoints(session, status="active")
            paused = await webhook_svc.list_endpoints(session, status="paused")
            assert len(active) == 1
            assert len(paused) == 1

    async def test_update_endpoint(self, db, webhook_svc):
        async with db.get_session() as session:
            ep = await webhook_svc.create_endpoint(
                session, url="https://old.com/hook",
                secret="secret-key-old-value-12",
            )
            ep_id = ep.id
        async with db.get_session() as session:
            updated = await webhook_svc.update_endpoint(
                session, ep_id, url="https://new.com/hook", status="paused",
            )
            assert updated.url == "https://new.com/hook"
            assert updated.status == "paused"

    async def test_update_nonexistent_returns_none(self, db, webhook_svc):
        async with db.get_session() as session:
            result = await webhook_svc.update_endpoint(session, "fake-id", url="x")
            assert result is None

    async def test_delete_endpoint(self, db, webhook_svc):
        async with db.get_session() as session:
            ep = await webhook_svc.create_endpoint(
                session, url="https://del.com/hook",
                secret="secret-key-del-value-12",
            )
            ep_id = ep.id
        async with db.get_session() as session:
            deleted = await webhook_svc.delete_endpoint(session, ep_id)
            assert deleted is True
        async with db.get_session() as session:
            found = await webhook_svc.get_endpoint(session, ep_id)
            assert found is None

    async def test_delete_nonexistent_returns_false(self, db, webhook_svc):
        async with db.get_session() as session:
            result = await webhook_svc.delete_endpoint(session, "fake-id")
            assert result is False


# ── Tenant Isolation ──


class TestTenantIsolation:
    async def test_endpoint_scoped_by_tenant(self, db, webhook_svc):
        async with db.get_session() as session:
            await webhook_svc.create_endpoint(
                session, url="https://t1.com/hook",
                secret="secret-key-tenant-one1",
                tenant_id="tenant-1",
            )
            await webhook_svc.create_endpoint(
                session, url="https://t2.com/hook",
                secret="secret-key-tenant-two2",
                tenant_id="tenant-2",
            )
        async with db.get_session() as session:
            t1_eps = await webhook_svc.list_endpoints(session, tenant_id="tenant-1")
            t2_eps = await webhook_svc.list_endpoints(session, tenant_id="tenant-2")
            assert len(t1_eps) == 1
            assert t1_eps[0].url == "https://t1.com/hook"
            assert len(t2_eps) == 1
            assert t2_eps[0].url == "https://t2.com/hook"

    async def test_get_endpoint_wrong_tenant(self, db, webhook_svc):
        async with db.get_session() as session:
            ep = await webhook_svc.create_endpoint(
                session, url="https://t1.com/hook",
                secret="secret-key-tenant-one1",
                tenant_id="tenant-1",
            )
            ep_id = ep.id
        async with db.get_session() as session:
            found = await webhook_svc.get_endpoint(session, ep_id, tenant_id="tenant-2")
            assert found is None


# ── Dispatch ──


class TestDispatch:
    async def test_dispatch_creates_deliveries(self, db, webhook_svc):
        async with db.get_session() as session:
            await webhook_svc.create_endpoint(
                session, url="https://example.com/hook",
                secret="secret-key-dispatch-test",
                event_types=["license.created"],
            )
        # Patch _send_delivery to avoid actual HTTP
        with patch.object(webhook_svc, "_send_delivery", new_callable=AsyncMock):
            async with db.get_session() as session:
                deliveries = await webhook_svc.dispatch(
                    session, "license.created", {"license_id": "abc-123"},
                )
                assert len(deliveries) == 1
                assert deliveries[0].event_type == "license.created"
                assert deliveries[0].status == "pending"

    async def test_dispatch_skips_non_matching_event(self, db, webhook_svc):
        async with db.get_session() as session:
            await webhook_svc.create_endpoint(
                session, url="https://example.com/hook",
                secret="secret-key-dispatch-test",
                event_types=["license.created"],
            )
        with patch.object(webhook_svc, "_send_delivery", new_callable=AsyncMock):
            async with db.get_session() as session:
                deliveries = await webhook_svc.dispatch(
                    session, "activation.created", {"license_id": "abc"},
                )
                assert len(deliveries) == 0

    async def test_dispatch_wildcard_matches_all(self, db, webhook_svc):
        async with db.get_session() as session:
            await webhook_svc.create_endpoint(
                session, url="https://example.com/hook",
                secret="secret-key-dispatch-test",
                event_types=[],  # wildcard
            )
        with patch.object(webhook_svc, "_send_delivery", new_callable=AsyncMock):
            async with db.get_session() as session:
                deliveries = await webhook_svc.dispatch(
                    session, "usage.recorded", {"metric": "api_calls"},
                )
                assert len(deliveries) == 1

    async def test_dispatch_skips_paused_endpoint(self, db, webhook_svc):
        async with db.get_session() as session:
            ep = await webhook_svc.create_endpoint(
                session, url="https://example.com/hook",
                secret="secret-key-dispatch-test",
                event_types=[],
            )
            ep_id = ep.id
        async with db.get_session() as session:
            await webhook_svc.update_endpoint(session, ep_id, status="paused")
        with patch.object(webhook_svc, "_send_delivery", new_callable=AsyncMock):
            async with db.get_session() as session:
                deliveries = await webhook_svc.dispatch(
                    session, "license.created", {},
                )
                assert len(deliveries) == 0

    async def test_dispatch_tenant_scoped(self, db, webhook_svc):
        async with db.get_session() as session:
            await webhook_svc.create_endpoint(
                session, url="https://t1.com/hook",
                secret="secret-key-tenant-one1",
                event_types=[],
                tenant_id="tenant-1",
            )
            await webhook_svc.create_endpoint(
                session, url="https://global.com/hook",
                secret="secret-key-global-one",
                event_types=[],
            )
        with patch.object(webhook_svc, "_send_delivery", new_callable=AsyncMock):
            async with db.get_session() as session:
                # Dispatch for tenant-1 should only hit tenant-1 endpoint
                deliveries = await webhook_svc.dispatch(
                    session, "license.created", {}, tenant_id="tenant-1",
                )
                assert len(deliveries) == 1
                assert deliveries[0].endpoint_id is not None


# ── Delivery Lifecycle (mocked HTTP) ──


class TestDeliveryLifecycle:
    async def test_successful_delivery(self, db, webhook_svc):
        """Mock a successful HTTP POST and verify delivery status updates."""
        async with db.get_session() as session:
            ep = await webhook_svc.create_endpoint(
                session, url="https://example.com/hook",
                secret="secret-key-delivery-test",
                event_types=["license.created"],
            )

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        webhook_svc._http_client = mock_client

        # Mock _update_delivery_status to avoid needing deps.get_db()
        with patch.object(webhook_svc, "_update_delivery_status", new_callable=AsyncMock) as mock_update:
            await webhook_svc._send_delivery(
                delivery_id="test-delivery-id",
                url="https://example.com/hook",
                secret="secret-key-delivery-test",
                payload={"event_type": "license.created", "data": {}},
                max_retries=3,
                timeout=10,
            )
            mock_update.assert_called_once_with(
                "test-delivery-id", "success", 1, 200, None,
            )

    async def test_failed_delivery_exhausts_retries(self, db, webhook_svc):
        mock_response = MagicMock()
        mock_response.status_code = 500

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        webhook_svc._http_client = mock_client

        with patch.object(webhook_svc, "_update_delivery_status", new_callable=AsyncMock) as mock_update:
            await webhook_svc._send_delivery(
                delivery_id="test-delivery-id",
                url="https://example.com/hook",
                secret="secret-key-delivery-test",
                payload={"event_type": "license.created", "data": {}},
                max_retries=1,
                timeout=10,
            )
            mock_update.assert_called_once_with(
                "test-delivery-id", "failed", 2, 500, "HTTP 500",
            )


# ── Delivery Queries ──


class TestDeliveryQueries:
    async def test_get_deliveries_for_endpoint(self, db, webhook_svc):
        async with db.get_session() as session:
            ep = await webhook_svc.create_endpoint(
                session, url="https://example.com/hook",
                secret="secret-key-delivery-test",
                event_types=["license.created"],
            )
            ep_id = ep.id
        with patch.object(webhook_svc, "_send_delivery", new_callable=AsyncMock):
            async with db.get_session() as session:
                await webhook_svc.dispatch(
                    session, "license.created", {"license_id": "abc"},
                )
        async with db.get_session() as session:
            deliveries = await webhook_svc.get_deliveries(session, endpoint_id=ep_id)
            assert len(deliveries) == 1
            assert deliveries[0].event_type == "license.created"

    async def test_retry_delivery(self, db, webhook_svc):
        async with db.get_session() as session:
            ep = await webhook_svc.create_endpoint(
                session, url="https://example.com/hook",
                secret="secret-key-retry-tests",
                event_types=["license.created"],
            )
        with patch.object(webhook_svc, "_send_delivery", new_callable=AsyncMock):
            async with db.get_session() as session:
                deliveries = await webhook_svc.dispatch(
                    session, "license.created", {"license_id": "abc"},
                )
                delivery_id = deliveries[0].id

        with patch.object(webhook_svc, "_send_delivery", new_callable=AsyncMock) as mock_send:
            async with db.get_session() as session:
                retried = await webhook_svc.retry_delivery(session, delivery_id)
                assert retried is not None
                assert retried.status == "pending"
                assert retried.attempts == 0
                mock_send.assert_called_once()

    async def test_retry_nonexistent_returns_none(self, db, webhook_svc):
        async with db.get_session() as session:
            result = await webhook_svc.retry_delivery(session, "fake-id")
            assert result is None
