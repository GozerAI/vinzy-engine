"""Integration tests for activation endpoints."""

import pytest


class TestActivationRouter:
    async def _create_license(self, client, admin_headers, machines_limit=3):
        await client.post("/products", json={"code": "ZUL", "name": "Zuultimate"}, headers=admin_headers)
        cust = await client.post("/customers", json={
            "name": "T", "email": "t@example.com",
        }, headers=admin_headers)
        lic_resp = await client.post("/licenses", json={
            "product_code": "ZUL",
            "customer_id": cust.json()["id"],
            "machines_limit": machines_limit,
        }, headers=admin_headers)
        return lic_resp.json()["key"]

    async def test_activate(self, client, admin_headers):
        key = await self._create_license(client, admin_headers)
        resp = await client.post("/activate", json={
            "key": key, "fingerprint": "fp-1", "hostname": "host1",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["code"] == "ACTIVATED"

    async def test_activate_already_activated(self, client, admin_headers):
        key = await self._create_license(client, admin_headers)
        await client.post("/activate", json={"key": key, "fingerprint": "fp-1"})
        resp = await client.post("/activate", json={"key": key, "fingerprint": "fp-1"})
        assert resp.json()["code"] == "ALREADY_ACTIVATED"

    async def test_activate_limit(self, client, admin_headers):
        key = await self._create_license(client, admin_headers, machines_limit=1)
        await client.post("/activate", json={"key": key, "fingerprint": "fp-1"})
        resp = await client.post("/activate", json={"key": key, "fingerprint": "fp-2"})
        assert resp.json()["success"] is False
        assert resp.json()["code"] == "ACTIVATION_LIMIT"

    async def test_deactivate(self, client, admin_headers):
        key = await self._create_license(client, admin_headers)
        await client.post("/activate", json={"key": key, "fingerprint": "fp-1"})
        resp = await client.post("/deactivate", json={
            "key": key, "fingerprint": "fp-1",
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    async def test_heartbeat(self, client, admin_headers):
        key = await self._create_license(client, admin_headers)
        await client.post("/activate", json={"key": key, "fingerprint": "fp-1"})
        resp = await client.post("/heartbeat", json={
            "key": key, "fingerprint": "fp-1", "version": "1.0.0",
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    async def test_heartbeat_not_activated(self, client, admin_headers):
        key = await self._create_license(client, admin_headers)
        resp = await client.post("/heartbeat", json={
            "key": key, "fingerprint": "fp-1",
        })
        assert resp.json()["success"] is False
