"""capacity_audit handler — receives the /free-audit form from
hogtron-solutions.com.

The WP form (page-free-audit.php) AJAX POSTs to wp-admin's
hogtron_handle_free_audit action which saves a ht_lead custom post +
emails inquiries@. This handler is an ADDITIONAL pipe: it gives
Sentinel visibility, scores the lead, fires a Slack notification, and
puts the lead on the Bridge HUD. WordPress stays as primary storage.

brief.payload (required):
  tenant_id        — slug to load TenantConfig
  name             — visitor's name
  email            — visitor's email
  business         — business name
  url              — their website URL
brief.payload (optional):
  phone            — phone number
  seo_score        — int 0-100 (audit may have already run on the WP side)
  geo_score        — int 0-100
  audit_data       — full audit dict (passed through to Slack)
  wp_post_id       — id of the ht_lead WP post (for back-reference)
  source_detail    — UTM params, referrer, etc

brief.context:
  tenant_config_loader — TenantConfigLoader (required for tenant lookup)
  notify_owner_fn      — optional callable(NewLeadNotification) for Slack
  scorer_fn            — optional callable for score_lead
"""
from __future__ import annotations

import re
from typing import Any

from .briefs import SentinelBrief, SentinelFinding
from ._tenant_config import TenantConfigLoader, TenantNotFound


_REQUIRED = ("tenant_id", "name", "email", "business", "url")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def capacity_audit(brief: SentinelBrief) -> SentinelFinding:
    p = brief.payload or {}
    ctx = brief.context or {}

    missing = [k for k in _REQUIRED if not p.get(k)]
    if missing:
        return SentinelFinding(
            kind="ingest_capacity_audit", status="validation_failed",
            payload={"errors": {k: "required" for k in missing}},
            reason=f"missing fields: {', '.join(missing)}",
        )

    email = str(p["email"]).strip().lower()
    if not _EMAIL_RE.match(email):
        return SentinelFinding(
            kind="ingest_capacity_audit", status="validation_failed",
            payload={"errors": {"email": "invalid format"}},
            reason="email not parseable",
        )

    tenant_id = str(p["tenant_id"])
    loader: TenantConfigLoader = ctx.get("tenant_config_loader")
    if loader is None:
        return SentinelFinding(
            kind="ingest_capacity_audit", status="error",
            reason="brief.context.tenant_config_loader is required",
        )
    try:
        tenant = loader.load(tenant_id)
    except TenantNotFound:
        return SentinelFinding(
            kind="ingest_capacity_audit", status="error",
            reason=f"tenant {tenant_id!r} not configured",
        )

    # Honor per-tenant on/off toggle
    behaviour = tenant.intake_config.capacity_audit
    if not behaviour.enabled:
        return SentinelFinding(
            kind="ingest_capacity_audit", status="error",
            reason=f"capacity_audit intake disabled for tenant {tenant_id!r}",
        )

    lead = {
        "name": str(p["name"]).strip(),
        "email": email,
        "phone": str(p.get("phone") or "").strip(),
        "business": str(p["business"]).strip(),
        "url": str(p["url"]).strip(),
        "seo_score": p.get("seo_score"),
        "geo_score": p.get("geo_score"),
        "wp_post_id": p.get("wp_post_id"),
        "source": "capacity_audit",
        "source_detail": {
            "form_id": "free-audit",
            "wp_post_id": p.get("wp_post_id"),
            **(p.get("source_detail") or {}),
        },
    }

    # Score (rule-based, low cost). Optional — won't fail the intake if
    # scorer isn't wired. The dashboard's UI can show "needs scoring"
    # for untriaged leads.
    score_payload = {}
    scorer_fn = ctx.get("scorer_fn")
    if scorer_fn:
        try:
            score_payload = scorer_fn({
                "lead_data": {"phone": lead["phone"], "email": lead["email"]},
                "submission_data": {"service": "audit", "url": lead["url"]},
                "paid_services": ["audit"],  # an audit is the entry into paid work
                "booked": False,
            }) or {}
        except Exception as e:  # noqa: BLE001
            print(f"[capacity_audit] scorer_fn errored (non-fatal): {e}")

    # Fire Slack / email notification — best effort
    notify_fn = ctx.get("notify_owner_fn")
    if notify_fn:
        try:
            notify_fn({
                "kind": "capacity_audit",
                "tenant": tenant.client.name,
                "lead": lead,
                "score": score_payload,
                "voice_audit_seo": p.get("seo_score"),
                "voice_audit_geo": p.get("geo_score"),
            })
        except Exception as e:  # noqa: BLE001
            print(f"[capacity_audit] notify_owner_fn errored (non-fatal): {e}")

    return SentinelFinding(
        kind="ingest_capacity_audit", status="ok",
        payload={"lead": lead, "score": score_payload},
        metadata={
            "tenant_id": tenant_id,
            "tenant_name": tenant.client.name,
            "has_score": bool(score_payload),
            "notified": bool(notify_fn),
        },
        reason=f"accepted capacity audit from {lead['business']!r} ({email})",
    )
