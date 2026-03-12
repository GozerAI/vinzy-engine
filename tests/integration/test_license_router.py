"""Integration tests for licensing endpoints."""

import pytest


class TestHealthEndpoint:
    async def test_health(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "vinzy-engine"


class TestProductEndpoints:
    async def test_create_product(self, client, admin_headers):
        resp = await client.post("/products", json={
            "code": "ZUL", "name": "Zuultimate",
        }, headers=admin_headers)
        assert resp.status_code == 201
        data = resp.json()
        assert data["code"] == "ZUL"
        assert data["id"]

    async def test_list_products(self, client, admin_headers):
        await client.post("/products", json={"code": "ZUL", "name": "Zuultimate"}, headers=admin_headers)
        await client.post("/products", json={"code": "NXS", "name": "Nexus"}, headers=admin_headers)
        resp = await client.get("/products", headers=admin_headers)
        assert resp.status_code == 200
        assert len(resp.json()) == 2


class TestCustomerEndpoints:
    async def test_create_customer(self, client, admin_headers):
        resp = await client.post("/customers", json={
            "name": "Test Corp", "email": "test@example.com",
        }, headers=admin_headers)
        assert resp.status_code == 201
        assert resp.json()["email"] == "test@example.com"

    async def test_list_customers(self, client, admin_headers):
        await client.post("/customers", json={"name": "A", "email": "a@ex.com"}, headers=admin_headers)
        await client.post("/customers", json={"name": "B", "email": "b@ex.com"}, headers=admin_headers)
        resp = await client.get("/customers", headers=admin_headers)
        assert resp.status_code == 200
        assert len(resp.json()) == 2


class TestLicenseEndpoints:
    async def _setup(self, client, admin_headers):
        prod_resp = await client.post("/products", json={
            "code": "ZUL", "name": "Zuultimate",
            "features": {"api": True, "export": {"enabled": True, "limit": 100}},
        }, headers=admin_headers)
        cust_resp = await client.post("/customers", json={
            "name": "Test", "email": "test@example.com",
        }, headers=admin_headers)
        return prod_resp.json(), cust_resp.json()

    async def test_create_license(self, client, admin_headers):
        product, customer = await self._setup(client, admin_headers)
        resp = await client.post("/licenses", json={
            "product_code": "ZUL",
            "customer_id": customer["id"],
            "tier": "pro",
            "machines_limit": 5,
        }, headers=admin_headers)
        assert resp.status_code == 201
        data = resp.json()
        assert data["key"].startswith("ZUL-")
        assert data["status"] == "active"
        assert data["tier"] == "pro"

    async def test_list_licenses(self, client, admin_headers):
        product, customer = await self._setup(client, admin_headers)
        await client.post("/licenses", json={
            "product_code": "ZUL", "customer_id": customer["id"],
        }, headers=admin_headers)
        resp = await client.get("/licenses", headers=admin_headers)
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    async def test_get_license(self, client, admin_headers):
        product, customer = await self._setup(client, admin_headers)
        create_resp = await client.post("/licenses", json={
            "product_code": "ZUL", "customer_id": customer["id"],
        }, headers=admin_headers)
        lic_id = create_resp.json()["id"]
        resp = await client.get(f"/licenses/{lic_id}", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["id"] == lic_id

    async def test_update_license(self, client, admin_headers):
        product, customer = await self._setup(client, admin_headers)
        create_resp = await client.post("/licenses", json={
            "product_code": "ZUL", "customer_id": customer["id"],
        }, headers=admin_headers)
        lic_id = create_resp.json()["id"]
        resp = await client.patch(f"/licenses/{lic_id}", json={
            "status": "suspended",
        }, headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "suspended"

    async def test_delete_license(self, client, admin_headers):
        product, customer = await self._setup(client, admin_headers)
        create_resp = await client.post("/licenses", json={
            "product_code": "ZUL", "customer_id": customer["id"],
        }, headers=admin_headers)
        lic_id = create_resp.json()["id"]
        resp = await client.delete(f"/licenses/{lic_id}", headers=admin_headers)
        assert resp.status_code == 204
        # Should be gone now
        get_resp = await client.get(f"/licenses/{lic_id}", headers=admin_headers)
        assert get_resp.status_code == 404


class TestValidationEndpoint:
    async def _create_license(self, client, admin_headers):
        await client.post("/products", json={
            "code": "ZUL", "name": "Zuultimate",
            "features": {"api": True},
        }, headers=admin_headers)
        cust = await client.post("/customers", json={
            "name": "T", "email": "t@example.com",
        }, headers=admin_headers)
        lic_resp = await client.post("/licenses", json={
            "product_code": "ZUL", "customer_id": cust.json()["id"],
        }, headers=admin_headers)
        return lic_resp.json()["key"]

    async def test_validate_valid_key(self, client, admin_headers):
        key = await self._create_license(client, admin_headers)
        resp = await client.get("/validate", params={"key": key})
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert data["code"] == "OK"
        # Verify lease is present and well-formed
        assert data.get("lease") is not None, "Lease must be present in validation response"
        lease = data["lease"]
        assert "payload" in lease
        assert "signature" in lease
        assert "lease_expires_at" in lease
        assert lease["payload"]["status"] == "active"

    async def test_validate_invalid_key(self, client):
        resp = await client.get("/validate", params={"key": "bad-key"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False


class TestAgentValidationEndpoint:
    async def _create_agent_license(self, client, admin_headers):
        await client.post("/products", json={
            "code": "ZUL", "name": "Zuultimate",
            "features": {
                "api": True,
                "agents": {
                    "CTO": {"enabled": True, "token_limit": 50000, "model_tier": "premium"},
                    "CSecO": {"enabled": False},
                },
            },
        }, headers=admin_headers)
        cust = await client.post("/customers", json={
            "name": "AgentTest", "email": "agent@example.com",
        }, headers=admin_headers)
        lic_resp = await client.post("/licenses", json={
            "product_code": "ZUL", "customer_id": cust.json()["id"],
        }, headers=admin_headers)
        return lic_resp.json()

    async def test_validate_agent_endpoint(self, client, admin_headers):
        lic = await self._create_agent_license(client, admin_headers)
        # Entitled agent
        resp = await client.get("/validate/agent", params={
            "key": lic["key"], "agent_code": "CTO",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert data["agent_code"] == "CTO"
        assert data["token_limit"] == 50000
        # Disabled agent
        resp = await client.get("/validate/agent", params={
            "key": lic["key"], "agent_code": "CSecO",
        })
        data = resp.json()
        assert data["valid"] is False
        assert data["code"] == "AGENT_NOT_ENTITLED"


class TestPostValidationEndpoint:
    """Tests for the preferred POST /validate endpoint."""

    async def _create_license(self, client, admin_headers):
        await client.post("/products", json={
            "code": "ZUL", "name": "Zuultimate",
            "features": {"api": True},
        }, headers=admin_headers)
        cust = await client.post("/customers", json={
            "name": "T", "email": "t@example.com",
        }, headers=admin_headers)
        lic_resp = await client.post("/licenses", json={
            "product_code": "ZUL", "customer_id": cust.json()["id"],
        }, headers=admin_headers)
        return lic_resp.json()["key"]

    async def test_post_validate_valid_key(self, client, admin_headers):
        key = await self._create_license(client, admin_headers)
        resp = await client.post("/validate", json={"key": key})
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert data["code"] == "OK"
        assert data["lease"] is not None
        assert data["lease"]["payload"]["status"] == "active"
        assert "signature" in data["lease"]

    async def test_post_validate_with_fingerprint(self, client, admin_headers):
        key = await self._create_license(client, admin_headers)
        resp = await client.post("/validate", json={"key": key, "fingerprint": "fp-abc"})
        assert resp.status_code == 200
        assert resp.json()["valid"] is True

    async def test_post_validate_invalid_key(self, client):
        resp = await client.post("/validate", json={"key": "bad-key"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False

    async def test_post_validate_missing_key(self, client):
        resp = await client.post("/validate", json={})
        assert resp.status_code == 422  # Pydantic validation error


class TestPostAgentValidationEndpoint:
    """Tests for the preferred POST /validate/agent endpoint."""

    async def _create_agent_license(self, client, admin_headers):
        await client.post("/products", json={
            "code": "ZUL", "name": "Zuultimate",
            "features": {
                "api": True,
                "agents": {
                    "CTO": {"enabled": True, "token_limit": 50000, "model_tier": "premium"},
                    "CSecO": {"enabled": False},
                },
            },
        }, headers=admin_headers)
        cust = await client.post("/customers", json={
            "name": "AgentPost", "email": "apost@example.com",
        }, headers=admin_headers)
        lic_resp = await client.post("/licenses", json={
            "product_code": "ZUL", "customer_id": cust.json()["id"],
        }, headers=admin_headers)
        return lic_resp.json()

    async def test_post_validate_agent_entitled(self, client, admin_headers):
        lic = await self._create_agent_license(client, admin_headers)
        resp = await client.post("/validate/agent", json={
            "key": lic["key"], "agent_code": "CTO",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert data["agent_code"] == "CTO"
        assert data["token_limit"] == 50000
        assert data["model_tier"] == "premium"

    async def test_post_validate_agent_not_entitled(self, client, admin_headers):
        lic = await self._create_agent_license(client, admin_headers)
        resp = await client.post("/validate/agent", json={
            "key": lic["key"], "agent_code": "CSecO",
        })
        data = resp.json()
        assert data["valid"] is False
        assert data["code"] == "AGENT_NOT_ENTITLED"

    async def test_post_validate_agent_invalid_key(self, client):
        resp = await client.post("/validate/agent", json={
            "key": "bad-key", "agent_code": "CTO",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False


class TestListEntitledAgentsEndpoint:
    """Tests for GET /licenses/{id}/agents."""

    async def _create_agent_license(self, client, admin_headers):
        await client.post("/products", json={
            "code": "ZUL", "name": "Zuultimate",
            "features": {
                "agents": {
                    "CTO": {"enabled": True, "token_limit": 50000, "model_tier": "premium"},
                    "CFO": {"enabled": True, "token_limit": 20000},
                    "CSecO": {"enabled": False},
                },
            },
        }, headers=admin_headers)
        cust = await client.post("/customers", json={
            "name": "AgentList", "email": "alist@example.com",
        }, headers=admin_headers)
        lic_resp = await client.post("/licenses", json={
            "product_code": "ZUL", "customer_id": cust.json()["id"],
        }, headers=admin_headers)
        return lic_resp.json()

    async def test_list_entitled_agents(self, client, admin_headers):
        lic = await self._create_agent_license(client, admin_headers)
        resp = await client.get(f"/licenses/{lic['id']}/agents", headers=admin_headers)
        assert resp.status_code == 200
        agents = resp.json()
        codes = {a["agent_code"] for a in agents}
        assert "CTO" in codes
        assert "CFO" in codes
        assert "CSecO" in codes
        # Check CTO details
        cto = next(a for a in agents if a["agent_code"] == "CTO")
        assert cto["enabled"] is True
        assert cto["token_limit"] == 50000
        assert cto["model_tier"] == "premium"
        # CSecO should be disabled
        cseco = next(a for a in agents if a["agent_code"] == "CSecO")
        assert cseco["enabled"] is False

    async def test_list_agents_not_found(self, client, admin_headers):
        resp = await client.get("/licenses/nonexistent-id/agents", headers=admin_headers)
        assert resp.status_code == 404

    async def test_list_agents_requires_auth(self, client):
        resp = await client.get("/licenses/some-id/agents")
        assert resp.status_code == 422  # Missing X-Vinzy-Api-Key header


class TestComposedEndpoint:
    async def test_composed_endpoint(self, client, admin_headers):
        # Create two products
        await client.post("/products", json={
            "code": "ZUL", "name": "Zuultimate",
            "features": {"api": True, "agents": {"CTO": {"enabled": True, "token_limit": 50000}}},
        }, headers=admin_headers)
        await client.post("/products", json={
            "code": "NXS", "name": "Nexus",
            "features": {"export": True, "agents": {"CTO": {"enabled": True, "token_limit": 30000}}},
        }, headers=admin_headers)
        # Create customer with two licenses
        cust = await client.post("/customers", json={
            "name": "Multi", "email": "multi@test.com",
        }, headers=admin_headers)
        cust_id = cust.json()["id"]
        await client.post("/licenses", json={
            "product_code": "ZUL", "customer_id": cust_id,
        }, headers=admin_headers)
        await client.post("/licenses", json={
            "product_code": "NXS", "customer_id": cust_id,
        }, headers=admin_headers)
        # Get composed
        resp = await client.get(
            f"/entitlements/composed/{cust_id}", headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["customer_id"] == cust_id
        assert data["total_products"] == 2
        assert data["agents"]["CTO"]["token_limit"] == 80000
