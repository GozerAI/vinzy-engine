"""Integration tests for the anomaly detection API router."""

import pytest

from vinzy_engine.deps import get_db, get_licensing_service, get_usage_service, get_anomaly_service


@pytest.fixture
async def seeded_anomaly(client, admin_headers):
    """Create a license, record baseline usage, trigger an anomaly, return anomaly data."""
    db = get_db()
    licensing = get_licensing_service()
    usage = get_usage_service()
    anomaly_svc = get_anomaly_service()

    # Create product + customer + license
    async with db.get_session() as session:
        await licensing.create_product(session, "ZUL", "Zuultimate")
        customer = await licensing.create_customer(
            session, "Test", "anomaly@test.com"
        )
    async with db.get_session() as session:
        lic, raw_key = await licensing.create_license(
            session, "ZUL", customer.id
        )

    # Record baseline usage (10 normal values)
    for _ in range(10):
        async with db.get_session() as session:
            await usage.record_usage(session, raw_key, "api_calls", 10.0)

    # Record spike to trigger anomaly
    async with db.get_session() as session:
        anomaly = await anomaly_svc.scan_and_record(
            session, lic.id, "api_calls", 100.0,
        )

    return {"license_id": lic.id, "anomaly_id": anomaly.id, "raw_key": raw_key}


class TestGetAnomaliesEndpoint:
    async def test_get_anomalies(self, client, admin_headers, seeded_anomaly):
        license_id = seeded_anomaly["license_id"]
        resp = await client.get(
            f"/anomalies/{license_id}",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["license_id"] == license_id
        assert data[0]["severity"] in ("critical", "high", "medium")
        assert data[0]["resolved"] is False

    async def test_get_anomalies_requires_auth(self, client, seeded_anomaly):
        license_id = seeded_anomaly["license_id"]
        resp = await client.get(f"/anomalies/{license_id}")
        assert resp.status_code in (401, 403, 422)


class TestResolveAnomalyEndpoint:
    async def test_resolve_anomaly(self, client, admin_headers, seeded_anomaly):
        anomaly_id = seeded_anomaly["anomaly_id"]
        resp = await client.post(
            f"/anomalies/{anomaly_id}/resolve",
            headers=admin_headers,
            json={"resolved_by": "admin@test.com"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["resolved"] is True
        assert data["resolved_by"] == "admin@test.com"
        assert data["resolved_at"] is not None

    async def test_resolve_nonexistent(self, client, admin_headers):
        resp = await client.post(
            "/anomalies/fake-id/resolve",
            headers=admin_headers,
            json={"resolved_by": "admin"},
        )
        assert resp.status_code == 404
