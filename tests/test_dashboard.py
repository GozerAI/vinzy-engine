"""Integration tests for the admin dashboard."""

import pytest

from tests.conftest import API_KEY, SUPER_ADMIN_KEY


class TestDashboardLogin:
    """Login flow and session management."""

    async def test_unauthenticated_redirect(self, client):
        resp = await client.get("/dashboard/", follow_redirects=False)
        assert resp.status_code == 302
        assert "/dashboard/login" in resp.headers["location"]

    async def test_login_page_renders(self, client):
        resp = await client.get("/dashboard/login")
        assert resp.status_code == 200
        assert "Vinzy-Engine Dashboard" in resp.text

    async def test_login_with_admin_key(self, client):
        resp = await client.post(
            "/dashboard/login",
            data={"api_key": API_KEY},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/dashboard/" in resp.headers["location"]
        assert "vinzy_dash_session" in resp.headers.get("set-cookie", "")

    async def test_login_with_super_admin_key(self, client):
        resp = await client.post(
            "/dashboard/login",
            data={"api_key": SUPER_ADMIN_KEY},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "vinzy_dash_session" in resp.headers.get("set-cookie", "")

    async def test_login_with_invalid_key(self, client):
        resp = await client.post(
            "/dashboard/login",
            data={"api_key": "wrong-key"},
        )
        assert resp.status_code == 401
        assert "Invalid API key" in resp.text

    async def test_logout_clears_cookie(self, client):
        # Login first
        login_resp = await client.post(
            "/dashboard/login",
            data={"api_key": API_KEY},
            follow_redirects=False,
        )
        cookies = login_resp.cookies

        # Logout
        resp = await client.post(
            "/dashboard/logout",
            cookies=cookies,
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/dashboard/login" in resp.headers["location"]


class TestDashboardPages:
    """Page rendering after authentication."""

    async def _login(self, client, key=API_KEY):
        """Login and return cookies dict."""
        resp = await client.post(
            "/dashboard/login",
            data={"api_key": key},
            follow_redirects=False,
        )
        return resp.cookies

    async def test_overview_page(self, client):
        cookies = await self._login(client)
        resp = await client.get("/dashboard/", cookies=cookies)
        assert resp.status_code == 200
        assert "Overview" in resp.text
        assert "Products" in resp.text

    async def test_products_page(self, client):
        cookies = await self._login(client)
        resp = await client.get("/dashboard/products", cookies=cookies)
        assert resp.status_code == 200
        assert "Products" in resp.text
        assert "New Product" in resp.text

    async def test_customers_page(self, client):
        cookies = await self._login(client)
        resp = await client.get("/dashboard/customers", cookies=cookies)
        assert resp.status_code == 200
        assert "Customers" in resp.text

    async def test_licenses_page(self, client):
        cookies = await self._login(client)
        resp = await client.get("/dashboard/licenses", cookies=cookies)
        assert resp.status_code == 200
        assert "Licenses" in resp.text

    async def test_anomalies_page(self, client):
        cookies = await self._login(client)
        resp = await client.get("/dashboard/anomalies", cookies=cookies)
        assert resp.status_code == 200
        assert "Anomalies" in resp.text

    async def test_webhooks_page(self, client):
        cookies = await self._login(client)
        resp = await client.get("/dashboard/webhooks", cookies=cookies)
        assert resp.status_code == 200
        assert "Webhook" in resp.text

    async def test_tenants_forbidden_for_admin(self, client):
        cookies = await self._login(client, API_KEY)
        resp = await client.get("/dashboard/tenants", cookies=cookies)
        assert resp.status_code == 403

    async def test_tenants_accessible_for_super_admin(self, client):
        cookies = await self._login(client, SUPER_ADMIN_KEY)
        resp = await client.get("/dashboard/tenants", cookies=cookies)
        assert resp.status_code == 200
        assert "Tenants" in resp.text


class TestDashboardCRUD:
    """Create operations through the dashboard."""

    async def _login(self, client, key=API_KEY):
        resp = await client.post(
            "/dashboard/login",
            data={"api_key": key},
            follow_redirects=False,
        )
        return resp.cookies

    async def test_create_product(self, client):
        cookies = await self._login(client)
        resp = await client.post(
            "/dashboard/products",
            data={"code": "TST", "name": "Test Product", "description": "desc"},
            cookies=cookies,
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 200
        assert "TST" in resp.text
        assert "Test Product" in resp.text

    async def test_create_customer(self, client):
        cookies = await self._login(client)
        resp = await client.post(
            "/dashboard/customers",
            data={"name": "Jane Doe", "email": "jane@test.com", "company": "ACME"},
            cookies=cookies,
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 200
        assert "Jane Doe" in resp.text
        assert "jane@test.com" in resp.text

    async def test_create_license(self, client):
        cookies = await self._login(client)

        # Create product first
        await client.post(
            "/dashboard/products",
            data={"code": "LIC", "name": "License Product"},
            cookies=cookies,
        )

        # Create customer
        await client.post(
            "/dashboard/customers",
            data={"name": "Bob", "email": "bob@test.com"},
            cookies=cookies,
        )

        # Get customer ID from the customers API
        from vinzy_engine.deps import get_db, get_licensing_service
        db = get_db()
        svc = get_licensing_service()
        async with db.get_session() as session:
            customers = await svc.list_customers(session)
            customer_id = customers[0].id

        # Create license via dashboard
        resp = await client.post(
            "/dashboard/licenses",
            data={
                "product_code": "LIC",
                "customer_id": customer_id,
                "tier": "standard",
                "machines_limit": "3",
                "days_valid": "365",
            },
            cookies=cookies,
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 200
        assert "LIC" in resp.text

    async def test_create_tenant_super_admin(self, client):
        cookies = await self._login(client, SUPER_ADMIN_KEY)
        resp = await client.post(
            "/dashboard/tenants",
            data={"name": "Test Tenant", "slug": "test-tenant"},
            cookies=cookies,
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 200
        assert "Test Tenant" in resp.text

    async def test_create_webhook(self, client):
        cookies = await self._login(client)
        resp = await client.post(
            "/dashboard/webhooks",
            data={
                "url": "https://example.com/hook",
                "secret": "my-secret",
                "description": "Test hook",
            },
            cookies=cookies,
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 200
        assert "example.com" in resp.text


class TestDashboardLicenseDetail:
    """License detail, update, delete, and tab partials."""

    async def _login(self, client, key=API_KEY):
        resp = await client.post(
            "/dashboard/login",
            data={"api_key": key},
            follow_redirects=False,
        )
        return resp.cookies

    async def _create_license(self, client, cookies):
        """Create a product, customer, and license. Return license_id."""
        await client.post(
            "/dashboard/products",
            data={"code": "DET", "name": "Detail Product"},
            cookies=cookies,
        )
        await client.post(
            "/dashboard/customers",
            data={"name": "Detail User", "email": "detail@test.com"},
            cookies=cookies,
        )
        from vinzy_engine.deps import get_db, get_licensing_service
        db = get_db()
        svc = get_licensing_service()
        async with db.get_session() as session:
            customers = await svc.list_customers(session)
            customer_id = customers[0].id
        await client.post(
            "/dashboard/licenses",
            data={
                "product_code": "DET",
                "customer_id": customer_id,
                "tier": "standard",
                "machines_limit": "3",
                "days_valid": "365",
            },
            cookies=cookies,
            headers={"HX-Request": "true"},
        )
        async with db.get_session() as session:
            licenses, _ = await svc.list_licenses(session)
            return licenses[0].id

    async def test_license_detail_page(self, client):
        cookies = await self._login(client)
        license_id = await self._create_license(client, cookies)
        resp = await client.get(f"/dashboard/licenses/{license_id}", cookies=cookies)
        assert resp.status_code == 200
        assert "DET" in resp.text

    async def test_license_detail_not_found(self, client):
        cookies = await self._login(client)
        resp = await client.get("/dashboard/licenses/nonexistent-id", cookies=cookies)
        assert resp.status_code == 404

    async def test_license_update(self, client):
        cookies = await self._login(client)
        license_id = await self._create_license(client, cookies)
        resp = await client.patch(
            f"/dashboard/licenses/{license_id}",
            data={"tier": "premium", "machines_limit": "10"},
            cookies=cookies,
            follow_redirects=False,
        )
        assert resp.status_code == 302

    async def test_license_delete(self, client):
        cookies = await self._login(client)
        license_id = await self._create_license(client, cookies)
        resp = await client.delete(
            f"/dashboard/licenses/{license_id}",
            cookies=cookies,
            follow_redirects=False,
        )
        assert resp.status_code == 302

    async def test_licenses_table_htmx(self, client):
        cookies = await self._login(client)
        resp = await client.get("/dashboard/licenses/table", cookies=cookies)
        assert resp.status_code == 200

    async def test_licenses_table_with_status_filter(self, client):
        cookies = await self._login(client)
        resp = await client.get(
            "/dashboard/licenses/table?status=active", cookies=cookies,
        )
        assert resp.status_code == 200

    async def test_license_audit_tab(self, client):
        cookies = await self._login(client)
        license_id = await self._create_license(client, cookies)
        resp = await client.get(
            f"/dashboard/licenses/{license_id}/audit", cookies=cookies,
        )
        assert resp.status_code == 200

    async def test_license_anomalies_tab(self, client):
        cookies = await self._login(client)
        license_id = await self._create_license(client, cookies)
        resp = await client.get(
            f"/dashboard/licenses/{license_id}/anomalies", cookies=cookies,
        )
        assert resp.status_code == 200

    async def test_license_usage_tab(self, client):
        cookies = await self._login(client)
        license_id = await self._create_license(client, cookies)
        resp = await client.get(
            f"/dashboard/licenses/{license_id}/usage", cookies=cookies,
        )
        assert resp.status_code == 200


class TestDashboardAnomalyOps:
    """Anomaly resolve and table partial."""

    async def _login(self, client, key=API_KEY):
        resp = await client.post(
            "/dashboard/login",
            data={"api_key": key},
            follow_redirects=False,
        )
        return resp.cookies

    async def test_anomalies_table_htmx(self, client):
        cookies = await self._login(client)
        resp = await client.get("/dashboard/anomalies/table", cookies=cookies)
        assert resp.status_code == 200

    async def test_anomalies_table_with_filters(self, client):
        cookies = await self._login(client)
        resp = await client.get(
            "/dashboard/anomalies/table?resolved=false&severity=high",
            cookies=cookies,
        )
        assert resp.status_code == 200

    async def test_resolve_anomaly(self, client):
        cookies = await self._login(client)

        # Insert a test anomaly directly
        from vinzy_engine.deps import get_db
        from vinzy_engine.anomaly.models import AnomalyModel
        db = get_db()
        async with db.get_session() as session:
            anomaly = AnomalyModel(
                license_id="test-lic",
                anomaly_type="z_score",
                severity="high",
                metric="tokens",
                z_score=3.5,
                baseline_mean=100.0,
                baseline_stddev=10.0,
                observed_value=135.0,
                detail={},
                resolved=False,
            )
            session.add(anomaly)
            await session.flush()
            anomaly_id = anomaly.id

        resp = await client.post(
            f"/dashboard/anomalies/{anomaly_id}/resolve", cookies=cookies,
        )
        assert resp.status_code == 200

    async def test_resolve_anomaly_not_found(self, client):
        cookies = await self._login(client)
        resp = await client.post(
            "/dashboard/anomalies/nonexistent-id/resolve", cookies=cookies,
        )
        assert resp.status_code == 404


class TestDashboardTenantOps:
    """Tenant update and delete operations."""

    async def _login(self, client, key=SUPER_ADMIN_KEY):
        resp = await client.post(
            "/dashboard/login",
            data={"api_key": key},
            follow_redirects=False,
        )
        return resp.cookies

    async def _create_tenant(self, client, cookies, name="Op Tenant", slug="op-tenant"):
        await client.post(
            "/dashboard/tenants",
            data={"name": name, "slug": slug},
            cookies=cookies,
            headers={"HX-Request": "true"},
        )
        from vinzy_engine.deps import get_db, get_tenant_service
        db = get_db()
        svc = get_tenant_service()
        async with db.get_session() as session:
            tenants = await svc.list_tenants(session)
            return tenants[0].id

    async def test_update_tenant(self, client):
        cookies = await self._login(client)
        tenant_id = await self._create_tenant(client, cookies)
        resp = await client.patch(
            f"/dashboard/tenants/{tenant_id}",
            data={"name": "Updated Name"},
            cookies=cookies,
        )
        assert resp.status_code == 200

    async def test_delete_tenant(self, client):
        cookies = await self._login(client)
        tenant_id = await self._create_tenant(client, cookies, "Del Tenant", "del-tenant")
        resp = await client.delete(
            f"/dashboard/tenants/{tenant_id}",
            cookies=cookies,
        )
        assert resp.status_code == 200
        assert "Tenant deleted" in resp.headers.get("HX-Trigger", "")

    async def test_update_tenant_forbidden_for_admin(self, client):
        # Create as super admin, try update as regular admin
        sa_cookies = await self._login(client, SUPER_ADMIN_KEY)
        tenant_id = await self._create_tenant(client, sa_cookies, "Admin Test", "admin-test")

        admin_cookies = await self._login(client, API_KEY)
        resp = await client.patch(
            f"/dashboard/tenants/{tenant_id}",
            data={"name": "Hack"},
            cookies=admin_cookies,
        )
        assert resp.status_code == 403


class TestDashboardWebhookOps:
    """Webhook detail, update, delete, test."""

    async def _login(self, client, key=API_KEY):
        resp = await client.post(
            "/dashboard/login",
            data={"api_key": key},
            follow_redirects=False,
        )
        return resp.cookies

    async def _create_webhook(self, client, cookies):
        """Create a webhook and return its ID."""
        await client.post(
            "/dashboard/webhooks",
            data={
                "url": "https://example.com/test-hook",
                "secret": "test-secret",
                "description": "Test webhook",
            },
            cookies=cookies,
            headers={"HX-Request": "true"},
        )
        from vinzy_engine.deps import get_db, get_webhook_service
        db = get_db()
        svc = get_webhook_service()
        async with db.get_session() as session:
            endpoints = await svc.list_endpoints(session)
            return endpoints[0].id

    async def test_webhook_detail_page(self, client):
        cookies = await self._login(client)
        endpoint_id = await self._create_webhook(client, cookies)
        resp = await client.get(
            f"/dashboard/webhooks/{endpoint_id}", cookies=cookies,
        )
        assert resp.status_code == 200
        assert "example.com" in resp.text

    async def test_webhook_detail_not_found(self, client):
        cookies = await self._login(client)
        resp = await client.get(
            "/dashboard/webhooks/nonexistent-id", cookies=cookies,
        )
        assert resp.status_code == 404

    async def test_webhook_update(self, client):
        cookies = await self._login(client)
        endpoint_id = await self._create_webhook(client, cookies)
        resp = await client.patch(
            f"/dashboard/webhooks/{endpoint_id}",
            data={"description": "Updated desc"},
            cookies=cookies,
            follow_redirects=False,
        )
        assert resp.status_code == 302

    async def test_webhook_delete(self, client):
        cookies = await self._login(client)
        endpoint_id = await self._create_webhook(client, cookies)
        resp = await client.delete(
            f"/dashboard/webhooks/{endpoint_id}",
            cookies=cookies,
            follow_redirects=False,
        )
        assert resp.status_code == 302

    async def test_webhook_test_dispatch(self, client):
        cookies = await self._login(client)
        endpoint_id = await self._create_webhook(client, cookies)
        resp = await client.post(
            f"/dashboard/webhooks/{endpoint_id}/test", cookies=cookies,
        )
        assert resp.status_code == 200


class TestDashboardAuditPages:
    """Audit timeline and events partial."""

    async def _login(self, client, key=API_KEY):
        resp = await client.post(
            "/dashboard/login",
            data={"api_key": key},
            follow_redirects=False,
        )
        return resp.cookies

    async def test_audit_page(self, client):
        cookies = await self._login(client)
        resp = await client.get(
            "/dashboard/audit/some-license-id", cookies=cookies,
        )
        assert resp.status_code == 200

    async def test_audit_events_partial(self, client):
        cookies = await self._login(client)
        resp = await client.get(
            "/dashboard/audit/some-license-id/events?page=1", cookies=cookies,
        )
        assert resp.status_code == 200


class TestAnomalyService:
    """Test the list_all_anomalies method added for dashboard."""

    async def test_list_all_anomalies_empty(self, client):
        from vinzy_engine.deps import get_db, get_anomaly_service
        db = get_db()
        svc = get_anomaly_service()
        async with db.get_session() as session:
            items, total = await svc.list_all_anomalies(session)
        assert items == []
        assert total == 0

    async def test_list_all_anomalies_filters(self, client):
        from vinzy_engine.deps import get_db, get_anomaly_service
        from vinzy_engine.anomaly.models import AnomalyModel
        db = get_db()
        svc = get_anomaly_service()

        # Insert a test anomaly directly
        async with db.get_session() as session:
            anomaly = AnomalyModel(
                license_id="test-license-id",
                anomaly_type="z_score",
                severity="high",
                metric="tokens",
                z_score=3.5,
                baseline_mean=100.0,
                baseline_stddev=10.0,
                observed_value=135.0,
                detail={},
                resolved=False,
            )
            session.add(anomaly)
            await session.flush()

        async with db.get_session() as session:
            items, total = await svc.list_all_anomalies(session, resolved=False)
            assert total == 1
            assert items[0].severity == "high"

            items2, total2 = await svc.list_all_anomalies(session, resolved=True)
            assert total2 == 0

            items3, total3 = await svc.list_all_anomalies(session, severity="critical")
            assert total3 == 0

            items4, total4 = await svc.list_all_anomalies(session, severity="high")
            assert total4 == 1
