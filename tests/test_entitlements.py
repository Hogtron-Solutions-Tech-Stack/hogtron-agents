"""Sanity tests for the per-tenant agent entitlement gate.

Run with: `pytest tests/test_entitlements.py` from the repo root.
Imports use absolute paths from `hogtron_agents.*` so they work without
installing the package (pyproject layout supports both).
"""
from __future__ import annotations

import pytest

from hogtron_agents._shared.entitlements import (
    AgentNotEntitled,
    is_agent_enabled,
    require_agent_enabled,
)
from hogtron_agents.sentinel._tenant_config import (
    AgentsEnabled,
    ClientInfo,
    InMemoryTenantConfigLoader,
    TenantConfig,
)


def _tenant(tid: str, **flags) -> TenantConfig:
    """Build a minimal TenantConfig with the given agent flags."""
    return TenantConfig(
        client=ClientInfo(id=tid, name=tid.title()),
        agents_enabled=AgentsEnabled(**flags),
    )


# --- pure flag check ---------------------------------------------------------

def test_is_agent_enabled_true_when_flag_set():
    cfg = _tenant("acme", research=True)
    assert is_agent_enabled(cfg, "research") is True


def test_is_agent_enabled_false_when_flag_unset():
    cfg = _tenant("acme")
    assert is_agent_enabled(cfg, "research") is False


def test_herald_aliases_marketing():
    """Herald is the social_media_manager subpackage of Marketing; one flag."""
    cfg = _tenant("acme", marketing=True)
    assert is_agent_enabled(cfg, "marketing") is True
    assert is_agent_enabled(cfg, "herald") is True


def test_operations_aliases_ops_field():
    """The AgentsEnabled field is `ops` for historical reasons; agent id is `operations`."""
    cfg = _tenant("acme", ops=True)
    assert is_agent_enabled(cfg, "operations") is True


def test_unknown_agent_id_fails_closed():
    """An unknown agent id is not in the catalog; deny rather than allow."""
    cfg = _tenant("acme", research=True, marketing=True)
    assert is_agent_enabled(cfg, "nonexistent_agent") is False


# --- gate behaviour ---------------------------------------------------------

def test_gate_passes_when_enabled():
    cfg = _tenant("acme", research=True)
    require_agent_enabled({"tenant_config": cfg}, "research")  # no raise


def test_gate_raises_when_disabled():
    cfg = _tenant("acme", research=False)
    with pytest.raises(AgentNotEntitled) as exc:
        require_agent_enabled({"tenant_config": cfg}, "research")
    assert exc.value.tenant_id == "acme"
    assert exc.value.agent_id == "research"


def test_gate_resolves_via_tenant_id_and_loader():
    loader = InMemoryTenantConfigLoader()
    loader.add(_tenant("acme", sales=True))
    context = {"tenant_id": "acme", "tenant_config_loader": loader}
    require_agent_enabled(context, "sales")  # no raise
    with pytest.raises(AgentNotEntitled):
        require_agent_enabled(context, "research")


def test_gate_open_when_no_tenant_in_context():
    """Internal callers (CEO loop, Factory scripts) pass no tenant — gate must pass."""
    require_agent_enabled({}, "research")          # empty context
    require_agent_enabled({"unrelated": 1}, "marketing")  # context without tenant_id


def test_gate_open_when_tenant_id_unknown_to_loader():
    """Tenant existence isn't the gate's job — entitlement is."""
    loader = InMemoryTenantConfigLoader()  # empty
    context = {"tenant_id": "ghost", "tenant_config_loader": loader}
    require_agent_enabled(context, "research")  # no raise — caller validates existence


# --- integration with department heads --------------------------------------

def test_research_blocks_when_not_entitled():
    """End-to-end: a brief with a disabled tenant should be refused by Research.do()."""
    from hogtron_agents.research import Research, ResearchBrief

    cfg = _tenant("acme", research=False, marketing=True)
    research = Research()
    brief = ResearchBrief(
        kind="seo_audit",
        payload={"domain": "example.com"},
        context={"tenant_config": cfg},
    )
    with pytest.raises(AgentNotEntitled):
        research.do(brief)


def test_marketing_blocks_when_not_entitled():
    from hogtron_agents.marketing import Marketing, MarketingBrief

    cfg = _tenant("acme", marketing=False, research=True)
    marketing = Marketing()
    brief = MarketingBrief(
        kind="caption",
        payload={"topic": "spring sale"},
        context={"tenant_config": cfg},
    )
    with pytest.raises(AgentNotEntitled):
        marketing.write(brief)


def test_creative_blocks_when_not_entitled():
    from hogtron_agents.creative import Creative, CreativeBrief

    cfg = _tenant("acme", creative=False)
    creative = Creative()
    brief = CreativeBrief(
        kind="mockup",
        payload={"prompt": "homepage hero"},
        context={"tenant_config": cfg},
    )
    with pytest.raises(AgentNotEntitled):
        creative.design(brief)


def test_sales_blocks_when_not_entitled():
    from hogtron_agents.sales import Sales, SalesBrief

    cfg = _tenant("acme", sales=False)
    sales = Sales()
    brief = SalesBrief(
        kind="proposal",
        payload={"client": "Acme Co"},
        context={"tenant_config": cfg},
    )
    with pytest.raises(AgentNotEntitled):
        sales.build(brief)
