"""GoogleCalendarProvider — real Google Calendar implementation of the
CalendarProvider Protocol.

Lives in the service layer (not the library) so the hogtron-agents
package itself doesn't pull google-api-python-client as a core dep.
Lazy-imported by services/sentinel/app.py when SENTINEL_CALENDAR_PROVIDER=google.

Auth model (single-tenant first):
  We use one OAuth user's refresh token to access one calendar. That's
  enough to validate Sentinel against a real calendar end-to-end (your
  admin Gmail). Multi-tenant (per-business OAuth) lands in a later
  phase — when it does, this class will be instantiated per-request
  with that tenant's credentials instead of pulled from env.

Env vars (set by the operator):
  GOOGLE_OAUTH_CLIENT_ID
  GOOGLE_OAUTH_CLIENT_SECRET
  GOOGLE_OAUTH_REFRESH_TOKEN  (minted via oauth_setup.py — one time)
  GOOGLE_CALENDAR_ID          (default: "primary")

CalendarProvider contract reminder:
  list_events(business_id, window_start, window_end, staff_member) -> list[CalendarEvent]
  create_event(event) -> CalendarEvent
  update_event(business_id, event_id, new_start, new_end) -> CalendarEvent
  cancel_event(business_id, event_id) -> CalendarEvent

In single-tenant mode `business_id` is ignored — all calls go to the
configured calendar. The interface keeps it for future per-tenant
routing.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from hogtron_agents.sentinel import CalendarEvent

# These imports are intentionally module-level — this whole module is
# only loaded when SENTINEL_CALENDAR_PROVIDER=google (app.py lazy import).
from google.oauth2.credentials import Credentials  # type: ignore
from googleapiclient.discovery import build  # type: ignore
from googleapiclient.errors import HttpError  # type: ignore


GOOGLE_SCOPES = ["https://www.googleapis.com/auth/calendar"]
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"


@dataclass
class GoogleCalendarProvider:
    """Single-tenant Google Calendar adapter."""
    client_id: str
    client_secret: str
    refresh_token: str
    calendar_id: str = "primary"

    @classmethod
    def from_env(cls) -> "GoogleCalendarProvider":
        missing = [v for v in (
            "GOOGLE_OAUTH_CLIENT_ID",
            "GOOGLE_OAUTH_CLIENT_SECRET",
            "GOOGLE_OAUTH_REFRESH_TOKEN",
        ) if not os.environ.get(v)]
        if missing:
            raise RuntimeError(
                "GoogleCalendarProvider needs env vars: " + ", ".join(missing)
                + ". Mint a refresh token with `python -m services.sentinel.oauth_setup`."
            )
        return cls(
            client_id=os.environ["GOOGLE_OAUTH_CLIENT_ID"],
            client_secret=os.environ["GOOGLE_OAUTH_CLIENT_SECRET"],
            refresh_token=os.environ["GOOGLE_OAUTH_REFRESH_TOKEN"],
            calendar_id=os.environ.get("GOOGLE_CALENDAR_ID", "primary"),
        )

    def _client(self):
        """Build a fresh API client. Credentials object handles token refresh
        internally on each request via the google-auth library."""
        creds = Credentials(
            token=None,  # forces refresh on first call
            refresh_token=self.refresh_token,
            token_uri=GOOGLE_TOKEN_URI,
            client_id=self.client_id,
            client_secret=self.client_secret,
            scopes=GOOGLE_SCOPES,
        )
        return build("calendar", "v3", credentials=creds, cache_discovery=False)

    # --- CalendarProvider methods ----------------------------------------

    def list_events(
        self,
        business_id: str,
        window_start: datetime,
        window_end: datetime,
        staff_member: Optional[str] = None,
    ) -> list[CalendarEvent]:
        # business_id ignored in single-tenant mode. staff_member is a
        # post-filter — Google Calendar's standard events endpoint
        # doesn't split by staff inherently; multi-staff support will
        # mean one calendar per staff member.
        svc = self._client()
        try:
            resp = svc.events().list(
                calendarId=self.calendar_id,
                timeMin=_to_rfc3339(window_start),
                timeMax=_to_rfc3339(window_end),
                singleEvents=True,
                orderBy="startTime",
                maxResults=250,
            ).execute()
        except HttpError as e:
            raise RuntimeError(f"google list events failed: {e}") from e

        out: list[CalendarEvent] = []
        for item in resp.get("items", []):
            if item.get("status") == "cancelled":
                continue
            start = _parse_g(item["start"])
            end = _parse_g(item["end"])
            if start is None or end is None:
                continue  # all-day events with date-only fields — skip for slot math
            ev_staff = (item.get("extendedProperties") or {}).get(
                "private", {}).get("staff_member")
            if staff_member and ev_staff != staff_member:
                continue
            out.append(CalendarEvent(
                event_id=item["id"],
                business_id=business_id,
                start=start, end=end,
                title=item.get("summary", ""),
                attendee_email=_first_attendee(item),
                attendee_name="",
                staff_member=ev_staff,
                notes=item.get("description", "") or "",
                status=item.get("status", "confirmed"),
            ))
        return out

    def create_event(self, event: CalendarEvent) -> CalendarEvent:
        body = {
            "summary": event.title,
            "description": event.notes or "",
            "start": {"dateTime": _to_rfc3339(event.start)},
            "end":   {"dateTime": _to_rfc3339(event.end)},
        }
        if event.attendee_email:
            body["attendees"] = [{
                "email": event.attendee_email,
                "displayName": event.attendee_name or event.attendee_email,
            }]
        if event.staff_member:
            body["extendedProperties"] = {
                "private": {"staff_member": event.staff_member},
            }
        try:
            created = self._client().events().insert(
                calendarId=self.calendar_id, body=body, sendUpdates="none",
            ).execute()
        except HttpError as e:
            raise RuntimeError(f"google insert failed: {e}") from e
        event.event_id = created["id"]
        return event

    def update_event(
        self,
        business_id: str,
        event_id: str,
        new_start: datetime,
        new_end: datetime,
    ) -> CalendarEvent:
        svc = self._client()
        try:
            existing = svc.events().get(
                calendarId=self.calendar_id, eventId=event_id,
            ).execute()
        except HttpError as e:
            if e.resp.status == 404:
                raise KeyError(f"event {event_id!r} not found") from e
            raise RuntimeError(f"google get failed: {e}") from e

        existing["start"] = {"dateTime": _to_rfc3339(new_start)}
        existing["end"] = {"dateTime": _to_rfc3339(new_end)}
        try:
            updated = svc.events().update(
                calendarId=self.calendar_id, eventId=event_id, body=existing,
                sendUpdates="none",
            ).execute()
        except HttpError as e:
            raise RuntimeError(f"google update failed: {e}") from e

        start = _parse_g(updated["start"])
        end = _parse_g(updated["end"])
        return CalendarEvent(
            event_id=updated["id"],
            business_id=business_id,
            start=start, end=end,
            title=updated.get("summary", ""),
            attendee_email=_first_attendee(updated),
            staff_member=(updated.get("extendedProperties") or {}).get(
                "private", {}).get("staff_member"),
            notes=updated.get("description", "") or "",
            status=updated.get("status", "confirmed"),
        )

    def cancel_event(self, business_id: str, event_id: str) -> CalendarEvent:
        svc = self._client()
        try:
            svc.events().delete(
                calendarId=self.calendar_id, eventId=event_id, sendUpdates="none",
            ).execute()
        except HttpError as e:
            if e.resp.status in (404, 410):
                raise KeyError(f"event {event_id!r} not found") from e
            raise RuntimeError(f"google delete failed: {e}") from e

        # Google delete doesn't return the event; synthesize a minimal cancelled record.
        return CalendarEvent(
            event_id=event_id,
            business_id=business_id,
            start=datetime.now(timezone.utc),
            end=datetime.now(timezone.utc),
            title="",
            status="cancelled",
        )


# --- helpers ------------------------------------------------------------

def _to_rfc3339(dt: datetime) -> str:
    """Google wants RFC3339 with timezone. Coerce naive to UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _parse_g(slot: dict) -> Optional[datetime]:
    """Parse a Google event start/end slot. None for date-only (all-day)."""
    s = slot.get("dateTime")
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def _first_attendee(item: dict) -> str:
    for a in item.get("attendees", []) or []:
        if a.get("email"):
            return a["email"]
    return ""
