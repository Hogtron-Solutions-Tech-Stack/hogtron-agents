"""Sentinel HTTP sidecar.

A thin Flask service that exposes Sentinel's Layer 1 kinds to the
Concierge Node backend over JSON. One process holds a singleton
CalendarProvider (mock or Google) and a Sentinel instance bound to it.

Request shape:
    POST /sentinel/<kind>
    Headers: X-Sentinel-Key: <shared secret>
    Body: {"payload": {...}, "requester": "concierge.backend"}

Response: SentinelFinding as JSON. HTTP 200 even for handler-level
errors (status="error") — caller inspects the body. HTTP non-2xx is
reserved for auth, routing, and infrastructure failures.

Run locally:
    cd hogtron-agents
    pip install -e .
    pip install -r services/sentinel/requirements.txt
    python -m services.sentinel.app

Deploy: railway.toml in services/sentinel/.
"""
from __future__ import annotations

import logging
import sys
from typing import Optional

from flask import Flask, jsonify, request

from hogtron_agents.sentinel import (
    Sentinel, SentinelBrief, MockCalendarProvider, CalendarProvider,
)

from . import config


# Surface — append new kinds here as each phase comes online.
_KINDS = {
    # Phase 1 — scheduling (require calendar_provider)
    "find_slot",
    "book_appointment",
    "reschedule",
    "cancel",
    "check_conflicts",
    # Phase 2A — intake / leads (no calendar dependency)
    "ingest_intake_form",
    "score_lead",
}

# Kinds that don't need a CalendarProvider — used to gate the "google
# mode requires real creds" startup check.
_NON_CALENDAR_KINDS = {"ingest_intake_form", "score_lead"}


def _build_provider(cfg: config.Config) -> CalendarProvider:
    """Build the singleton CalendarProvider based on env."""
    if cfg.calendar_provider == "mock":
        return MockCalendarProvider()
    if cfg.calendar_provider == "google":
        # Lazy import — Google SDK isn't a core dep, only pulled when used.
        from .providers.google_calendar import GoogleCalendarProvider  # noqa
        return GoogleCalendarProvider.from_env()
    raise ValueError(
        f"unknown SENTINEL_CALENDAR_PROVIDER={cfg.calendar_provider!r}; "
        "must be 'mock' or 'google'"
    )


def create_app(cfg: Optional[config.Config] = None) -> Flask:
    cfg = cfg or config.load()

    logging.basicConfig(
        level=getattr(logging, cfg.log_level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )
    log = logging.getLogger("sentinel.sidecar")

    provider = _build_provider(cfg)
    sentinel = Sentinel(calendar_provider=provider)

    app = Flask(__name__)
    app.config["SENTINEL_CFG"] = cfg
    app.config["SENTINEL"] = sentinel
    app.config["CALENDAR_PROVIDER"] = provider

    log.info(
        "sentinel sidecar up: provider=%s auth=%s",
        cfg.calendar_provider,
        "on" if cfg.sentinel_api_key else "OFF (dev only!)",
    )

    # --- routes ---------------------------------------------------------

    @app.get("/healthz")
    def healthz():
        return jsonify({
            "ok": True,
            "provider": cfg.calendar_provider,
            "kinds": sorted(_KINDS),
        })

    @app.get("/")
    def index():
        return jsonify({
            "service": "sentinel",
            "version": "0.1.0",
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

        # Mock-only: allow seed fixtures in the request for dev convenience.
        # Quietly ignored in google mode (where you seed via the real calendar).
        if cfg.calendar_provider == "mock" and isinstance(body.get("_seed"), list):
            from hogtron_agents.sentinel import CalendarEvent
            from hogtron_agents.sentinel._calendar import parse_iso
            for s in body["_seed"]:
                provider.create_event(CalendarEvent(
                    event_id=s.get("event_id", ""),
                    business_id=s["business_id"],
                    start=parse_iso(s["start"]),
                    end=parse_iso(s["end"]),
                    title=s.get("title", "seed"),
                    staff_member=s.get("staff_member"),
                ))

        try:
            brief = SentinelBrief(
                kind=kind, payload=payload,
                context=body.get("context") or {},
                requester=body.get("requester"),
            )
        except Exception as e:
            return jsonify({"error": f"bad brief: {e}"}), 400

        finding = sentinel.do(brief)
        return jsonify(finding.model_dump(mode="json"))

    return app


if __name__ == "__main__":
    cfg = config.load()
    app = create_app(cfg)
    # Dev server only — production uses gunicorn (see railway.toml).
    app.run(host="0.0.0.0", port=cfg.port, debug=False)
