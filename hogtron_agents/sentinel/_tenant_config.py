"""Tenant config loader — typed access to client_profile.yaml.

When Sentinel acts on behalf of a tenant (HogTron itself for the
website forms, or any future client), every handler needs the same
context: brand voice, contact details, approval rules, integration
configs (GBP location ID, etc).

That context lives in `client_profile.yaml` — the output of the Tally
onboarding intake we shipped 2026-05-15. This module:

  1. Defines TenantConfig as a Pydantic model (the typed shape)
  2. Provides a Loader Protocol so the sidecar can read configs from
     different backends (filesystem for dev, Supabase for prod)
  3. Ships two reference loaders: FileTenantConfigLoader (reads from
     a directory of YAMLs) and InMemoryTenantConfigLoader (tests)

The Supabase backend is intentionally deferred — defining the Protocol
+ a file-backed reference impl unblocks all downstream code while we
decide where activated tenants actually live (Supabase table? Private
repo? Env-injected JSON?). The unknowns there don't need to block the
Sentinel build.

Shape matches the intake form's YAML output exactly, plus optional
sections for Sentinel-specific configs (review response, intake form
behaviour) that the operator adds manually when activating a tenant.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal, Optional, Protocol

from pydantic import BaseModel, Field
import yaml


# --- Core sections (match the intake form exactly) ---------------------

class ClientInfo(BaseModel):
    """Top-level identity. `id` is the URL-safe slug used as a stable
    handle across the system (Supabase rows, file names, etc)."""
    id: str
    name: str
    industry: str = ""
    locations: list[str] = Field(default_factory=list)
    website: str = ""
    founded: str = ""


class BrandColors(BaseModel):
    primary: str = ""
    accent: str = ""


class Brand(BaseModel):
    voice: list[str] = Field(default_factory=list)
    voice_avoid: list[str] = Field(default_factory=list)
    colors: BrandColors = Field(default_factory=BrandColors)
    logo_url: str = ""
    taglines: list[str] = Field(default_factory=list)


class Audience(BaseModel):
    icp: str = ""
    pain_points: list[str] = Field(default_factory=list)
    channels: list[str] = Field(default_factory=list)


class AgentsEnabled(BaseModel):
    """Per-agent activation flags. Names match the dept callsigns
    (lowercase) in hogtron_agents."""
    creative: bool = False
    research: bool = False
    marketing: bool = False
    sales: bool = False
    ops: bool = False
    ledger: bool = False
    # Sentinel is always-on once a tenant exists; not represented here.


# Approval value type — keeps casts simple downstream.
ApprovalRule = Literal["require_human", "auto"]


class ApprovalRules(BaseModel):
    """Per-agent-artifact approval gates. Keys match the spec form:
    <agent>_<artifact>. Default everywhere is `require_human` (safer)."""
    creative_drafts:  ApprovalRule = "require_human"
    research_reports: ApprovalRule = "require_human"
    marketing_posts:  ApprovalRule = "require_human"
    sales_proposals:  ApprovalRule = "require_human"
    ops_publishes:    ApprovalRule = "require_human"
    ledger_writes:    ApprovalRule = "require_human"


class TeamMember(BaseModel):
    name: str = ""
    email: str = ""


class IntegrationFlag(BaseModel):
    """Most integrations expose just a connected bool. Email also carries
    a provider string (Mailchimp, Klaviyo, etc)."""
    connected: bool = False


class EmailIntegration(IntegrationFlag):
    provider: str = ""


class Integrations(BaseModel):
    google_business_profile: IntegrationFlag = Field(default_factory=IntegrationFlag)
    instagram: IntegrationFlag = Field(default_factory=IntegrationFlag)
    shopify:   IntegrationFlag = Field(default_factory=IntegrationFlag)
    email:     EmailIntegration = Field(default_factory=EmailIntegration)


# --- Sentinel-specific extensions (operator adds manually) -------------

class ReviewResponseApprovalRules(BaseModel):
    """Per-star-rating approval for posting review replies. Safer
    defaults: only 5★ auto-posts; <5★ queues for human review."""
    auto_post_5_star:    bool = False
    auto_post_4_star:    bool = False
    auto_post_below_4:   bool = False


class ReviewResponseConfig(BaseModel):
    """Per-tenant config for the GBP review responder. When `enabled` is
    false (default), Sentinel ignores review-response work for this
    tenant."""
    enabled: bool = False
    gbp_location_id: str = ""           # "accounts/xxx/locations/yyy"
    signature: str = ""                 # appended verbatim to each reply
    phone_to_mention: str = ""          # offered in negative replies
    services_summary: str = ""          # 1-line summary baked into prompt
    business_context: str = ""          # longer paragraph for prompt context
    word_limit: int = 75
    poll_interval_minutes: int = 60
    backfill_rate_per_hour: int = 8     # cap during catch-up of old reviews
    approval_rules: ReviewResponseApprovalRules = Field(default_factory=ReviewResponseApprovalRules)


class IntakeFormBehavior(BaseModel):
    enabled: bool = True
    require_consent: bool = True


class IntakeConfig(BaseModel):
    """Per-form-name behaviour. Forms keyed here are the ones the
    sidecar accepts inbound from the tenant's site."""
    capacity_audit:   IntakeFormBehavior = Field(default_factory=IntakeFormBehavior)
    contact_form:     IntakeFormBehavior = Field(default_factory=IntakeFormBehavior)
    extra: dict[str, IntakeFormBehavior] = Field(default_factory=dict)


# --- Top-level config --------------------------------------------------

class TenantConfig(BaseModel):
    """Full per-tenant config. The first 7 sections match the intake
    YAML 1:1; the last 2 are Sentinel extensions added during
    activation. Unknown YAML keys are preserved in `_extra` so future
    additions don't crash old loaders."""
    client: ClientInfo
    brand: Brand = Field(default_factory=Brand)
    audience: Audience = Field(default_factory=Audience)
    agents_enabled: AgentsEnabled = Field(default_factory=AgentsEnabled)
    approval_rules: ApprovalRules = Field(default_factory=ApprovalRules)
    team_access: list[TeamMember] = Field(default_factory=list)
    integrations: Integrations = Field(default_factory=Integrations)

    # Sentinel extensions
    review_response_config: ReviewResponseConfig = Field(default_factory=ReviewResponseConfig)
    intake_config: IntakeConfig = Field(default_factory=IntakeConfig)

    # Catch-all for unrecognised top-level keys (preserve, don't lose)
    extra: dict[str, Any] = Field(default_factory=dict)

    @property
    def tenant_id(self) -> str:
        """Alias for client.id — the primary handle used everywhere."""
        return self.client.id

    def brand_voice_block(self) -> str:
        """Render brand voice + voice_avoid as a prompt-ready block.
        Used by Marketing/HERALD handlers when generating tenant-voice
        content."""
        bits = []
        if self.brand.voice:
            bits.append("Voice (be these things): " + ", ".join(self.brand.voice))
        if self.brand.voice_avoid:
            bits.append("Avoid (never sound like): " + ", ".join(self.brand.voice_avoid))
        return "\n".join(bits)


# --- Loader Protocol + reference impls ---------------------------------

class TenantConfigLoader(Protocol):
    """Loads tenant configs by id. Implementations choose the backend
    (filesystem, Supabase, env vars, etc)."""

    def load(self, tenant_id: str) -> TenantConfig:
        """Return the config or raise TenantNotFound."""
        ...

    def exists(self, tenant_id: str) -> bool:
        """Cheap check without parsing the whole YAML."""
        ...


class TenantNotFound(KeyError):
    """Raised when a loader can't find the requested tenant."""


class FileTenantConfigLoader:
    """Loads from a directory of <tenant_id>.yaml files.

    Suitable for local dev + bundled-with-sidecar setups. The
    directory path is configurable so the loader works whether the
    repo layout has `clients/`, `tenants/`, or something custom.
    """

    def __init__(self, base_dir: Path | str):
        self.base_dir = Path(base_dir)

    def _path(self, tenant_id: str) -> Path:
        return self.base_dir / f"{tenant_id}.yaml"

    def exists(self, tenant_id: str) -> bool:
        return self._path(tenant_id).is_file()

    def load(self, tenant_id: str) -> TenantConfig:
        path = self._path(tenant_id)
        if not path.is_file():
            raise TenantNotFound(tenant_id)
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return _from_raw(raw)


class InMemoryTenantConfigLoader:
    """In-memory loader for tests. Pre-populate via add()."""

    def __init__(self):
        self._store: dict[str, TenantConfig] = {}

    def add(self, config: TenantConfig) -> None:
        self._store[config.tenant_id] = config

    def add_raw(self, raw: dict) -> TenantConfig:
        config = _from_raw(raw)
        self.add(config)
        return config

    def exists(self, tenant_id: str) -> bool:
        return tenant_id in self._store

    def load(self, tenant_id: str) -> TenantConfig:
        if tenant_id not in self._store:
            raise TenantNotFound(tenant_id)
        return self._store[tenant_id]


# --- Helpers ------------------------------------------------------------

def _from_raw(raw: dict) -> TenantConfig:
    """Parse a YAML-dict into TenantConfig, preserving unknown top-level
    keys in `.extra`. Pydantic doesn't preserve extra keys by default;
    we capture them manually so additions to the YAML schema don't get
    silently dropped."""
    if not isinstance(raw, dict):
        raise ValueError(f"tenant config root must be a dict, got {type(raw).__name__}")

    known = {
        "client", "brand", "audience", "agents_enabled", "approval_rules",
        "team_access", "integrations", "review_response_config", "intake_config",
    }
    extra = {k: v for k, v in raw.items() if k not in known}

    # Pydantic validates everything else
    payload = {k: v for k, v in raw.items() if k in known}
    if "extra" not in payload:
        payload["extra"] = extra

    return TenantConfig.model_validate(payload)


def loader_from_env() -> TenantConfigLoader:
    """Pick a loader implementation based on env vars. Used by the
    sidecar at startup so deploys don't have to swap code.

    Env vars:
      TENANT_CONFIG_BACKEND = file (default) | supabase | memory
      TENANT_CONFIG_DIR     = directory for FileTenantConfigLoader
                              (default ./clients)

    Supabase backend is reserved for a follow-up — for now an empty
    InMemoryTenantConfigLoader is returned (so the sidecar still boots
    and operators see 'tenant not configured' rather than a crash).
    """
    backend = (os.environ.get("TENANT_CONFIG_BACKEND") or "file").lower()
    if backend == "file":
        base = Path(os.environ.get("TENANT_CONFIG_DIR") or "clients")
        return FileTenantConfigLoader(base)
    if backend == "memory":
        return InMemoryTenantConfigLoader()
    if backend == "supabase":
        # Reserved. Returning empty in-memory loader so boot doesn't fail;
        # operator will see TenantNotFound on first request and know to
        # finish the Supabase backend wiring.
        print("[tenant_config] TENANT_CONFIG_BACKEND=supabase not yet implemented; "
              "using empty in-memory loader")
        return InMemoryTenantConfigLoader()
    raise ValueError(f"unknown TENANT_CONFIG_BACKEND={backend!r}")
