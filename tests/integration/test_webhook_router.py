"""Integration tests for the webhook management API router."""

import pytest

from vinzy_engine.deps import get_webhook_service


class TestCreateWebhookEndpoint:
    async def test_create_endpoint(self, client, admin_headers):
        resp = await client.post(
            "/webhooks",
            headers=admin_headers,
            json={
                "url": "https://example.com/hook",
                "secret": "my-super-secret-key-1234",
                "event_types": ["license.created"],
                "description": "Test webhook",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["url"] == "https://example.com/hook"
        assert data["status"] == "active"
        assert data["event_types"] == ["license.created"]
        assert "secret" not in data  # write-only

    async def test_create_requires_auth(self, client):
        resp = await client.post(
            "/webhooks",
            json={
                "url": "https://example.com/hook",
                "secret": "my-super-secret-key-1234",
            },
        )
        assert resp.status_code in (401, 403, 422)

    async def test_create_rejects_short_secret(self, client, admin_headers):
        resp = await client.post(
            "/webhooks",
            headers=admin_headers,
            json={
                "url": "https://example.com/hook",
                "secret": "short",
            },
        )
        assert resp.status_code == 422

    async def test_create_rejects_invalid_event_type(self, client, admin_headers):
        resp = await client.post(
            "/webhooks",
            headers=admin_headers,
            json={
                "url": "https://example.com/hook",
                "secret": "my-super-secret-key-1234",
                "event_types": ["not.a.real.event"],
            },
        )
        assert resp.status_code == 422


class TestListWebhookEndpoints:
    async def test_list_empty(self, client, admin_headers):
        resp = await client.get("/webhooks", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_after_create(self, client, admin_headers):
        await client.post(
            "/webhooks",
            headers=admin_headers,
            json={
                "url": "https://example.com/hook",
                "secret": "my-super-secret-key-1234",
            },
        )
        resp = await client.get("/webhooks", headers=admin_headers)
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    async def test_list_filter_status(self, client, admin_headers):
        # Create two endpoints
        r1 = await client.post(
            "/webhooks",
            headers=admin_headers,
            json={
                "url": "https://a.com/hook",
                "secret": "my-super-secret-key-1111",
            },
        )
        endpoint_id = r1.json()["id"]

        # Pause one
        await client.patch(
            f"/webhooks/{endpoint_id}",
            headers=admin_headers,
            json={"status": "paused"},
        )

        await client.post(
            "/webhooks",
            headers=admin_headers,
            json={
                "url": "https://b.com/hook",
                "secret": "my-super-secret-key-2222",
            },
        )

        resp = await client.get("/webhooks?status=active", headers=admin_headers)
        assert resp.status_code == 200
        assert len(resp.json()) == 1


class TestGetWebhookEndpoint:
    async def test_get_endpoint(self, client, admin_headers):
        r = await client.post(
            "/webhooks",
            headers=admin_headers,
            json={
                "url": "https://example.com/hook",
                "secret": "my-super-secret-key-1234",
                "description": "My hook",
            },
        )
        endpoint_id = r.json()["id"]

        resp = await client.get(f"/webhooks/{endpoint_id}", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["description"] == "My hook"

    async def test_get_nonexistent(self, client, admin_headers):
        resp = await client.get("/webhooks/fake-id", headers=admin_headers)
        assert resp.status_code == 404


class TestUpdateWebhookEndpoint:
    async def test_update_endpoint(self, client, admin_headers):
        r = await client.post(
            "/webhooks",
            headers=admin_headers,
            json={
                "url": "https://old.com/hook",
                "secret": "my-super-secret-key-1234",
            },
        )
        endpoint_id = r.json()["id"]

        resp = await client.patch(
            f"/webhooks/{endpoint_id}",
            headers=admin_headers,
            json={"url": "https://new.com/hook", "status": "paused"},
        )
        assert resp.status_code == 200
        assert resp.json()["url"] == "https://new.com/hook"
        assert resp.json()["status"] == "paused"

    async def test_update_nonexistent(self, client, admin_headers):
        resp = await client.patch(
            "/webhooks/fake-id",
            headers=admin_headers,
            json={"url": "https://new.com"},
        )
        assert resp.status_code == 404

    async def test_update_rejects_invalid_status(self, client, admin_headers):
        r = await client.post(
            "/webhooks",
            headers=admin_headers,
            json={
                "url": "https://example.com/hook",
                "secret": "my-super-secret-key-1234",
            },
        )
        endpoint_id = r.json()["id"]

        resp = await client.patch(
            f"/webhooks/{endpoint_id}",
            headers=admin_headers,
            json={"status": "invalid_status"},
        )
        assert resp.status_code == 422


class TestDeleteWebhookEndpoint:
    async def test_delete_endpoint(self, client, admin_headers):
        r = await client.post(
            "/webhooks",
            headers=admin_headers,
            json={
                "url": "https://example.com/hook",
                "secret": "my-super-secret-key-1234",
            },
        )
        endpoint_id = r.json()["id"]

        resp = await client.delete(f"/webhooks/{endpoint_id}", headers=admin_headers)
        assert resp.status_code == 204

        # Confirm deleted
        resp = await client.get(f"/webhooks/{endpoint_id}", headers=admin_headers)
        assert resp.status_code == 404

    async def test_delete_nonexistent(self, client, admin_headers):
        resp = await client.delete("/webhooks/fake-id", headers=admin_headers)
        assert resp.status_code == 404


class TestDeliveryLog:
    async def test_deliveries_empty(self, client, admin_headers):
        r = await client.post(
            "/webhooks",
            headers=admin_headers,
            json={
                "url": "https://example.com/hook",
                "secret": "my-super-secret-key-1234",
            },
        )
        endpoint_id = r.json()["id"]

        resp = await client.get(
            f"/webhooks/{endpoint_id}/deliveries",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_deliveries_nonexistent_endpoint(self, client, admin_headers):
        resp = await client.get(
            "/webhooks/fake-id/deliveries",
            headers=admin_headers,
        )
        assert resp.status_code == 404


class TestTestPing:
    async def test_test_ping(self, client, admin_headers):
        r = await client.post(
            "/webhooks",
            headers=admin_headers,
            json={
                "url": "https://example.com/hook",
                "secret": "my-super-secret-key-1234",
            },
        )
        endpoint_id = r.json()["id"]

        resp = await client.post(
            f"/webhooks/{endpoint_id}/test",
            headers=admin_headers,
            json={},
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["event_type"] == "webhook.test"
        assert data["status"] == "pending"

    async def test_test_ping_nonexistent(self, client, admin_headers):
        resp = await client.post(
            "/webhooks/fake-id/test",
            headers=admin_headers,
            json={},
        )
        assert resp.status_code == 404


class TestRetryDelivery:
    async def test_retry_nonexistent(self, client, admin_headers):
        resp = await client.post(
            "/webhooks/deliveries/fake-id/retry",
            headers=admin_headers,
        )
        assert resp.status_code == 404
