"""CalendarProvider Protocol + MockCalendarProvider.

The Sentinel scheduling kinds (find_slot, book_appointment, etc.) are
calendar-agnostic — they reason about windows and events without
knowing whether the backing store is Google Calendar, Outlook, or a
local SQLite table. The CalendarProvider Protocol is the seam.

Real provider implementations (GoogleCalendarProvider, etc.) live in
the deployable service layer (`services/sentinel/providers/`) so the
library itself doesn't have to depend on google-api-python-client or
similar heavy clients.

MockCalendarProvider lives here because it has no external deps and is
useful for tests, local development, and the sidecar's "mock mode"
that lets you exercise the bridge without setting up OAuth.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol, Optional
import uuid


@dataclass
class CalendarEvent:
    """One event on a business's calendar."""
    event_id: str
    business_id: str
    start: datetime
    end: datetime
    title: str
    attendee_email: str = ""
    attendee_name: str = ""
    staff_member: Optional[str] = None
    notes: str = ""
    status: str = "confirmed"  # confirmed | cancelled


class CalendarProvider(Protocol):
    """Calendar I/O contract.

    Implementations must be safe to call concurrently per business_id.
    All datetimes are timezone-aware (UTC unless caller is explicit).
    """

    def list_events(
        self,
        business_id: str,
        window_start: datetime,
        window_end: datetime,
        staff_member: Optional[str] = None,
    ) -> list[CalendarEvent]:
        """Return all non-cancelled events overlapping [window_start, window_end)."""
        ...

    def create_event(self, event: CalendarEvent) -> CalendarEvent:
        """Write a new event. Implementations assign event_id if empty."""
        ...

    def update_event(
        self,
        business_id: str,
        event_id: str,
        new_start: datetime,
        new_end: datetime,
    ) -> CalendarEvent:
        """Move an event. Raises KeyError if event_id not found."""
        ...

    def cancel_event(self, business_id: str, event_id: str) -> CalendarEvent:
        """Mark an event cancelled. Raises KeyError if not found."""
        ...


# --- Mock implementation -----------------------------------------------

@dataclass
class MockCalendarProvider:
    """In-memory calendar. For tests, local dev, and the sidecar's mock mode.

    Holds events in a {business_id: {event_id: CalendarEvent}} dict.
    Pre-populate via seed_event() if you want fixtures in place.
    """
    _events: dict[str, dict[str, CalendarEvent]] = field(default_factory=dict)

    def seed_event(self, event: CalendarEvent) -> CalendarEvent:
        return self.create_event(event)

    def list_events(
        self,
        business_id: str,
        window_start: datetime,
        window_end: datetime,
        staff_member: Optional[str] = None,
    ) -> list[CalendarEvent]:
        biz = self._events.get(business_id, {})
        out = []
        for ev in biz.values():
            if ev.status == "cancelled":
                continue
            if ev.end <= window_start or ev.start >= window_end:
                continue
            if staff_member and ev.staff_member != staff_member:
                continue
            out.append(ev)
        out.sort(key=lambda e: e.start)
        return out

    def create_event(self, event: CalendarEvent) -> CalendarEvent:
        if not event.event_id:
            event.event_id = f"mock_{uuid.uuid4().hex[:12]}"
        self._events.setdefault(event.business_id, {})[event.event_id] = event
        return event

    def update_event(
        self,
        business_id: str,
        event_id: str,
        new_start: datetime,
        new_end: datetime,
    ) -> CalendarEvent:
        biz = self._events.get(business_id, {})
        ev = biz.get(event_id)
        if ev is None or ev.status == "cancelled":
            raise KeyError(f"event {event_id!r} not found for business {business_id!r}")
        ev.start = new_start
        ev.end = new_end
        return ev

    def cancel_event(self, business_id: str, event_id: str) -> CalendarEvent:
        biz = self._events.get(business_id, {})
        ev = biz.get(event_id)
        if ev is None:
            raise KeyError(f"event {event_id!r} not found for business {business_id!r}")
        ev.status = "cancelled"
        return ev


# --- Helpers shared across scheduling handlers --------------------------

def parse_iso(s: str) -> datetime:
    """Parse an ISO datetime. Accepts trailing Z (UTC)."""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def find_open_windows(
    busy: list[CalendarEvent],
    window_start: datetime,
    window_end: datetime,
    duration: timedelta,
    buffer: timedelta = timedelta(0),
) -> list[tuple[datetime, datetime]]:
    """Given busy events in a range, return open windows >= duration.

    Pure function — no I/O. Sorted by start time.
    """
    busy_sorted = sorted(busy, key=lambda e: e.start)
    cursor = window_start
    open_windows: list[tuple[datetime, datetime]] = []

    for ev in busy_sorted:
        slot_end = ev.start - buffer
        if slot_end - cursor >= duration:
            open_windows.append((cursor, slot_end))
        cursor = max(cursor, ev.end + buffer)

    if window_end - cursor >= duration:
        open_windows.append((cursor, window_end))

    return open_windows
