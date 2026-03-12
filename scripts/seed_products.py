#!/usr/bin/env python3
"""Seed the database with the 5 commercial products.

Usage:
    python -m scripts.seed_products
    # or from project root:
    python scripts/seed_products.py
"""

import asyncio
import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from vinzy_engine.common.config import get_settings
from vinzy_engine.common.database import DatabaseManager
from vinzy_engine.licensing.service import LicensingService
from vinzy_engine.licensing.tier_templates import PRODUCT_SEEDS, resolve_tier_features


async def seed_products() -> None:
    settings = get_settings()
    db = DatabaseManager(settings)
    await db.init()
    await db.create_all()

    svc = LicensingService(settings)

    async with db.get_session() as session:
        for seed in PRODUCT_SEEDS:
            existing = await svc.get_product_by_code(session, seed["code"])
            if existing:
                print(f"  [skip] {seed['code']} ({seed['name']}) already exists")
                continue

            # Set product-level features to enterprise (superset) so
            # entitlement resolution can downgrade per license tier
            features = resolve_tier_features(seed["code"], "enterprise")

            await svc.create_product(
                session,
                code=seed["code"],
                name=seed["name"],
                description=seed["description"],
                default_tier=seed["default_tier"],
                features=features,
            )
            print(f"  [created] {seed['code']} ({seed['name']})")

        await session.commit()

    await db.close()
    print("\nDone. 5 products seeded.")


if __name__ == "__main__":
    asyncio.run(seed_products())
