"""Integration tests for the audit chain API endpoints."""

import pytest


class TestAuditRouter:
    async def _setup(self, client, admin_headers):
        """Create product + customer + license."""
        await client.post("/products", json={
            "code": "ZUL", "name": "Zuultimate",
        }, headers=admin_headers)
        cust_resp = await client.post("/customers", json={
            "name": "Test", "email": "test@example.com",
        }, headers=admin_headers)
        lic_resp = await client.post("/licenses", json={
            "product_code": "ZUL",
            "customer_id": cust_resp.json()["id"],
            "tier": "pro",
        }, headers=admin_headers)
        return lic_resp.json()

    async def test_get_audit_events(self, client, admin_headers):
        lic = await self._setup(client, admin_headers)
        # Creating a license auto-records an audit event
        resp = await client.get(
            f"/audit/{lic['id']}", headers=admin_headers,
        )
        assert resp.status_code == 200
        events = resp.json()
        assert len(events) >= 1
        assert events[0]["event_type"] == "license.created"
        assert events[0]["event_hash"] is not None
        assert events[0]["signature"] is not None

    async def test_verify_chain_endpoint(self, client, admin_headers):
        lic = await self._setup(client, admin_headers)
        resp = await client.get(
            f"/audit/{lic['id']}/verify", headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert data["events_checked"] >= 1

    async def test_audit_auto_recorded_on_create(self, client, admin_headers):
        lic = await self._setup(client, admin_headers)
        resp = await client.get(
            f"/audit/{lic['id']}?event_type=license.created",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        events = resp.json()
        assert len(events) == 1
        assert events[0]["detail"]["product_code"] == "ZUL"

    async def test_audit_auto_recorded_on_validate(self, client, admin_headers):
        lic = await self._setup(client, admin_headers)
        # Validate the license
        await client.get(f"/validate?key={lic['key']}")
        resp = await client.get(
            f"/audit/{lic['id']}?event_type=license.validated",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        events = resp.json()
        assert len(events) >= 1
