"""check_conflicts handler — does a proposed window overlap any event?

Cheaper than find_slot — single-window query. Use before book_appointment
when the caller has proposed a specific time.

brief.payload:
  business_id, start, end (required)
  staff_member (optional)
brief.context:
  calendar_provider (required)

Status semantics:
  "clear"    — window is free
  "conflict" — payload.conflicts has overlapping events
  "error"    — bad input or provider raised
"""
from __future__ import annotations

from .briefs import SentinelBrief, SentinelFinding
from ._calendar import CalendarProvider, parse_iso


def check_conflicts(brief: SentinelBrief) -> SentinelFinding:
    p = brief.payload or {}
    provider: CalendarProvider = brief.context.get("calendar_provider")
    if provider is None:
        return SentinelFinding(
            kind="check_conflicts", status="error",
            reason="brief.context.calendar_provider is required",
        )

    required = ["business_id", "start", "end"]
    missing = [k for k in required if not p.get(k)]
    if missing:
        return SentinelFinding(
            kind="check_conflicts", status="error",
            reason=f"payload missing required field(s): {', '.join(missing)}",
        )

    try:
        start = parse_iso(p["start"])
        end = parse_iso(p["end"])
    except ValueError as e:
        return SentinelFinding(
            kind="check_conflicts", status="error",
            reason=f"bad start/end: {e}",
        )
    if end <= start:
        return SentinelFinding(
            kind="check_conflicts", status="error",
            reason="end must be after start",
        )

    staff = p.get("staff_member")

    try:
        busy = provider.list_events(p["business_id"], start, end, staff_member=staff)
    except Exception as e:
        return SentinelFinding(
            kind="check_conflicts", status="error",
            reason=f"provider.list_events failed: {e}",
        )

    return SentinelFinding(
        kind="check_conflicts",
        status="clear" if not busy else "conflict",
        payload={"conflicts": [
            {"event_id": ev.event_id, "start": ev.start.isoformat(),
             "end": ev.end.isoformat(), "title": ev.title,
             "staff_member": ev.staff_member}
            for ev in busy
        ]},
        reason=f"{len(busy)} overlap(s)" if busy else "no overlap",
    )
