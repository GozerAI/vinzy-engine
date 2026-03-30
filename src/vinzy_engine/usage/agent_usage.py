"""Agent-aware usage aggregation for delegation metering."""

from typing import Any

AGENT_METRIC_PREFIX = "agent."


def parse_agent_metric(metric: str) -> tuple[str, str] | None:
    """
    Parse an agent-prefixed metric string.

    "agent.CTO.tokens" → ("CTO", "tokens")
    "agent.CFO.delegations" → ("CFO", "delegations")
    "api_calls" → None
    """
    if not metric.startswith(AGENT_METRIC_PREFIX):
        return None
    parts = metric[len(AGENT_METRIC_PREFIX):].split(".", 1)
    if len(parts) != 2:
        return None
    return parts[0], parts[1]


def aggregate_agent_usage(
    records: list[dict[str, Any]],
) -> dict[str, dict[str, float]]:
    """
    Group usage records by agent_code and sum per sub_metric.

    Input: [{"metric": "agent.CTO.tokens", "value": 1000}, ...]
    Output: {"CTO": {"tokens": 1000, ...}, ...}
    """
    result: dict[str, dict[str, float]] = {}

    for record in records:
        metric = record.get("metric", "")
        value = record.get("value", 0.0)
        parsed = parse_agent_metric(metric)
        if parsed is None:
            continue
        agent_code, sub_metric = parsed
        if agent_code not in result:
            result[agent_code] = {}
        result[agent_code][sub_metric] = result[agent_code].get(sub_metric, 0.0) + value

    return result


def check_agent_quota(
    agent_usage: dict[str, float],
    agent_entitlement: dict[str, Any],
) -> dict[str, Any]:
    """
    Check if an agent's usage is within its entitlement quotas.

    agent_usage: {"tokens": 5000, "delegations": 12}
    agent_entitlement: {"token_limit": 10000, "enabled": True}

    Returns {"within_quota": bool, "violations": [...]}
    """
    violations = []

    # Check token_limit
    token_limit = agent_entitlement.get("token_limit")
    token_usage = agent_usage.get("tokens", 0.0)
    if token_limit is not None and token_usage > token_limit:
        violations.append({
            "metric": "tokens",
            "limit": token_limit,
            "used": token_usage,
            "overage": token_usage - token_limit,
        })

    return {
        "within_quota": len(violations) == 0,
        "violations": violations,
    }
