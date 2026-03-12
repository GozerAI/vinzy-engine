"""Agent-specific entitlement resolution for AI agent licensing."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentEntitlement:
    """Resolved entitlement for a single agent."""
    agent_code: str
    enabled: bool = True
    token_limit: int | None = None
    model_tier: str = "standard"
    extra: dict[str, Any] = field(default_factory=dict)


def resolve_agent_entitlements(
    product_features: dict[str, Any],
    license_entitlements: dict[str, Any],
) -> dict[str, AgentEntitlement]:
    """
    Merge product-level and license-level agent entitlements.

    Product features define the base:
        {"agents": {"CTO": {"enabled": true, "token_limit": 50000, "model_tier": "premium"}, ...}}

    License entitlements can override per-customer:
        {"agents": {"CTO": {"token_limit": 100000}, "CDO": {"enabled": true}}}

    License overrides product per field per agent.
    """
    product_agents = product_features.get("agents", {})
    license_agents = license_entitlements.get("agents", {})

    all_codes = set(product_agents.keys()) | set(license_agents.keys())
    result: dict[str, AgentEntitlement] = {}

    for code in sorted(all_codes):
        prod = product_agents.get(code, {})
        lic = license_agents.get(code, {})

        # License fields override product fields
        enabled = lic.get("enabled", prod.get("enabled", True))
        token_limit = lic.get("token_limit", prod.get("token_limit"))
        model_tier = lic.get("model_tier", prod.get("model_tier", "standard"))

        # Collect any extra fields not in the standard set
        standard_keys = {"enabled", "token_limit", "model_tier"}
        extra = {}
        for d in (prod, lic):
            for k, v in d.items():
                if k not in standard_keys:
                    extra[k] = v

        result[code] = AgentEntitlement(
            agent_code=code,
            enabled=enabled,
            token_limit=token_limit,
            model_tier=model_tier,
            extra=extra,
        )

    return result


def is_agent_entitled(
    product_features: dict[str, Any],
    license_entitlements: dict[str, Any],
    agent_code: str,
) -> bool:
    """Check if a specific agent is entitled (enabled)."""
    agents = resolve_agent_entitlements(product_features, license_entitlements)
    ent = agents.get(agent_code)
    if ent is None:
        return False
    return ent.enabled


def get_agent_quota(
    product_features: dict[str, Any],
    license_entitlements: dict[str, Any],
    agent_code: str,
    metric: str,
) -> int | None:
    """Get a specific quota metric for an agent (e.g., 'token_limit')."""
    agents = resolve_agent_entitlements(product_features, license_entitlements)
    ent = agents.get(agent_code)
    if ent is None:
        return None
    # Check standard fields first, then extra
    if metric == "token_limit":
        return ent.token_limit
    return ent.extra.get(metric)


def get_entitled_agents(
    product_features: dict[str, Any],
    license_entitlements: dict[str, Any],
) -> list[str]:
    """Return list of enabled agent codes."""
    agents = resolve_agent_entitlements(product_features, license_entitlements)
    return [code for code, ent in agents.items() if ent.enabled]
