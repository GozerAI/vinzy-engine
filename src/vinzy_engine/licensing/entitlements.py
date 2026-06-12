"""Entitlement resolution logic."""

from typing import Any


def resolve_entitlements(
    product_features: dict[str, Any],
    license_entitlements: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Merge product-level features with license-level entitlement overrides.

    Product features define the base feature set for a tier.
    License entitlements can override limits or disable features.

    Returns list of resolved entitlement dicts with:
        feature, enabled, limit, used, remaining
    """
    resolved = []

    # Start from product features as base
    all_features = set(product_features.keys()) | set(license_entitlements.keys())

    for feature in sorted(all_features):
        product_def = product_features.get(feature, {})
        license_def = license_entitlements.get(feature, {})

        if isinstance(product_def, bool):
            product_def = {"enabled": product_def}
        if isinstance(license_def, bool):
            license_def = {"enabled": license_def}

        enabled = license_def.get("enabled", product_def.get("enabled", True))
        limit = license_def.get("limit", product_def.get("limit"))
        used = license_def.get("used", 0)

        remaining = None
        if limit is not None:
            remaining = max(0, limit - used)

        resolved.append({
            "feature": feature,
            "enabled": enabled,
            "limit": limit,
            "used": used,
            "remaining": remaining,
        })

    return resolved
