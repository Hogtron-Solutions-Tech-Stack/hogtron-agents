"""Sentinel sidecar configuration.

Env-driven. The Concierge Node backend reaches this service over HTTP;
the service holds a singleton CalendarProvider (mock or Google) and
runs Sentinel against it per request.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: Path = None) -> None:
    """Tiny .env loader — no python-dotenv dep. Pre-existing env vars win
    (so prod / Railway settings always override the file).

    Walks up from this file looking for .env, so it works whether you run
    the sidecar from hogtron-agents/ or from services/sentinel/.
    """
    if path is None:
        for parent in Path(__file__).resolve().parents:
            cand = parent / ".env"
            if cand.is_file():
                path = cand
                break
    if path is None or not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


@dataclass(frozen=True)
class Config:
    # Provider selection ----------------------------------------------------
    # "mock"   — in-memory, fixtures via seed payloads. Default for dev.
    # "google" — GoogleCalendarProvider (Phase 1B; needs OAuth creds).
    calendar_provider: str

    # GBP reviews provider for the review-responder pipeline.
    # "mock"   — MockGBPReviewsClient (in-memory).
    # "google" — GoogleGBPReviewsClient (per-tenant OAuth refresh tokens).
    gbp_provider: str

    # Tenant config backend.
    # "file"     — FileTenantConfigLoader, dir from TENANT_CONFIG_DIR
    # "memory"   — InMemoryTenantConfigLoader (empty; for tests)
    # "supabase" — reserved (falls back to memory currently)
    tenant_config_backend: str

    # Auth ------------------------------------------------------------------
    # Shared secret in X-Sentinel-Key header. If empty, auth is OFF — only
    # acceptable for local development. Set in Railway prod.
    sentinel_api_key: str

    # Service ---------------------------------------------------------------
    port: int
    log_level: str

    # Anthropic (for Marketing.review_response drafts) ---------------------
    anthropic_api_key: str

    # Slack (best-effort notifications) ------------------------------------
    slack_bot_token: str
    slack_leads_inbound_channel: str
    slack_review_approval_channel: str


def load() -> Config:
    load_dotenv()
    return Config(
        calendar_provider=os.environ.get("SENTINEL_CALENDAR_PROVIDER", "mock").lower(),
        gbp_provider=os.environ.get("SENTINEL_GBP_PROVIDER", "mock").lower(),
        tenant_config_backend=os.environ.get("TENANT_CONFIG_BACKEND", "file").lower(),
        sentinel_api_key=os.environ.get("SENTINEL_API_KEY", ""),
        port=int(os.environ.get("PORT", "5055")),
        log_level=os.environ.get("LOG_LEVEL", "info").upper(),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        slack_bot_token=os.environ.get("SLACK_BOT_TOKEN", ""),
        slack_leads_inbound_channel=os.environ.get(
            "SLACK_LEADS_INBOUND_CHANNEL", "leads-inbound"),
        slack_review_approval_channel=os.environ.get(
            "SLACK_REVIEW_APPROVAL_CHANNEL", "review-approvals"),
    )
