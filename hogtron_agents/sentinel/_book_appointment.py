"""book_appointment handler — write a confirmed event to a business's calendar.

Stateless. Always checks for conflicts in [start, end) first; refuses to
overwrite a busy window. Caller persists calendar_event_id back onto the
bookings row (Hogtron-Concierge already has the column).

brief.payload:
  business_id, start, end, title, attendee_email (required)
  attendee_name, staff_member, notes (optional)
brief.context:
  calendar_provider (required)

Status semantics:
  "booked"   — event written; payload has calendar_event_id
  "conflict" — window overlaps an existing event; payload has conflicts[]
  "error"    — bad input or provider raised
"""
from __future__ import annotations

from .briefs import SentinelBrief, SentinelFinding
from ._calendar import CalendarProvider, CalendarEvent, parse_iso


def book_appointment(brief: SentinelBrief) -> SentinelFinding:
    p = brief.payload or {}
    provider: CalendarProvider = brief.context.get("calendar_provider")
    if provider is None:
        return SentinelFinding(
            kind="book_appointment", status="error",
            reason="brief.context.calendar_provider is required",
        )

    required = ["business_id", "start", "end", "title", "attendee_email"]
    missing = [k for k in required if not p.get(k)]
    if missing:
        return SentinelFinding(
            kind="book_appointment", status="error",
            reason=f"payload missing required field(s): {', '.join(missing)}",
        )

    try:
        start = parse_iso(p["start"])
        end = parse_iso(p["end"])
    except ValueError as e:
        return SentinelFinding(
            kind="book_appointment", status="error",
            reason=f"bad start/end: {e}",
        )
    if end <= start:
        return SentinelFinding(
            kind="book_appointment", status="error",
            reason="end must be after start",
        )

    staff = p.get("staff_member")

    try:
        busy = provider.list_events(p["business_id"], start, end, staff_member=staff)
    except Exception as e:
        return SentinelFinding(
            kind="book_appointment", status="error",
            reason=f"provider.list_events failed: {e}",
        )

    if busy:
        return SentinelFinding(
            kind="book_appointment", status="conflict",
            payload={"conflicts": [_event_brief(ev) for ev in busy]},
            reason=f"{len(busy)} existing event(s) overlap [{start.isoformat()}, {end.isoformat()})",
        )

    event = CalendarEvent(
        event_id="",
        business_id=p["business_id"],
        start=start, end=end,
        title=p["title"],
        attendee_email=p["attendee_email"],
        attendee_name=p.get("attendee_name") or "",
        staff_member=staff,
        notes=p.get("notes") or "",
    )

    try:
        created = provider.create_event(event)
    except Exception as e:
        return SentinelFinding(
            kind="book_appointment", status="error",
            reason=f"provider.create_event failed: {e}",
        )

    return SentinelFinding(
        kind="book_appointment", status="booked",
        payload={"calendar_event_id": created.event_id, "event": _event_brief(created)},
        reason=f"booked event {created.event_id}",
    )


def _event_brief(ev) -> dict:
    return {
        "event_id": ev.event_id,
        "start": ev.start.isoformat(),
        "end": ev.end.isoformat(),
        "title": ev.title,
        "staff_member": ev.staff_member,
        "status": ev.status,
    }
