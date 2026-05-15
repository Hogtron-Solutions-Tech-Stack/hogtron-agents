"""reschedule handler — move an existing event to a new window.

Checks for conflicts at the new window before moving (excluding the
event being moved — moving it onto itself is not a conflict).

brief.payload:
  business_id, calendar_event_id, new_start, new_end (required)
brief.context:
  calendar_provider (required)

Status semantics:
  "rescheduled" — moved; payload has updated event
  "conflict"    — new window overlaps another event
  "not_found"   — calendar_event_id doesn't exist
  "error"       — bad input or provider raised
"""
from __future__ import annotations

from .briefs import SentinelBrief, SentinelFinding
from ._calendar import CalendarProvider, parse_iso


def reschedule(brief: SentinelBrief) -> SentinelFinding:
    p = brief.payload or {}
    provider: CalendarProvider = brief.context.get("calendar_provider")
    if provider is None:
        return SentinelFinding(
            kind="reschedule", status="error",
            reason="brief.context.calendar_provider is required",
        )

    required = ["business_id", "calendar_event_id", "new_start", "new_end"]
    missing = [k for k in required if not p.get(k)]
    if missing:
        return SentinelFinding(
            kind="reschedule", status="error",
            reason=f"payload missing required field(s): {', '.join(missing)}",
        )

    try:
        new_start = parse_iso(p["new_start"])
        new_end = parse_iso(p["new_end"])
    except ValueError as e:
        return SentinelFinding(
            kind="reschedule", status="error",
            reason=f"bad new_start/new_end: {e}",
        )
    if new_end <= new_start:
        return SentinelFinding(
            kind="reschedule", status="error",
            reason="new_end must be after new_start",
        )

    business_id = p["business_id"]
    event_id = p["calendar_event_id"]

    try:
        busy = provider.list_events(business_id, new_start, new_end)
    except Exception as e:
        return SentinelFinding(
            kind="reschedule", status="error",
            reason=f"provider.list_events failed: {e}",
        )

    # Exclude the event being moved (moving onto itself isn't a conflict).
    conflicts = [ev for ev in busy if ev.event_id != event_id]
    if conflicts:
        return SentinelFinding(
            kind="reschedule", status="conflict",
            payload={"conflicts": [
                {"event_id": ev.event_id, "start": ev.start.isoformat(),
                 "end": ev.end.isoformat(), "title": ev.title}
                for ev in conflicts
            ]},
            reason=f"{len(conflicts)} other event(s) overlap the new window",
        )

    try:
        updated = provider.update_event(business_id, event_id, new_start, new_end)
    except KeyError:
        return SentinelFinding(
            kind="reschedule", status="not_found",
            reason=f"event {event_id!r} not found for business {business_id!r}",
        )
    except Exception as e:
        return SentinelFinding(
            kind="reschedule", status="error",
            reason=f"provider.update_event failed: {e}",
        )

    return SentinelFinding(
        kind="reschedule", status="rescheduled",
        payload={
            "calendar_event_id": updated.event_id,
            "event": {
                "event_id": updated.event_id,
                "start": updated.start.isoformat(),
                "end": updated.end.isoformat(),
                "title": updated.title,
                "staff_member": updated.staff_member,
                "status": updated.status,
            },
        },
        reason=f"moved {event_id} to {new_start.isoformat()}",
    )
