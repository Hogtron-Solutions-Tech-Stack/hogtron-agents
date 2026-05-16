"""Sentinel HTTP sidecar.

A thin Flask service that exposes Sentinel's Layer 1 kinds over JSON
to anyone that can reach it: WordPress sites (capacity audit + contact
form), the Concierge Node backend (booking), the dashboard (review
responder runs), the cron scheduler (hourly review polling).

Request shape:
    POST /sentinel/<kind>
    Headers: X-Sentinel-Key: <shared secret>
    Body: {"payload": {...}, "context": {...}, "requester": "..."}

Response: SentinelFinding as JSON. HTTP 200 even for handler-level
errors (status="error") — caller inspects the body. HTTP non-2xx is
reserved for auth, routing, and infrastructure failures.

At startup the sidecar constructs and holds:
  - one CalendarProvider singleton (mock or Google)
  - one TenantConfigLoader (file/memory/supabase)
  - one Marketing instance (for review_response drafts)
  - one Slack notifier (for inbound leads + review-approval queue)
  - one GBP-reviews-client factory (per-tenant clients on demand)

These are injected into brief.context automatically per request so
callers don't need to know about them.

Run locally:
    cd hogtron-agents
    pip install -e .
    pip install -r services/sentinel/requirements.txt
    python -m services.sentinel.app

Deploy: railway.toml in services/sentinel/.
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Any, Optional

from flask import Flask, jsonify, request

from hogtron_agents.sentinel import (
    Sentinel, SentinelBrief, MockCalendarProvider, CalendarProvider,
    FileTenantConfigLoader, InMemoryTenantConfigLoader, TenantConfigLoader,
)

from . import config
from . import notifier as notif_mod


# Full surface — append new kinds here as each handler comes online.
_KINDS = {
    # Phase 1 — scheduling
    "find_slot",
    "book_appointment",
    "reschedule",
    "cancel",
    "check_conflicts",
    # Phase 2A — generic intake / leads
    "ingest_intake_form",
    "score_lead",
    # Phase 2B — hogtron-website inbound forms
    "ingest_capacity_audit",
    "ingest_contact_form",
    # Phase 3 — review response orchestration
    "respond_to_reviews",
}

# Kinds that need the calendar provider injected
_CALENDAR_KINDS = {
    "find_slot", "book_appointment", "reschedule", "cancel", "check_conflicts",
}

# Kinds that need the tenant config loader + notifier injected
_INTAKE_KINDS = {"ingest_capacity_audit", "ingest_contact_form"}

# Kinds that need the FULL review orchestration set (tenant loader +
# marketing instance + gbp client factory + notifier)
_REVIEW_KINDS = {"respond_to_reviews"}


# --- Provider builders --------------------------------------------------

def _build_calendar_provider(cfg: config.Config) -> CalendarProvider:
    if cfg.calendar_provider == "mock":
        return MockCalendarProvider()
    if cfg.calendar_provider == "google":
        from .providers.google_calendar import GoogleCalendarProvider  # noqa
        return GoogleCalendarProvider.from_env()
    raise ValueError(
        f"unknown SENTINEL_CALENDAR_PROVIDER={cfg.calendar_provider!r}; "
        "must be 'mock' or 'google'"
    )


def _build_tenant_loader(cfg: config.Config) -> TenantConfigLoader:
    backend = cfg.tenant_config_backend
    if backend == "file":
        base = os.environ.get("TENANT_CONFIG_DIR", "clients")
        return FileTenantConfigLoader(base)
    if backend == "memory":
        return InMemoryTenantConfigLoader()
    if backend == "supabase":
        # Reserved. Empty in-memory loader so boot succeeds; first request
        # will return TenantNotFound (clear signal to finish wiring).
        logging.warning("[sentinel] TENANT_CONFIG_BACKEND=supabase not implemented yet; "
                        "using empty in-memory loader")
        return InMemoryTenantConfigLoader()
    raise ValueError(f"unknown TENANT_CONFIG_BACKEND={backend!r}")


def _build_gbp_client_factory(cfg: config.Config):
    """Returns a callable: tenant_id → GBPReviewsClient.

    Mock mode returns a shared MockGBPReviewsClient; google mode builds
    a per-tenant GoogleGBPReviewsClient from env-stored tokens.
    """
    if cfg.gbp_provider == "mock":
        from .providers.gbp_reviews import MockGBPReviewsClient
        shared = MockGBPReviewsClient()

        def factory(tenant_id: str):
            return shared
        return factory

    if cfg.gbp_provider == "google":
        from .providers.gbp_reviews import GoogleGBPReviewsClient

        def factory(tenant_id: str):
            return GoogleGBPReviewsClient.from_tenant_id(tenant_id)
        return factory

    raise ValueError(f"unknown SENTINEL_GBP_PROVIDER={cfg.gbp_provider!r}")


def _build_marketing():
    """Lazy-load the Marketing class. It pulls in anthropic + other deps
    only on first import — speeds up boot when only intake routes are
    used."""
    from hogtron_agents.marketing import Marketing
    return Marketing()


# --- App factory --------------------------------------------------------

def create_app(cfg: Optional[config.Config] = None) -> Flask:
    cfg = cfg or config.load()

    logging.basicConfig(
        level=getattr(logging, cfg.log_level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )
    log = logging.getLogger("sentinel.sidecar")

    # Build singletons
    calendar_provider = _build_calendar_provider(cfg)
    tenant_loader = _build_tenant_loader(cfg)
    gbp_factory = _build_gbp_client_factory(cfg)
    # Marketing is heavyweight (pulls anthropic SDK) — defer to first
    # request that needs it. Holding the reference here so the closure
    # in dispatch() captures the lazy slot.
    marketing_ref: dict = {"instance": None}

    def _ensure_marketing():
        if marketing_ref["instance"] is None:
            marketing_ref["instance"] = _build_marketing()
        return marketing_ref["instance"]

    if cfg.slack_bot_token:
        notify_fn = notif_mod.make_notifier(
            bot_token=cfg.slack_bot_token,
            leads_channel=cfg.slack_leads_inbound_channel,
            review_channel=cfg.slack_review_approval_channel,
        )
    else:
        notify_fn = notif_mod.null_notifier

    sentinel = Sentinel(calendar_provider=calendar_provider)

    app = Flask(__name__)
    app.config["SENTINEL_CFG"] = cfg
    app.config["SENTINEL"] = sentinel
    app.config["CALENDAR_PROVIDER"] = calendar_provider
    app.config["TENANT_LOADER"] = tenant_loader
    app.config["GBP_FACTORY"] = gbp_factory
    app.config["NOTIFY_FN"] = notify_fn

    log.info(
        "sentinel sidecar up: calendar=%s gbp=%s tenant=%s auth=%s slack=%s",
        cfg.calendar_provider, cfg.gbp_provider, cfg.tenant_config_backend,
        "on" if cfg.sentinel_api_key else "OFF (dev only!)",
        "on" if cfg.slack_bot_token else "OFF",
    )

    # --- routes ---------------------------------------------------------

    @app.get("/healthz")
    def healthz():
        return jsonify({
            "ok": True,
            "calendar_provider": cfg.calendar_provider,
            "gbp_provider": cfg.gbp_provider,
            "tenant_backend": cfg.tenant_config_backend,
            "kinds": sorted(_KINDS),
        })

    @app.get("/")
    def index():
        return jsonify({
            "service": "sentinel",
            "version": "0.2.0",
            "endpoints": [
                "GET  /healthz",
                "POST /sentinel/<kind>  (kinds: " + ", ".join(sorted(_KINDS)) + ")",
            ],
        })

    @app.post("/sentinel/<kind>")
    def dispatch(kind: str):
        if cfg.sentinel_api_key:
            provided = request.headers.get("X-Sentinel-Key", "")
            if provided != cfg.sentinel_api_key:
                return jsonify({"error": "unauthorized"}), 401

        if kind not in _KINDS:
            return jsonify({
                "error": f"unknown kind {kind!r}",
                "known": sorted(_KINDS),
            }), 404

        body = request.get_json(silent=True) or {}
        payload = body.get("payload")
        if not isinstance(payload, dict):
            return jsonify({"error": "body.payload must be an object"}), 400

        # Mock-only: allow seed fixtures for calendar dev convenience.
        if cfg.calendar_provider == "mock" and isinstance(body.get("_seed"), list):
            from hogtron_agents.sentinel import CalendarEvent
            from hogtron_agents.sentinel._calendar import parse_iso
            for s in body["_seed"]:
                calendar_provider.create_event(CalendarEvent(
                    event_id=s.get("event_id", ""),
                    business_id=s["business_id"],
                    start=parse_iso(s["start"]),
                    end=parse_iso(s["end"]),
                    title=s.get("title", "seed"),
                    staff_member=s.get("staff_member"),
                ))

        # Build the brief context, layering in sidecar singletons per kind.
        # Caller's body.context wins on conflict so tests can override.
        ctx: dict = {}
        if kind in _INTAKE_KINDS:
            ctx["tenant_config_loader"] = tenant_loader
            ctx["notify_owner_fn"] = notify_fn
            # Pull score_lead in as a callable for capacity_audit scoring.
            # Closure over sentinel so the handler can call back in.
            def _scorer(scorer_payload: dict) -> dict:
                from hogtron_agents.sentinel import SentinelBrief as _SB
                f = sentinel.do(_SB(
                    kind="score_lead", payload=scorer_payload,
                    requester=f"sidecar.scorer:{kind}",
                ))
                return f.payload if f.status == "ok" else {}
            ctx["scorer_fn"] = _scorer
        if kind in _REVIEW_KINDS:
            ctx["tenant_config_loader"] = tenant_loader
            ctx["gbp_client_fn"] = gbp_factory
            ctx["marketing_instance"] = _ensure_marketing()
            ctx["notify_owner_fn"] = notify_fn
            if cfg.anthropic_api_key:
                ctx["anthropic_api_key"] = cfg.anthropic_api_key
        # Caller-provided context overrides our auto-injection
        caller_ctx = body.get("context") or {}
        ctx.update(caller_ctx)

        try:
            brief = SentinelBrief(
                kind=kind, payload=payload,
                context=ctx,
                requester=body.get("requester"),
            )
        except Exception as e:
            return jsonify({"error": f"bad brief: {e}"}), 400

        finding = sentinel.do(brief)
        # Don't echo the (potentially huge) context back to the caller.
        # Pydantic excludes context from model_dump by default? Actually
        # no — SentinelBrief is separate from SentinelFinding. Finding
        # is fine to dump as-is.
        return jsonify(finding.model_dump(mode="json"))

    return app


if __name__ == "__main__":
    cfg = config.load()
    app = create_app(cfg)
    # Dev server only — production uses gunicorn (see railway.toml).
    app.run(host="0.0.0.0", port=cfg.port, debug=False)
