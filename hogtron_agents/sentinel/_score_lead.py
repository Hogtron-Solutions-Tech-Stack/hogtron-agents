"""score_lead handler — rule-based lead triage.

Stateless. Takes the lead data + submission context, returns
hot/warm/cold + a short reason trace. Phase 2 v1 ships with rules baked
in (see design doc §8); per-business overrides are Phase 4.

Logic:
  HOT  — has phone AND service in business 'paid_services' AND booked
  WARM — has phone AND any service selected
  COLD — missing phone OR no clear service intent

Why a Sentinel kind (vs. inline in the Node backend): future swap-in
for AI-enhanced scoring is a single-file change, no caller migration.

brief.payload:
  lead_data (dict, required)     — {name, email, phone, ...}
  submission_data (dict, optional) — the normalized form answers
  booked (bool, optional)         — whether a booking was created in same flow
  paid_services (list[str], optional)
                                  — values from businesses.config.paid_services;
                                    used to detect the HOT tier
"""
from __future__ import annotations

from .briefs import SentinelBrief, SentinelFinding


def score_lead(brief: SentinelBrief) -> SentinelFinding:
    p = brief.payload or {}
    lead = p.get("lead_data") or {}
    submission = p.get("submission_data") or {}
    booked = bool(p.get("booked"))
    paid_services = set(p.get("paid_services") or [])

    if not isinstance(lead, dict):
        return SentinelFinding(
            kind="score_lead", status="error",
            reason="payload.lead_data must be a dict",
        )

    has_phone = bool(lead.get("phone"))
    service = submission.get("service")

    if has_phone and service and service in paid_services and booked:
        return SentinelFinding(
            kind="score_lead", status="ok",
            payload={"score": "hot",
                     "reason": "phone + paid-tier service + booked discovery"},
            reason="hot",
        )

    if has_phone and service:
        return SentinelFinding(
            kind="score_lead", status="ok",
            payload={"score": "warm", "reason": "phone + clear service intent"},
            reason="warm",
        )

    if has_phone:
        return SentinelFinding(
            kind="score_lead", status="ok",
            payload={"score": "warm", "reason": "phone but vague service"},
            reason="warm",
        )

    return SentinelFinding(
        kind="score_lead", status="ok",
        payload={"score": "cold",
                 "reason": "no phone — harder to reach, lower intent signal"},
        reason="cold",
    )
