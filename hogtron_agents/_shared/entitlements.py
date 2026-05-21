"""Per-tenant agent entitlement gate.

When a customer subscribes to a subset of agents (e.g. Sentinel + Herald
only), the other department entrypoints must refuse work for that tenant.
This module is the single check; departments call `require_agent_enabled`
at the top of their `do()` / `write()` method.

Behaviour
---------
- If `brief.context` carries a `tenant_config` (TenantConfig instance) OR
  a `tenant_id` (string), the gate checks `tenant_config.agents_enabled`
  against the agent id and raises `AgentNotEntitled` if disabled.
- If neither is present, the gate is **open** (returns silently). This
  preserves backward compatibility with internal callers — the CEO loop,
  FactoryHQ scripts, and APScheduler jobs all invoke department heads
  without tenant context today.
- `tenant_id` alone triggers a load via `loader_from_env()`. Callers can
  override by passing their own loader in `context["tenant_config_loader"]`.

Why fail-open
-------------
Forcing tenant context on every internal call would be a large refactor
outside the scope of this work. Customer-facing surfaces (the Dashboard,
the public Sentinel sidecar) always pass tenant context, so they get
gated correctly. Internal callers are trusted.
"""
from __future__ import annotations

from typing import Any, Optional

from ..sentinel._tenant_config import (
    TenantConfig,
    TenantConfigLoader,
    TenantNotFound,
    loader_from_env,
)


class AgentNotEntitled(PermissionError):
    """Raised when a tenant invokes an agent they aren't subscribed to."""

    def __init__(self, tenant_id: str, agent_id: str):
        self.tenant_id = tenant_id
        self.agent_id = agent_id
        super().__init__(
            f"tenant {tenant_id!r} is not entitled to agent {agent_id!r}. "
            f"Enable via agents_enabled.{_AGENT_FLAG_MAP.get(agent_id, agent_id)} "
            f"in the tenant config."
        )


# Catalog agent id -> AgentsEnabled boolean field name.
# Sentinel is intentionally absent — it is always-on per its docstring.
# `herald` aliases `marketing` (Herald = social_media_manager, which lives
# inside the Marketing department and shares its enable flag).
_AGENT_FLAG_MAP: dict[str, str] = {
    "research": "research",
    "marketing": "marketing",
    "herald": "marketing",
    "sales": "sales",
    "creative": "creative",
    "operations": "ops",
    "ledger": "ledger",
}


def require_agent_enabled(context: dict[str, Any], agent_id: str) -> None:
    """Raise AgentNotEntitled if the tenant in `context` hasn't enabled `agent_id`.

    Silent (no-op) if there is no tenant in context — see module docstring.
    """
    config = _resolve_tenant_config(context)
    if config is None:
        return  # fail-open for internal callers
    if not is_agent_enabled(config, agent_id):
        raise AgentNotEntitled(config.tenant_id, agent_id)


def is_agent_enabled(config: TenantConfig, agent_id: str) -> bool:
    """Pure check: does this tenant config have `agent_id` enabled?"""
    flag = _AGENT_FLAG_MAP.get(agent_id)
    if flag is None:
        # Unknown agent id — treat as "not in the catalog", fail closed.
        return False
    return bool(getattr(config.agents_enabled, flag, False))


def _resolve_tenant_config(context: dict[str, Any]) -> Optional[TenantConfig]:
    """Pull a TenantConfig out of a brief.context dict, or return None.

    Resolution order:
      1. context["tenant_config"]            (TenantConfig instance)
      2. context["tenant_id"] + loader       (loader from context, then env)
    """
    direct = context.get("tenant_config")
    if isinstance(direct, TenantConfig):
        return direct

    tenant_id = context.get("tenant_id")
    if not tenant_id:
        return None

    loader: Optional[TenantConfigLoader] = context.get("tenant_config_loader")
    if loader is None:
        loader = loader_from_env()
    try:
        return loader.load(tenant_id)
    except TenantNotFound:
        # Treat missing tenant as fail-open here — callers can pre-validate
        # the tenant exists with their own error path. The gate's job is
        # entitlement, not existence.
        return None
