"""find_slot handler — query a business's calendar for open windows.

Stateless. Reads from a CalendarProvider passed via brief.context.
Returns the first N open windows >= duration_min in [window_start, window_end).

brief.payload:
  business_id (str, required)
  window_start (ISO datetime, required)
  window_end   (ISO datetime, required)
  duration_min (int, required)
  buffer_min   (int, default 0)        — pad before/after busy events
  staff_member (str, optional)         — filter to one staffer's events
  max_slots    (int, default 10)       — cap returned slots
brief.context:
  calendar_provider (CalendarProvider, required)

Status semantics:
  "ok"               — slots found
  "no_availability"  — no slots fit
  "error"            — bad input or provider raised
"""
from __future__ import annotations

from datetime import timedelta

from .briefs import SentinelBrief, SentinelFinding
from ._calendar import CalendarProvider, parse_iso, find_open_windows


def find_slot(brief: SentinelBrief) -> SentinelFinding:
    p = brief.payload or {}
    provider: CalendarProvider = brief.context.get("calendar_provider")
    if provider is None:
        return SentinelFinding(
            kind="find_slot", status="error",
            reason="brief.context.calendar_provider is required",
        )

    business_id = p.get("business_id")
    if not business_id:
        return SentinelFinding(
            kind="find_slot", status="error",
            reason="payload.business_id is required",
        )

    try:
        window_start = parse_iso(p["window_start"])
        window_end = parse_iso(p["window_end"])
        duration = timedelta(minutes=int(p["duration_min"]))
    except (KeyError, ValueError) as e:
        return SentinelFinding(
            kind="find_slot", status="error",
            reason=f"bad window/duration input: {e}",
        )

    if window_end <= window_start:
        return SentinelFinding(
            kind="find_slot", status="error",
            reason="window_end must be after window_start",
        )

    buffer = timedelta(minutes=int(p.get("buffer_min") or 0))
    max_slots = int(p.get("max_slots") or 10)
    staff = p.get("staff_member")

    try:
        busy = provider.list_events(business_id, window_start, window_end, staff_member=staff)
    except Exception as e:
        return SentinelFinding(
            kind="find_slot", status="error",
            reason=f"provider.list_events failed: {e}",
        )

    windows = find_open_windows(busy, window_start, window_end, duration, buffer)

    # Slice each open window into back-to-back slots of `duration`.
    slots: list[dict] = []
    for w_start, w_end in windows:
        cursor = w_start
        while cursor + duration <= w_end and len(slots) < max_slots:
            slots.append({
                "start": cursor.isoformat(),
                "end": (cursor + duration).isoformat(),
                "staff_member": staff,
            })
            cursor += duration
        if len(slots) >= max_slots:
            break

    return SentinelFinding(
        kind="find_slot",
        status="ok" if slots else "no_availability",
        payload={"slots": slots},
        metadata={
            "n_slots": len(slots),
            "n_busy_events": len(busy),
            "duration_min": int(p["duration_min"]),
        },
        reason=(
            f"{len(slots)} slot(s) of {p['duration_min']}min across "
            f"{len(busy)} busy event(s)"
        ),
    )
