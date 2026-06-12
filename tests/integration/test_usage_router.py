"""Integration tests for usage endpoints."""

import pytest


class TestUsageRouter:
    async def _create_license(self, client, admin_headers, entitlements=None):
        await client.post("/products", json={"code": "ZUL", "name": "Zuultimate"}, headers=admin_headers)
        cust = await client.post("/customers", json={
            "name": "T", "email": "t@example.com",
        }, headers=admin_headers)
        lic_resp = await client.post("/licenses", json={
            "product_code": "ZUL",
            "customer_id": cust.json()["id"],
            "entitlements": entitlements or {},
        }, headers=admin_headers)
        data = lic_resp.json()
        return data["key"], data["id"]

    async def test_record_usage(self, client, admin_headers):
        key, lic_id = await self._create_license(client, admin_headers)
        resp = await client.post("/usage/record", json={
            "key": key, "metric": "api-calls", "value": 5.0,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["value_added"] == 5.0

    async def test_record_usage_accumulates(self, client, admin_headers):
        key, lic_id = await self._create_license(client, admin_headers)
        await client.post("/usage/record", json={
            "key": key, "metric": "tokens", "value": 100,
        })
        resp = await client.post("/usage/record", json={
            "key": key, "metric": "tokens", "value": 50,
        })
        assert resp.json()["total_value"] == 150.0

    async def test_get_usage_summary(self, client, admin_headers):
        key, lic_id = await self._create_license(client, admin_headers)
        await client.post("/usage/record", json={
            "key": key, "metric": "api-calls", "value": 3,
        })
        await client.post("/usage/record", json={
            "key": key, "metric": "tokens", "value": 500,
        })
        resp = await client.get(f"/usage/{lic_id}", headers=admin_headers)
        assert resp.status_code == 200
        summaries = resp.json()
        assert len(summaries) == 2

    async def test_usage_with_bad_key(self, client):
        resp = await client.post("/usage/record", json={
            "key": "bad-key", "metric": "api-calls", "value": 1,
        })
        assert resp.json()["success"] is False

    async def test_agent_usage_endpoint(self, client, admin_headers):
        key, lic_id = await self._create_license(client, admin_headers)
        # Record agent-prefixed usage
        await client.post("/usage/record", json={
            "key": key, "metric": "agent.CTO.tokens", "value": 3000,
        })
        await client.post("/usage/record", json={
            "key": key, "metric": "agent.CTO.delegations", "value": 5,
        })
        await client.post("/usage/record", json={
            "key": key, "metric": "agent.CFO.tokens", "value": 1000,
        })
        resp = await client.get(
            f"/usage/agents/{lic_id}", headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["CTO"]["tokens"] == 3000
        assert data["CTO"]["delegations"] == 5
        assert data["CFO"]["tokens"] == 1000
