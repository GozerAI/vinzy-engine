"""Cross-product entitlement composition for multi-product customers."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ComposedSource:
    """Attribution of where a composed value came from."""
    product_code: str
    license_id: str
    value: Any


@dataclass
class ComposedFeature:
    """A single composed feature with its effective value and sources."""
    feature: str
    effective_value: Any
    strategy: str
    sources: list[ComposedSource] = field(default_factory=list)


@dataclass
class ComposedResult:
    """Full composition result for a customer."""
    features: list[ComposedFeature] = field(default_factory=list)
    agents: dict[str, dict[str, Any]] = field(default_factory=dict)
    total_products: int = 0


def _get_compose_strategy(feature_def: dict, default: str = "union") -> str:
    """Extract composition strategy from a feature definition."""
    if isinstance(feature_def, dict):
        return feature_def.get("compose", default)
    return default


def _apply_strategy(strategy: str, values: list[Any]) -> Any:
    """Apply a composition strategy to a list of values."""
    if not values:
        return None

    if strategy == "sum":
        numeric = [v for v in values if isinstance(v, (int, float))]
        return sum(numeric) if numeric else None

    if strategy == "max":
        # For model tiers, define ordering
        tier_order = {"basic": 0, "standard": 1, "premium": 2, "enterprise": 3}
        if all(isinstance(v, str) for v in values):
            return max(values, key=lambda v: tier_order.get(v, -1))
        numeric = [v for v in values if isinstance(v, (int, float))]
        return max(numeric) if numeric else None

    # "union" — for booleans: any True wins; for others: first non-None
    if strategy == "union":
        if all(isinstance(v, bool) for v in values):
            return any(values)
        for v in values:
            if v is not None:
                return v
        return None

    return values[0] if values else None


def compose_customer_entitlements(
    licenses: list[Any],
    products: list[Any],
) -> ComposedResult:
    """
    Compose entitlements across multiple licenses/products.

    Each license must have: id, entitlements (dict), product_id
    Each product must have: id, code, features (dict)

    Merge strategies:
    - "sum": token limits add up across products
    - "max": take the highest tier or limit
    - "union": combine feature sets (enabled if any product enables it)
    """
    product_map = {p.id: p for p in products}
    if not licenses:
        return ComposedResult(total_products=0)

    # Collect all feature values with sources
    feature_values: dict[str, list[tuple[Any, str, str, str]]] = {}
    # (value, strategy, product_code, license_id)
    agent_values: dict[str, dict[str, list[tuple[Any, str, str]]]] = {}
    # agent_code -> field -> [(value, product_code, license_id)]

    for lic in licenses:
        product = product_map.get(lic.product_id)
        if product is None:
            continue
        product_code = product.code
        product_features = product.features or {}
        license_ents = lic.entitlements or {}

        # Merge product-level features
        all_keys = set(product_features.keys()) | set(license_ents.keys())
        for key in all_keys:
            if key == "agents":
                continue  # handle separately
            prod_val = product_features.get(key, {})
            lic_val = license_ents.get(key, {})

            # Determine the effective value for this license
            if isinstance(prod_val, bool):
                prod_val = {"enabled": prod_val}
            if isinstance(lic_val, bool):
                lic_val = {"enabled": lic_val}

            if isinstance(prod_val, dict) and isinstance(lic_val, dict):
                # Use license override where present
                effective = {**prod_val, **lic_val}
                # Determine strategy from product definition
                strategy = _get_compose_strategy(prod_val, "union")
                # For limit-like fields, compose the limit value
                if "limit" in effective:
                    default_strat = "max"
                    strategy = _get_compose_strategy(prod_val, default_strat)
                    val = effective["limit"]
                else:
                    val = effective.get("enabled", True)
            else:
                strategy = "union"
                val = lic_val if lic_val else prod_val

            if key not in feature_values:
                feature_values[key] = []
            feature_values[key].append((val, strategy, product_code, lic.id))

        # Merge agent entitlements
        prod_agents = product_features.get("agents", {})
        lic_agents = license_ents.get("agents", {})
        all_agent_codes = set(prod_agents.keys()) | set(lic_agents.keys())

        for agent_code in all_agent_codes:
            if agent_code not in agent_values:
                agent_values[agent_code] = {}

            pa = prod_agents.get(agent_code, {})
            la = lic_agents.get(agent_code, {})
            merged = {**pa, **la}

            for agent_field, agent_val in merged.items():
                if agent_field not in agent_values[agent_code]:
                    agent_values[agent_code][agent_field] = []
                agent_values[agent_code][agent_field].append(
                    (agent_val, product_code, lic.id)
                )

    # Compose features
    composed_features = []
    for feature, entries in sorted(feature_values.items()):
        values = [e[0] for e in entries]
        strategy = entries[0][1] if entries else "union"
        effective = _apply_strategy(strategy, values)
        sources = [
            ComposedSource(product_code=e[2], license_id=e[3], value=e[0])
            for e in entries
        ]
        composed_features.append(ComposedFeature(
            feature=feature,
            effective_value=effective,
            strategy=strategy,
            sources=sources,
        ))

    # Compose agents
    composed_agents: dict[str, dict[str, Any]] = {}
    for agent_code, fields in sorted(agent_values.items()):
        composed_agents[agent_code] = {}
        for field_name, entries in fields.items():
            values = [e[0] for e in entries]
            if field_name == "enabled":
                composed_agents[agent_code][field_name] = any(
                    v for v in values if isinstance(v, bool)
                ) if any(isinstance(v, bool) for v in values) else True
            elif field_name == "token_limit":
                numeric = [v for v in values if isinstance(v, (int, float))]
                composed_agents[agent_code][field_name] = sum(numeric) if numeric else None
            elif field_name == "model_tier":
                composed_agents[agent_code][field_name] = _apply_strategy("max", values)
            else:
                composed_agents[agent_code][field_name] = values[-1] if values else None

    unique_product_ids = {lic.product_id for lic in licenses if lic.product_id in product_map}
    return ComposedResult(
        features=composed_features,
        agents=composed_agents,
        total_products=len(unique_product_ids),
    )
