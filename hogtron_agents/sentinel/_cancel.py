"""cancel handler — cancel an existing calendar event.

brief.payload:
  business_id, calendar_event_id (required)
  reason (optional)              — recorded in finding.metadata
brief.context:
  calendar_provider (required)

Status semantics:
  "cancelled" — event marked cancelled
  "not_found" — calendar_event_id doesn't exist
  "error"     — bad input or provider raised
"""
from __future__ import annotations

from .briefs import SentinelBrief, SentinelFinding
from ._calendar import CalendarProvider


def cancel(brief: SentinelBrief) -> SentinelFinding:
    p = brief.payload or {}
    provider: CalendarProvider = brief.context.get("calendar_provider")
    if provider is None:
        return SentinelFinding(
            kind="cancel", status="error",
            reason="brief.context.calendar_provider is required",
        )

    required = ["business_id", "calendar_event_id"]
    missing = [k for k in required if not p.get(k)]
    if missing:
        return SentinelFinding(
            kind="cancel", status="error",
            reason=f"payload missing required field(s): {', '.join(missing)}",
        )

    business_id = p["business_id"]
    event_id = p["calendar_event_id"]
    cancel_reason = p.get("reason") or ""

    try:
        cancelled = provider.cancel_event(business_id, event_id)
    except KeyError:
        return SentinelFinding(
            kind="cancel", status="not_found",
            reason=f"event {event_id!r} not found for business {business_id!r}",
        )
    except Exception as e:
        return SentinelFinding(
            kind="cancel", status="error",
            reason=f"provider.cancel_event failed: {e}",
        )

    return SentinelFinding(
        kind="cancel", status="cancelled",
        payload={"calendar_event_id": cancelled.event_id},
        metadata={"cancel_reason": cancel_reason},
        reason=f"cancelled {event_id}",
    )
