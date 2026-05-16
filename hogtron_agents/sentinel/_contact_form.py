"""contact_form handler — receives the /contact form from
hogtron-solutions.com.

WP's page-contact.php does a traditional POST submit, validates the
nonce, and sends an email to inquiries@. No WP database storage.
Sentinel pipes alongside that: visibility, optional scoring, Slack
ping, Bridge HUD entry.

brief.payload (required):
  tenant_id
  name
  email
  message
brief.payload (optional):
  service          — dropdown selection (web design, hosting, SEO, etc)
  source_detail    — UTM params, referrer, etc

brief.context:
  tenant_config_loader — TenantConfigLoader (required)
  notify_owner_fn      — optional callable for Slack
"""
from __future__ import annotations

import re

from .briefs import SentinelBrief, SentinelFinding
from ._tenant_config import TenantConfigLoader, TenantNotFound


_REQUIRED = ("tenant_id", "name", "email", "message")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def contact_form(brief: SentinelBrief) -> SentinelFinding:
    p = brief.payload or {}
    ctx = brief.context or {}

    missing = [k for k in _REQUIRED if not p.get(k)]
    if missing:
        return SentinelFinding(
            kind="ingest_contact_form", status="validation_failed",
            payload={"errors": {k: "required" for k in missing}},
            reason=f"missing fields: {', '.join(missing)}",
        )

    email = str(p["email"]).strip().lower()
    if not _EMAIL_RE.match(email):
        return SentinelFinding(
            kind="ingest_contact_form", status="validation_failed",
            payload={"errors": {"email": "invalid format"}},
            reason="email not parseable",
        )

    tenant_id = str(p["tenant_id"])
    loader: TenantConfigLoader = ctx.get("tenant_config_loader")
    if loader is None:
        return SentinelFinding(
            kind="ingest_contact_form", status="error",
            reason="brief.context.tenant_config_loader is required",
        )
    try:
        tenant = loader.load(tenant_id)
    except TenantNotFound:
        return SentinelFinding(
            kind="ingest_contact_form", status="error",
            reason=f"tenant {tenant_id!r} not configured",
        )

    behaviour = tenant.intake_config.contact_form
    if not behaviour.enabled:
        return SentinelFinding(
            kind="ingest_contact_form", status="error",
            reason=f"contact_form intake disabled for tenant {tenant_id!r}",
        )

    lead = {
        "name": str(p["name"]).strip(),
        "email": email,
        "message": str(p["message"]).strip(),
        "service": str(p.get("service") or "").strip(),
        "source": "contact_form",
        "source_detail": {
            "form_id": "contact",
            "service": str(p.get("service") or ""),
            **(p.get("source_detail") or {}),
        },
    }

    notify_fn = ctx.get("notify_owner_fn")
    if notify_fn:
        try:
            notify_fn({
                "kind": "contact_form",
                "tenant": tenant.client.name,
                "lead": lead,
            })
        except Exception as e:  # noqa: BLE001
            print(f"[contact_form] notify_owner_fn errored (non-fatal): {e}")

    return SentinelFinding(
        kind="ingest_contact_form", status="ok",
        payload={"lead": lead},
        metadata={
            "tenant_id": tenant_id,
            "tenant_name": tenant.client.name,
            "service": lead["service"],
            "notified": bool(notify_fn),
        },
        reason=f"accepted contact from {lead['name']!r} ({email})",
    )
