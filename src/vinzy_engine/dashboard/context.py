"""Shared template context helpers for the dashboard."""

from starlette.requests import Request

NAV_ITEMS = [
    {"label": "Overview", "url": "/dashboard/", "icon": "home"},
    {"label": "Products", "url": "/dashboard/products", "icon": "box"},
    {"label": "Customers", "url": "/dashboard/customers", "icon": "users"},
    {"label": "Licenses", "url": "/dashboard/licenses", "icon": "key"},
    {"label": "Anomalies", "url": "/dashboard/anomalies", "icon": "alert"},
    {"label": "Webhooks", "url": "/dashboard/webhooks", "icon": "webhook"},
]

SUPER_ADMIN_ITEMS = [
    {"label": "Tenants", "url": "/dashboard/tenants", "icon": "building"},
]


def base_context(request: Request, session: dict) -> dict:
    """Build the base template context with nav items and role info."""
    role = session.get("role", "admin") if session else "admin"
    is_super = role == "super_admin"

    nav = list(NAV_ITEMS)
    if is_super:
        nav.extend(SUPER_ADMIN_ITEMS)

    # Determine active nav item from path
    path = request.url.path
    for item in nav:
        item["active"] = path == item["url"] or (
            item["url"] != "/dashboard/" and path.startswith(item["url"])
        )

    return {
        "request": request,
        "nav_items": nav,
        "role": role,
        "is_super": is_super,
    }
