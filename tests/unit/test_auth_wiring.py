"""Tests for auth wiring — admin endpoints require API key, public endpoints don't."""

import pytest


class TestAdminEndpointsRequireAuth:
    async def test_create_product_no_auth(self, client):
        resp = await client.post("/products", json={"code": "ZUL", "name": "Z"})
        assert resp.status_code == 422  # missing required header

    async def test_create_product_wrong_auth(self, client):
        resp = await client.post(
            "/products",
            json={"code": "ZUL", "name": "Z"},
            headers={"X-Vinzy-Api-Key": "wrong-key"},
        )
        assert resp.status_code == 403

    async def test_list_licenses_no_auth(self, client):
        resp = await client.get("/licenses")
        assert resp.status_code == 422

    async def test_get_usage_no_auth(self, client):
        resp = await client.get("/usage/some-id")
        assert resp.status_code == 422

    async def test_create_customer_no_auth(self, client):
        resp = await client.post("/customers", json={"name": "T", "email": "t@ex.com"})
        assert resp.status_code == 422

    async def test_create_license_wrong_auth(self, client):
        resp = await client.post(
            "/licenses",
            json={"product_code": "ZUL", "customer_id": "x"},
            headers={"X-Vinzy-Api-Key": "wrong"},
        )
        assert resp.status_code == 403


class TestPublicEndpointsWork:
    async def test_validate_no_auth(self, client):
        resp = await client.get("/validate", params={"key": "anything"})
        assert resp.status_code == 200

    async def test_activate_no_auth(self, client):
        resp = await client.post("/activate", json={
            "key": "anything", "fingerprint": "fp",
        })
        assert resp.status_code == 200  # returns success=False, but 200


class TestLibraryExports:
    def test_import_license_client(self):
        from vinzy_engine import LicenseClient
        assert LicenseClient is not None

    def test_import_generate_key(self):
        from vinzy_engine import generate_key
        key = generate_key("ZUL", "test-key")
        assert key.startswith("ZUL-")

    def test_import_validate_key(self):
        from vinzy_engine import validate_key, generate_key
        key = generate_key("ZUL", "test-key")
        result = validate_key(key, "test-key")
        assert result.valid is True
