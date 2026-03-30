"""Integration tests for tenant router — super-admin auth required."""

import pytest


SUPER_ADMIN_KEY = "test-super-admin-key"


class TestTenantRouter:
    async def test_create_tenant_requires_auth(self, client):
        resp = await client.post("/tenants", json={
            "name": "Acme", "slug": "acme",
        })
        assert resp.status_code == 422  # missing header

    async def test_create_tenant_wrong_key(self, client):
        resp = await client.post(
            "/tenants",
            json={"name": "Acme", "slug": "acme"},
            headers={"X-Vinzy-Api-Key": "wrong-key"},
        )
        assert resp.status_code == 403

    async def test_create_tenant_success(self, client, super_admin_headers):
        resp = await client.post(
            "/tenants",
            json={"name": "Acme Corp", "slug": "acme"},
            headers=super_admin_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Acme Corp"
        assert data["slug"] == "acme"
        assert data["api_key"].startswith("vzt_")

    async def test_list_tenants(self, client, super_admin_headers):
        await client.post(
            "/tenants",
            json={"name": "A", "slug": "a"},
            headers=super_admin_headers,
        )
        resp = await client.get("/tenants", headers=super_admin_headers)
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    async def test_list_tenants_requires_auth(self, client):
        resp = await client.get("/tenants")
        assert resp.status_code == 422
