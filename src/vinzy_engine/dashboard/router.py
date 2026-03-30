"""Dashboard sub-application — routes and handlers."""

import logging
import pathlib

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

from vinzy_engine.dashboard.auth import (
    COOKIE_NAME,
    MAX_AGE,
    create_session_cookie,
    get_session,
    login_redirect,
)
from vinzy_engine.dashboard.context import base_context

logger = logging.getLogger(__name__)

_DIR = pathlib.Path(__file__).parent
_TEMPLATES_DIR = _DIR / "templates"
_STATIC_DIR = _DIR / "static"

templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


# ── Auth middleware ──


class DashboardAuthMiddleware(BaseHTTPMiddleware):
    """Redirect unauthenticated requests to login page."""

    EXEMPT = {"/dashboard/login", "/dashboard/static"}

    async def dispatch(self, request, call_next):
        path = request.url.path
        # Allow login page and static assets
        if path == "/dashboard/login" or path.startswith("/dashboard/static"):
            return await call_next(request)
        session = get_session(request)
        if session is None:
            return login_redirect()
        request.state.session = session
        return await call_next(request)


# ── Helpers ──


def _get_db():
    from vinzy_engine.deps import get_db
    return get_db()


def _get_licensing():
    from vinzy_engine.deps import get_licensing_service
    return get_licensing_service()


def _get_tenant_service():
    from vinzy_engine.deps import get_tenant_service
    return get_tenant_service()


def _get_audit_service():
    from vinzy_engine.deps import get_audit_service
    return get_audit_service()


def _get_anomaly_service():
    from vinzy_engine.deps import get_anomaly_service
    return get_anomaly_service()


def _get_usage_service():
    from vinzy_engine.deps import get_usage_service
    return get_usage_service()


def _get_webhook_service():
    from vinzy_engine.deps import get_webhook_service
    return get_webhook_service()


def _ctx(request: Request) -> dict:
    """Build base context from request."""
    session = getattr(request.state, "session", None)
    return base_context(request, session)


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def _flash(response, message: str, level: str = "success"):
    """Set HX-Trigger header for flash messages."""
    import json
    response.headers["HX-Trigger"] = json.dumps({
        "showFlash": {"message": message, "level": level}
    })
    return response


# ── App factory ──


def create_dashboard_app() -> FastAPI:
    """Create the dashboard FastAPI sub-application."""
    app = FastAPI(docs_url=None, openapi_url=None, redoc_url=None)
    app.add_middleware(DashboardAuthMiddleware)
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="dashboard-static")

    # ────────────────────────────────────────────
    # Auth routes
    # ────────────────────────────────────────────

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request):
        return templates.TemplateResponse("login.html", {"request": request, "error": None})

    @app.post("/login")
    async def login_submit(request: Request, api_key: str = Form(...)):
        from vinzy_engine.common.config import get_settings
        settings = get_settings()

        if api_key == settings.super_admin_key:
            role = "super_admin"
        elif api_key == settings.api_key:
            role = "admin"
        else:
            return templates.TemplateResponse(
                "login.html", {"request": request, "error": "Invalid API key"}, status_code=401,
            )

        response = RedirectResponse("/dashboard/", status_code=302)
        cookie = create_session_cookie(role)
        response.set_cookie(
            COOKIE_NAME, cookie, max_age=MAX_AGE,
            httponly=True, samesite="lax", secure=True,
        )
        return response

    @app.post("/logout")
    async def logout():
        response = RedirectResponse("/dashboard/login", status_code=302)
        response.delete_cookie(COOKIE_NAME)
        return response

    # ────────────────────────────────────────────
    # Overview
    # ────────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    async def overview(request: Request):
        db = _get_db()
        licensing = _get_licensing()
        anomaly_svc = _get_anomaly_service()

        async with db.get_session() as session:
            products = await licensing.list_products(session)
            customers = await licensing.list_customers(session)
            _, license_total = await licensing.list_licenses(session, limit=1)
            unresolved = await anomaly_svc.list_all_anomalies(
                session, resolved=False, limit=1, offset=0,
            )

        ctx = _ctx(request)
        ctx.update({
            "product_count": len(products),
            "customer_count": len(customers),
            "license_count": license_total,
            "anomaly_count": unresolved[1],  # total count
        })
        return templates.TemplateResponse("overview.html", ctx)

    # ────────────────────────────────────────────
    # Products
    # ────────────────────────────────────────────

    @app.get("/products", response_class=HTMLResponse)
    async def products_page(request: Request):
        db = _get_db()
        svc = _get_licensing()
        async with db.get_session() as session:
            products = await svc.list_products(session)
        ctx = _ctx(request)
        ctx["products"] = products
        return templates.TemplateResponse("products/list.html", ctx)

    @app.post("/products", response_class=HTMLResponse)
    async def create_product(
        request: Request,
        code: str = Form(...),
        name: str = Form(...),
        description: str = Form(""),
    ):
        db = _get_db()
        svc = _get_licensing()
        error = None
        try:
            async with db.get_session() as session:
                await svc.create_product(session, code, name, description=description)
        except Exception as e:
            error = str(e)

        async with db.get_session() as session:
            products = await svc.list_products(session)

        if _is_htmx(request):
            resp = templates.TemplateResponse(
                "products/_table.html", {"request": request, "products": products},
            )
            if error:
                _flash(resp, error, "error")
            else:
                _flash(resp, "Product created")
            return resp

        ctx = _ctx(request)
        ctx["products"] = products
        ctx["error"] = error
        return templates.TemplateResponse("products/list.html", ctx)

    # ────────────────────────────────────────────
    # Customers
    # ────────────────────────────────────────────

    @app.get("/customers", response_class=HTMLResponse)
    async def customers_page(request: Request):
        db = _get_db()
        svc = _get_licensing()
        async with db.get_session() as session:
            customers = await svc.list_customers(session)
        ctx = _ctx(request)
        ctx["customers"] = customers
        return templates.TemplateResponse("customers/list.html", ctx)

    @app.post("/customers", response_class=HTMLResponse)
    async def create_customer(
        request: Request,
        name: str = Form(...),
        email: str = Form(...),
        company: str = Form(""),
    ):
        db = _get_db()
        svc = _get_licensing()
        error = None
        try:
            async with db.get_session() as session:
                await svc.create_customer(session, name, email, company=company)
        except Exception as e:
            error = str(e)

        async with db.get_session() as session:
            customers = await svc.list_customers(session)

        if _is_htmx(request):
            resp = templates.TemplateResponse(
                "customers/_table.html", {"request": request, "customers": customers},
            )
            if error:
                _flash(resp, error, "error")
            else:
                _flash(resp, "Customer created")
            return resp

        ctx = _ctx(request)
        ctx["customers"] = customers
        ctx["error"] = error
        return templates.TemplateResponse("customers/list.html", ctx)

    # ────────────────────────────────────────────
    # Licenses
    # ────────────────────────────────────────────

    @app.get("/licenses", response_class=HTMLResponse)
    async def licenses_page(
        request: Request,
        status: str | None = Query(None),
        page: int = Query(1, ge=1),
    ):
        db = _get_db()
        svc = _get_licensing()
        page_size = 20
        offset = (page - 1) * page_size

        async with db.get_session() as session:
            items, total = await svc.list_licenses(
                session, status=status, offset=offset, limit=page_size,
            )
            # Resolve product codes
            from vinzy_engine.licensing.models import ProductModel
            licenses = []
            for lic in items:
                product = await session.get(ProductModel, lic.product_id)
                licenses.append({
                    "obj": lic,
                    "product_code": product.code if product else "",
                })

            products = await svc.list_products(session)
            customers = await svc.list_customers(session)

        total_pages = max(1, (total + page_size - 1) // page_size)
        ctx = _ctx(request)
        ctx.update({
            "licenses": licenses,
            "products": products,
            "customers": customers,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            "status_filter": status or "",
        })
        return templates.TemplateResponse("licenses/list.html", ctx)

    @app.get("/licenses/table", response_class=HTMLResponse)
    async def licenses_table(
        request: Request,
        status: str | None = Query(None),
        page: int = Query(1, ge=1),
    ):
        db = _get_db()
        svc = _get_licensing()
        page_size = 20
        offset = (page - 1) * page_size

        async with db.get_session() as session:
            items, total = await svc.list_licenses(
                session, status=status, offset=offset, limit=page_size,
            )
            from vinzy_engine.licensing.models import ProductModel
            licenses = []
            for lic in items:
                product = await session.get(ProductModel, lic.product_id)
                licenses.append({
                    "obj": lic,
                    "product_code": product.code if product else "",
                })

        total_pages = max(1, (total + page_size - 1) // page_size)
        return templates.TemplateResponse("licenses/_table.html", {
            "request": request,
            "licenses": licenses,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            "status_filter": status or "",
        })

    @app.post("/licenses", response_class=HTMLResponse)
    async def create_license(
        request: Request,
        product_code: str = Form(...),
        customer_id: str = Form(...),
        tier: str = Form("standard"),
        machines_limit: int = Form(3),
        days_valid: int = Form(365),
    ):
        db = _get_db()
        svc = _get_licensing()
        error = None
        created_key = None
        try:
            async with db.get_session() as session:
                _, raw_key = await svc.create_license(
                    session, product_code, customer_id,
                    tier=tier, machines_limit=machines_limit, days_valid=days_valid,
                )
                created_key = raw_key
        except Exception as e:
            error = str(e)

        # Reload table
        async with db.get_session() as session:
            items, total = await svc.list_licenses(session, limit=20)
            from vinzy_engine.licensing.models import ProductModel
            licenses = []
            for lic in items:
                product = await session.get(ProductModel, lic.product_id)
                licenses.append({
                    "obj": lic,
                    "product_code": product.code if product else "",
                })

        total_pages = max(1, (total + 19) // 20)
        if _is_htmx(request):
            resp = templates.TemplateResponse("licenses/_table.html", {
                "request": request,
                "licenses": licenses,
                "total": total,
                "page": 1,
                "total_pages": total_pages,
                "status_filter": "",
            })
            if error:
                _flash(resp, error, "error")
            elif created_key:
                _flash(resp, f"License created. Key: {created_key}")
            return resp

        return RedirectResponse("/dashboard/licenses", status_code=302)

    @app.get("/licenses/{license_id}", response_class=HTMLResponse)
    async def license_detail(request: Request, license_id: str):
        db = _get_db()
        svc = _get_licensing()

        async with db.get_session() as session:
            lic = await svc.get_license_by_id(session, license_id)
            if lic is None:
                return HTMLResponse("License not found", status_code=404)
            from vinzy_engine.licensing.models import ProductModel
            product = await session.get(ProductModel, lic.product_id)
            customer = await svc.get_customer(session, lic.customer_id)
            from vinzy_engine.licensing.entitlements import resolve_entitlements
            product_features = product.features if product else {}
            resolved = resolve_entitlements(product_features, lic.entitlements or {})

        ctx = _ctx(request)
        ctx.update({
            "license": lic,
            "product": product,
            "customer": customer,
            "entitlements": resolved,
        })
        return templates.TemplateResponse("licenses/detail.html", ctx)

    @app.patch("/licenses/{license_id}")
    async def update_license(request: Request, license_id: str):
        db = _get_db()
        svc = _get_licensing()
        form = await request.form()
        updates = {}
        if form.get("status"):
            updates["status"] = form["status"]
        if form.get("tier"):
            updates["tier"] = form["tier"]
        if form.get("machines_limit"):
            updates["machines_limit"] = int(form["machines_limit"])
        try:
            async with db.get_session() as session:
                await svc.update_license(session, license_id, **updates)
        except Exception:
            logger.exception("Failed to update license %s", license_id)
        return RedirectResponse(f"/dashboard/licenses/{license_id}", status_code=302)

    @app.delete("/licenses/{license_id}")
    async def delete_license(request: Request, license_id: str):
        db = _get_db()
        svc = _get_licensing()
        try:
            async with db.get_session() as session:
                await svc.soft_delete_license(session, license_id)
        except Exception:
            logger.exception("Failed to delete license %s", license_id)
        return RedirectResponse("/dashboard/licenses", status_code=302)

    # License tabs (htmx partials)

    @app.get("/licenses/{license_id}/audit", response_class=HTMLResponse)
    async def license_audit_tab(request: Request, license_id: str):
        db = _get_db()
        audit_svc = _get_audit_service()
        async with db.get_session() as session:
            events = await audit_svc.get_events(session, license_id, limit=50)
        return templates.TemplateResponse("licenses/_audit.html", {
            "request": request, "events": events, "license_id": license_id,
        })

    @app.get("/licenses/{license_id}/anomalies", response_class=HTMLResponse)
    async def license_anomalies_tab(request: Request, license_id: str):
        db = _get_db()
        anomaly_svc = _get_anomaly_service()
        async with db.get_session() as session:
            anomalies = await anomaly_svc.get_anomalies(session, license_id)
        return templates.TemplateResponse("licenses/_anomalies.html", {
            "request": request, "anomalies": anomalies, "license_id": license_id,
        })

    @app.get("/licenses/{license_id}/usage", response_class=HTMLResponse)
    async def license_usage_tab(request: Request, license_id: str):
        db = _get_db()
        usage_svc = _get_usage_service()
        async with db.get_session() as session:
            summary = await usage_svc.get_usage_summary(session, license_id)
            agent_summary = await usage_svc.get_agent_usage_summary(session, license_id)
        return templates.TemplateResponse("licenses/_usage.html", {
            "request": request, "usage": summary, "agent_usage": agent_summary,
            "license_id": license_id,
        })

    # ────────────────────────────────────────────
    # Tenants (super-admin only)
    # ────────────────────────────────────────────

    @app.get("/tenants", response_class=HTMLResponse)
    async def tenants_page(request: Request):
        session_data = getattr(request.state, "session", {})
        if session_data.get("role") != "super_admin":
            return HTMLResponse("Forbidden", status_code=403)

        db = _get_db()
        svc = _get_tenant_service()
        async with db.get_session() as session:
            tenants = await svc.list_tenants(session)
        ctx = _ctx(request)
        ctx["tenants"] = tenants
        return templates.TemplateResponse("tenants/list.html", ctx)

    @app.post("/tenants", response_class=HTMLResponse)
    async def create_tenant(
        request: Request,
        name: str = Form(...),
        slug: str = Form(...),
    ):
        session_data = getattr(request.state, "session", {})
        if session_data.get("role") != "super_admin":
            return HTMLResponse("Forbidden", status_code=403)

        db = _get_db()
        svc = _get_tenant_service()
        error = None
        raw_key = None
        try:
            async with db.get_session() as session:
                _, raw_key = await svc.create_tenant(session, name, slug)
        except Exception as e:
            error = str(e)

        async with db.get_session() as session:
            tenants = await svc.list_tenants(session)

        if _is_htmx(request):
            resp = templates.TemplateResponse(
                "tenants/_table.html", {"request": request, "tenants": tenants},
            )
            if error:
                _flash(resp, error, "error")
            elif raw_key:
                _flash(resp, f"Tenant created. API key: {raw_key}")
            return resp

        ctx = _ctx(request)
        ctx["tenants"] = tenants
        return templates.TemplateResponse("tenants/list.html", ctx)

    @app.patch("/tenants/{tenant_id}", response_class=HTMLResponse)
    async def update_tenant(request: Request, tenant_id: str):
        session_data = getattr(request.state, "session", {})
        if session_data.get("role") != "super_admin":
            return HTMLResponse("Forbidden", status_code=403)

        db = _get_db()
        svc = _get_tenant_service()
        form = await request.form()
        updates = {}
        if form.get("name"):
            updates["name"] = form["name"]
        try:
            async with db.get_session() as session:
                await svc.update_tenant(session, tenant_id, **updates)
        except Exception:
            logger.exception("Failed to update tenant %s", tenant_id)

        async with db.get_session() as session:
            tenants = await svc.list_tenants(session)

        return templates.TemplateResponse(
            "tenants/_table.html", {"request": request, "tenants": tenants},
        )

    @app.delete("/tenants/{tenant_id}", response_class=HTMLResponse)
    async def delete_tenant(request: Request, tenant_id: str):
        session_data = getattr(request.state, "session", {})
        if session_data.get("role") != "super_admin":
            return HTMLResponse("Forbidden", status_code=403)

        db = _get_db()
        svc = _get_tenant_service()
        try:
            async with db.get_session() as session:
                await svc.delete_tenant(session, tenant_id)
        except Exception:
            logger.exception("Failed to delete tenant %s", tenant_id)

        async with db.get_session() as session:
            tenants = await svc.list_tenants(session)

        resp = templates.TemplateResponse(
            "tenants/_table.html", {"request": request, "tenants": tenants},
        )
        _flash(resp, "Tenant deleted")
        return resp

    # ────────────────────────────────────────────
    # Anomalies
    # ────────────────────────────────────────────

    @app.get("/anomalies", response_class=HTMLResponse)
    async def anomalies_page(
        request: Request,
        resolved: str | None = Query(None),
        severity: str | None = Query(None),
        page: int = Query(1, ge=1),
    ):
        db = _get_db()
        svc = _get_anomaly_service()
        page_size = 20
        offset = (page - 1) * page_size
        resolved_bool = None
        if resolved == "true":
            resolved_bool = True
        elif resolved == "false":
            resolved_bool = False

        async with db.get_session() as session:
            items, total = await svc.list_all_anomalies(
                session, resolved=resolved_bool, severity=severity,
                limit=page_size, offset=offset,
            )

        total_pages = max(1, (total + page_size - 1) // page_size)
        ctx = _ctx(request)
        ctx.update({
            "anomalies": items,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            "resolved_filter": resolved or "",
            "severity_filter": severity or "",
        })
        return templates.TemplateResponse("anomalies/list.html", ctx)

    @app.get("/anomalies/table", response_class=HTMLResponse)
    async def anomalies_table(
        request: Request,
        resolved: str | None = Query(None),
        severity: str | None = Query(None),
        page: int = Query(1, ge=1),
    ):
        db = _get_db()
        svc = _get_anomaly_service()
        page_size = 20
        offset = (page - 1) * page_size
        resolved_bool = None
        if resolved == "true":
            resolved_bool = True
        elif resolved == "false":
            resolved_bool = False

        async with db.get_session() as session:
            items, total = await svc.list_all_anomalies(
                session, resolved=resolved_bool, severity=severity,
                limit=page_size, offset=offset,
            )

        total_pages = max(1, (total + page_size - 1) // page_size)
        return templates.TemplateResponse("anomalies/_table.html", {
            "request": request,
            "anomalies": items,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            "resolved_filter": resolved or "",
            "severity_filter": severity or "",
        })

    @app.post("/anomalies/{anomaly_id}/resolve", response_class=HTMLResponse)
    async def resolve_anomaly(request: Request, anomaly_id: str):
        db = _get_db()
        svc = _get_anomaly_service()
        async with db.get_session() as session:
            anomaly = await svc.resolve_anomaly(session, anomaly_id, "dashboard-admin")
        if anomaly is None:
            return HTMLResponse("Not found", status_code=404)
        return templates.TemplateResponse("anomalies/_row.html", {
            "request": request, "a": anomaly,
        })

    # ────────────────────────────────────────────
    # Webhooks
    # ────────────────────────────────────────────

    @app.get("/webhooks", response_class=HTMLResponse)
    async def webhooks_page(request: Request):
        db = _get_db()
        svc = _get_webhook_service()
        async with db.get_session() as session:
            endpoints = await svc.list_endpoints(session)
        ctx = _ctx(request)
        ctx["endpoints"] = endpoints
        return templates.TemplateResponse("webhooks/list.html", ctx)

    @app.post("/webhooks", response_class=HTMLResponse)
    async def create_webhook(
        request: Request,
        url: str = Form(...),
        secret: str = Form(...),
        description: str = Form(""),
    ):
        db = _get_db()
        svc = _get_webhook_service()
        error = None
        try:
            async with db.get_session() as session:
                await svc.create_endpoint(session, url, secret, description=description)
        except Exception as e:
            error = str(e)

        async with db.get_session() as session:
            endpoints = await svc.list_endpoints(session)

        if _is_htmx(request):
            resp = templates.TemplateResponse(
                "webhooks/_table.html", {"request": request, "endpoints": endpoints},
            )
            if error:
                _flash(resp, error, "error")
            else:
                _flash(resp, "Webhook endpoint created")
            return resp

        ctx = _ctx(request)
        ctx["endpoints"] = endpoints
        return templates.TemplateResponse("webhooks/list.html", ctx)

    @app.get("/webhooks/{endpoint_id}", response_class=HTMLResponse)
    async def webhook_detail(request: Request, endpoint_id: str):
        db = _get_db()
        svc = _get_webhook_service()
        async with db.get_session() as session:
            endpoint = await svc.get_endpoint(session, endpoint_id)
            if endpoint is None:
                return HTMLResponse("Not found", status_code=404)
            deliveries = await svc.get_deliveries(session, endpoint_id=endpoint_id, limit=50)
        ctx = _ctx(request)
        ctx.update({"endpoint": endpoint, "deliveries": deliveries})
        return templates.TemplateResponse("webhooks/detail.html", ctx)

    @app.patch("/webhooks/{endpoint_id}", response_class=HTMLResponse)
    async def update_webhook(request: Request, endpoint_id: str):
        db = _get_db()
        svc = _get_webhook_service()
        form = await request.form()
        updates = {}
        for field in ("url", "secret", "description", "status"):
            if form.get(field):
                updates[field] = form[field]
        try:
            async with db.get_session() as session:
                await svc.update_endpoint(session, endpoint_id, **updates)
        except Exception:
            logger.exception("Failed to update webhook %s", endpoint_id)
        return RedirectResponse(f"/dashboard/webhooks/{endpoint_id}", status_code=302)

    @app.delete("/webhooks/{endpoint_id}")
    async def delete_webhook(request: Request, endpoint_id: str):
        db = _get_db()
        svc = _get_webhook_service()
        try:
            async with db.get_session() as session:
                await svc.delete_endpoint(session, endpoint_id)
        except Exception:
            logger.exception("Failed to delete webhook %s", endpoint_id)
        return RedirectResponse("/dashboard/webhooks", status_code=302)

    @app.post("/webhooks/{endpoint_id}/test", response_class=HTMLResponse)
    async def test_webhook(request: Request, endpoint_id: str):
        db = _get_db()
        svc = _get_webhook_service()
        async with db.get_session() as session:
            endpoint = await svc.get_endpoint(session, endpoint_id)
            if endpoint is None:
                return HTMLResponse("Not found", status_code=404)
            await svc.dispatch(
                session, "test.ping",
                {"message": "Test delivery from dashboard"},
            )
            deliveries = await svc.get_deliveries(session, endpoint_id=endpoint_id, limit=50)
        return templates.TemplateResponse("webhooks/_deliveries.html", {
            "request": request, "deliveries": deliveries, "endpoint": endpoint,
        })

    @app.post("/webhooks/deliveries/{delivery_id}/retry", response_class=HTMLResponse)
    async def retry_delivery(request: Request, delivery_id: str):
        db = _get_db()
        svc = _get_webhook_service()
        async with db.get_session() as session:
            delivery = await svc.retry_delivery(session, delivery_id)
            if delivery is None:
                return HTMLResponse("Not found", status_code=404)
            deliveries = await svc.get_deliveries(
                session, endpoint_id=delivery.endpoint_id, limit=50,
            )
            endpoint = await svc.get_endpoint(session, delivery.endpoint_id)
        return templates.TemplateResponse("webhooks/_deliveries.html", {
            "request": request, "deliveries": deliveries, "endpoint": endpoint,
        })

    # ────────────────────────────────────────────
    # Audit
    # ────────────────────────────────────────────

    @app.get("/audit/{license_id}", response_class=HTMLResponse)
    async def audit_page(request: Request, license_id: str):
        db = _get_db()
        audit_svc = _get_audit_service()
        async with db.get_session() as session:
            events = await audit_svc.get_events(session, license_id, limit=50)
        ctx = _ctx(request)
        ctx.update({"events": events, "license_id": license_id})
        return templates.TemplateResponse("audit/timeline.html", ctx)

    @app.get("/audit/{license_id}/events", response_class=HTMLResponse)
    async def audit_events_partial(
        request: Request,
        license_id: str,
        page: int = Query(1, ge=1),
    ):
        db = _get_db()
        audit_svc = _get_audit_service()
        offset = (page - 1) * 50
        async with db.get_session() as session:
            events = await audit_svc.get_events(
                session, license_id, limit=50, offset=offset,
            )
        return templates.TemplateResponse("audit/_events.html", {
            "request": request, "events": events, "license_id": license_id,
            "page": page,
        })

    return app
