#!/usr/bin/env python3
"""Create Stripe Products and Prices for the GozerAI ecosystem.

Usage:
    # Dry run (shows what would be created):
    python scripts/setup_stripe.py --dry-run

    # Create in Stripe test mode:
    STRIPE_SECRET_KEY=sk_test_... python scripts/setup_stripe.py

    # Create in Stripe live mode:
    STRIPE_SECRET_KEY=sk_live_... python scripts/setup_stripe.py

    # Founder phase only (default):
    python scripts/setup_stripe.py --phase founder

    # All phases (prelaunch prep):
    python scripts/setup_stripe.py --phase full

Outputs the VINZY_STRIPE_PRICE_MAP JSON that should be set as an env var
for the Vinzy-Engine provisioning router.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from vinzy_engine.licensing.tier_templates import (
    PRICING, PRODUCT_SEEDS, BUNDLE_DEFINITIONS, FOUNDER_PRICING, PHASE_CONFIG,
)

# ── Stripe product feature lists (shown in Checkout, Portal, Pricing Tables) ──
PLATFORM_FEATURES = {
    "Pro": [
        {"name": "All 10 GozerAI products"},
        {"name": "5,000 AI credits/month"},
        {"name": "3 machine activations"},
        {"name": "SSO (OIDC)"},
        {"name": "API access"},
        {"name": "Overage at $0.018/credit"},
    ],
    "Growth": [
        {"name": "All 10 GozerAI products"},
        {"name": "25,000 AI credits/month"},
        {"name": "10 machine activations"},
        {"name": "SSO (OIDC)"},
        {"name": "White-label support"},
        {"name": "Executive reports & analytics"},
        {"name": "Overage at $0.014/credit"},
    ],
    "Scale": [
        {"name": "All 10 GozerAI products"},
        {"name": "80,000 AI credits/month"},
        {"name": "Unlimited machine activations"},
        {"name": "SSO (SAML + OIDC)"},
        {"name": "White-label support"},
        {"name": "SLA guarantee"},
        {"name": "Custom integrations"},
        {"name": "Overage at $0.010/credit"},
    ],
}

SINGLE_FEATURES = {
    "Pro": [
        {"name": "1 GozerAI product of your choice"},
        {"name": "1,500 AI credits/month"},
        {"name": "3 machine activations"},
        {"name": "API access"},
    ],
    "Growth": [
        {"name": "1 GozerAI product of your choice"},
        {"name": "6,000 AI credits/month"},
        {"name": "10 machine activations"},
        {"name": "White-label support"},
        {"name": "API access"},
    ],
}

BUNDLE_FEATURES = {
    "Small Bundle Pro": [
        {"name": "2–3 GozerAI products"},
        {"name": "3,000 AI credits/month"},
        {"name": "3 machine activations"},
        {"name": "API access"},
    ],
    "Small Bundle Growth": [
        {"name": "2–3 GozerAI products"},
        {"name": "14,000 AI credits/month"},
        {"name": "10 machine activations"},
        {"name": "White-label support"},
        {"name": "API access"},
    ],
    "Medium Bundle Pro": [
        {"name": "4–6 GozerAI products"},
        {"name": "5,000 AI credits/month"},
        {"name": "3 machine activations"},
        {"name": "API access"},
    ],
    "Medium Bundle Growth": [
        {"name": "4–6 GozerAI products"},
        {"name": "22,000 AI credits/month"},
        {"name": "10 machine activations"},
        {"name": "White-label support"},
        {"name": "API access"},
    ],
}

ARCLANE_FEATURES = {
    "Pro": [
        {"name": "AI business builder"},
        {"name": "20 cycle credits/month"},
        {"name": "All templates (SaaS, content, landing)"},
        {"name": "Advanced analytics & notifications"},
    ],
}


def _make_prices(tier_key: str, prices: dict, cycles: list[str]) -> list:
    """Build Stripe price entries for the given billing cycles."""
    result = []
    if "monthly" in cycles and "monthly" in prices:
        result.append({
            "lookup": f"{tier_key}_monthly",
            "unit_amount": prices["monthly"] * 100,
            "currency": "usd",
            "interval": "month",
            "interval_count": 1,
        })
    if "quarterly" in cycles and "quarterly" in prices:
        result.append({
            "lookup": f"{tier_key}_quarterly",
            "unit_amount": prices["quarterly"] * 100,
            "currency": "usd",
            "interval": "month",
            "interval_count": 3,
        })
    if "yearly" in cycles and "yearly" in prices:
        result.append({
            "lookup": f"{tier_key}_yearly",
            "unit_amount": prices["yearly"] * 100,
            "currency": "usd",
            "interval": "year",
            "interval_count": 1,
        })
    return result


def build_stripe_products(phase: str = "founder") -> list:
    """Build Stripe product definitions for a given rollout phase."""
    cycles = PHASE_CONFIG[phase]["billing_cycles"]
    available = PHASE_CONFIG[phase]["available_tiers"]
    products = []

    # Platform tiers
    for tier_key, tier_label in [
        ("platform_pro", "Pro"),
        ("platform_growth", "Growth"),
        ("platform_scale", "Scale"),
    ]:
        base_tier = tier_key.split("_", 1)[1]  # "pro", "growth", "scale"
        if base_tier not in available:
            continue

        # Use founder pricing if available and in founder phase
        if phase == "founder" and tier_key in FOUNDER_PRICING:
            prices = FOUNDER_PRICING[tier_key]
            stripe_name = f"GozerAI Platform — {tier_label} (Founder)"
        else:
            prices = PRICING[tier_key]
            stripe_name = f"GozerAI Platform — {tier_label}"

        products.append({
            "product_code": "PLATFORM",
            "stripe_name": stripe_name,
            "stripe_description": f"Full GozerAI platform access — all 10 products ({tier_label} tier)",
            "tier": tier_key,
            "features": PLATFORM_FEATURES.get(tier_label, []),
            "prices": _make_prices(tier_key, prices, cycles),
        })

    # Single product tiers
    for tier_key, tier_label in [
        ("single_pro", "Pro"),
        ("single_growth", "Growth"),
    ]:
        base_tier = tier_key.split("_", 1)[1]
        if base_tier not in available:
            continue

        if phase == "founder" and tier_key in FOUNDER_PRICING:
            prices = FOUNDER_PRICING[tier_key]
            stripe_name = f"GozerAI Single Product — {tier_label} (Founder)"
        else:
            prices = PRICING[tier_key]
            stripe_name = f"GozerAI Single Product — {tier_label}"

        products.append({
            "product_code": "SINGLE",
            "stripe_name": stripe_name,
            "stripe_description": f"Single GozerAI product access ({tier_label} tier)",
            "tier": tier_key,
            "features": SINGLE_FEATURES.get(tier_label, []),
            "prices": _make_prices(tier_key, prices, cycles),
        })

    # Bundle tiers
    for tier_key, tier_label in [
        ("bundle_small_pro", "Small Bundle Pro"),
        ("bundle_small_growth", "Small Bundle Growth"),
        ("bundle_medium_pro", "Medium Bundle Pro"),
        ("bundle_medium_growth", "Medium Bundle Growth"),
    ]:
        # Extract base tier from key (e.g., "bundle_small_pro" -> "pro")
        base_tier = tier_key.rsplit("_", 1)[1]
        if base_tier not in available:
            continue

        if phase == "founder" and tier_key in FOUNDER_PRICING:
            prices = FOUNDER_PRICING[tier_key]
            stripe_name = f"GozerAI {tier_label} (Founder)"
        else:
            prices = PRICING[tier_key]
            stripe_name = f"GozerAI {tier_label}"

        size = "2-3 products" if "small" in tier_key else "4-6 products"
        products.append({
            "product_code": "BUNDLE",
            "stripe_name": stripe_name,
            "stripe_description": f"GozerAI bundle access — {size} ({tier_label})",
            "tier": tier_key,
            "features": BUNDLE_FEATURES.get(tier_label, []),
            "prices": _make_prices(tier_key, prices, cycles),
        })

    # Arclane (single Pro tier for now)
    if "pro" in available:
        if phase == "founder" and "arclane_pro" in FOUNDER_PRICING:
            prices = FOUNDER_PRICING["arclane_pro"]
            stripe_name = "Arclane — Pro (Founder)"
        else:
            prices = PRICING["arclane_pro"]
            stripe_name = "Arclane — Pro"

        products.append({
            "product_code": "ARC",
            "stripe_name": stripe_name,
            "stripe_description": "Arclane AI business builder (Pro tier)",
            "tier": "arclane_pro",
            "features": ARCLANE_FEATURES["Pro"],
            "prices": _make_prices("arclane_pro", prices, cycles),
        })

    # Themed bundles (use underlying small/medium bundle pricing)
    for bundle_key, bundle_def in BUNDLE_DEFINITIONS.items():
        size = bundle_def["size"]  # "small" or "medium"
        for tier_suffix in ["pro", "growth"]:
            if tier_suffix not in available:
                continue
            tier_key = f"bundle_{size}_{tier_suffix}"
            if tier_key not in PRICING:
                continue

            if phase == "founder" and tier_key in FOUNDER_PRICING:
                prices = FOUNDER_PRICING[tier_key]
                stripe_name = f"GozerAI {bundle_def['name']} — {tier_suffix.title()} (Founder)"
            else:
                prices = PRICING[tier_key]
                stripe_name = f"GozerAI {bundle_def['name']} — {tier_suffix.title()}"

            lookup_prefix = f"bundle_{bundle_key}_{tier_suffix}"
            product_names = ", ".join(bundle_def["products"])
            products.append({
                "product_code": f"BUNDLE_{bundle_key.upper()}",
                "stripe_name": stripe_name,
                "stripe_description": f"{bundle_def['name']}: {product_names} ({tier_suffix.title()} tier)",
                "tier": lookup_prefix,
                "features": BUNDLE_FEATURES.get(
                    f"{'Small' if size == 'small' else 'Medium'} Bundle {tier_suffix.title()}", []
                ),
                "prices": _make_prices(lookup_prefix, prices, cycles),
            })

    return products


def dry_run(phase: str = "founder"):
    """Print what would be created without calling Stripe."""
    products = build_stripe_products(phase)
    print(f"=== DRY RUN — Stripe Products & Prices ({phase} phase) ===\n")

    price_map = {}
    for product in products:
        print(f"Product: {product['stripe_name']}")
        print(f"  Code: {product['product_code']}, Tier: {product['tier']}")
        print(f"  Description: {product['stripe_description']}")
        if product.get("features"):
            print(f"  Features:")
            for feat in product["features"]:
                print(f"    • {feat['name']}")
        for price in product["prices"]:
            amount = price["unit_amount"] / 100
            interval = price["interval"]
            if price.get("interval_count", 1) > 1:
                interval = f"{price['interval_count']}x {interval}"
            print(f"  Price: ${amount:.0f}/{interval} -> lookup: {price['lookup']}")
            price_map[price["lookup"]] = f"price_PLACEHOLDER_{price['lookup']}"
        print()

    print("=== VINZY_STRIPE_PRICE_MAP (template) ===")
    print(json.dumps(price_map, indent=2))
    print("\nReplace price_PLACEHOLDER_* with actual Stripe Price IDs after creation.")

    print(f"\n=== Themed Bundles (reference) ===")
    for key, bundle in BUNDLE_DEFINITIONS.items():
        print(f"  {bundle['name']}: {', '.join(bundle['products'])} ({bundle['size']} bundle)")


def create_in_stripe(phase: str = "founder"):
    """Create products and prices in Stripe, output the price map."""
    try:
        import stripe
    except ImportError:
        print("ERROR: stripe package not installed. Run: pip install stripe")
        sys.exit(1)

    api_key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not api_key:
        print("ERROR: Set STRIPE_SECRET_KEY environment variable")
        sys.exit(1)

    stripe.api_key = api_key
    products = build_stripe_products(phase)

    mode = "TEST" if "sk_test_" in api_key else "LIVE"
    print(f"=== Creating Stripe Products & Prices ({mode} mode, {phase} phase) ===\n")

    price_map = {}

    for product_def in products:
        # Check if product already exists by searching for metadata match
        existing = stripe.Product.search(
            query=f"metadata['gozerai_tier']:'{product_def['tier']}' "
                  f"AND metadata['gozerai_code']:'{product_def['product_code']}'",
        )

        if existing.data:
            stripe_product = existing.data[0]
            # Update features on existing product to keep them in sync
            stripe.Product.modify(
                stripe_product.id,
                features=product_def.get("features", []),
            )
            print(f"  [exists] {product_def['stripe_name']} -> {stripe_product.id} (features synced)")
        else:
            stripe_product = stripe.Product.create(
                name=product_def["stripe_name"],
                description=product_def["stripe_description"],
                features=product_def.get("features", []),
                metadata={
                    "gozerai_code": product_def["product_code"],
                    "gozerai_tier": product_def["tier"],
                },
            )
            print(f"  [created] {product_def['stripe_name']} -> {stripe_product.id}")

        # Create prices
        for price_def in product_def["prices"]:
            # Check for existing price with same lookup key
            existing_prices = stripe.Price.search(
                query=f"lookup_key:'{price_def['lookup']}'",
            )

            if existing_prices.data:
                price_obj = existing_prices.data[0]
                print(f"    [exists] {price_def['lookup']} -> {price_obj.id}")
            else:
                recurring = {"interval": price_def["interval"]}
                if price_def.get("interval_count", 1) > 1:
                    recurring["interval_count"] = price_def["interval_count"]
                price_obj = stripe.Price.create(
                    product=stripe_product.id,
                    unit_amount=price_def["unit_amount"],
                    currency=price_def["currency"],
                    recurring=recurring,
                    lookup_key=price_def["lookup"],
                    metadata={
                        "gozerai_code": product_def["product_code"],
                        "gozerai_tier": product_def["tier"],
                    },
                )
                print(f"    [created] {price_def['lookup']} -> {price_obj.id}")

            price_map[price_def["lookup"]] = price_obj.id

    print("\n=== VINZY_STRIPE_PRICE_MAP ===")
    price_map_json = json.dumps(price_map, indent=2)
    print(price_map_json)

    print(f"\n=== Set this as your environment variable ===")
    # Single-line for .env file
    price_map_oneline = json.dumps(price_map)
    print(f'VINZY_STRIPE_PRICE_MAP=\'{price_map_oneline}\'')

    print(f"\n=== Webhook setup ===")
    print("1. Go to Stripe Dashboard -> Developers -> Webhooks")
    print("2. Add endpoint: https://api.gozerai.com/v1/provisioning/webhooks/stripe")
    print("3. Select event: checkout.session.completed")
    print("4. Copy the signing secret and set:")
    print("   VINZY_STRIPE_WEBHOOK_SECRET='whsec_...'")

    return price_map


def main():
    phase = "founder"
    for arg in sys.argv[1:]:
        if arg.startswith("--phase"):
            # Handle --phase=X or --phase X
            if "=" in arg:
                phase = arg.split("=", 1)[1]
            else:
                idx = sys.argv.index(arg)
                if idx + 1 < len(sys.argv):
                    phase = sys.argv[idx + 1]

    if phase not in PHASE_CONFIG:
        print(f"ERROR: Unknown phase '{phase}'. Must be one of: {', '.join(PHASE_CONFIG)}")
        sys.exit(1)

    if "--dry-run" in sys.argv:
        dry_run(phase)
    else:
        create_in_stripe(phase)


if __name__ == "__main__":
    main()
