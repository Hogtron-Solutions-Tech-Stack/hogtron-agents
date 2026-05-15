"""Sentinel department brief + finding types.

Sentinel is the concierge dept: scheduling, intake, comms, organizing.
Layer 1 is stateless — handlers take a SentinelBrief, return a
SentinelFinding. Callers (Hogtron-Concierge Node backend, CEO loop,
APScheduler jobs) own DB writes and side-effect commits.

Phase 0 scope: scheduling kinds only. Intake, comms, and organize kinds
will be added as their handlers come online (2-line dispatcher change
per kind, per the research dept template).
"""
from __future__ import annotations

from typing import Literal, Any, Optional
from pydantic import BaseModel, Field


SentinelKind = Literal[
    # --- Scheduling (Phase 1) -----------------------------------------
    "find_slot",         # query calendar(s), return open windows
    "book_appointment",  # write to calendar, return event id
    "reschedule",        # move an existing event
    "cancel",            # cancel an existing event
    "check_conflicts",   # availability check for a proposed window

    # --- Intake / Leads (Phase 2A) ------------------------------------
    "ingest_intake_form",  # validate + normalize a submitted form, return cleaned lead data
    "score_lead",          # rule-based hot/warm/cold triage

    # --- Planned, not yet wired ---------------------------------------
    # Intake (Phase 2B/C):  start_intake (when Flow D ships), route_inquiry,
    #                       summarize_intake
    # Comms (Phase 3, gated): send_confirmation_draft, send_confirmation,
    #                         send_reminder_draft, send_reminder,
    #                         send_followup_draft, send_followup,
    #                         escalate_to_human
    # Organize (Phase 4):   create_task, update_task, summarize_thread,
    #                       generate_brief
    # Payments (later, gated): quote_deposit
]


class SentinelBrief(BaseModel):
    """One job for Sentinel to do.

    payload: the inputs specific to the kind (slot window, contact id, etc.)
    context: caller-provided dependencies (calendar client, db conn, api keys).
             Handlers are stateless; everything they need comes through here.
    """
    kind: SentinelKind
    payload: dict[str, Any]
    context: dict[str, Any] = Field(default_factory=dict)
    requester: Optional[str] = None


class SentinelFinding(BaseModel):
    """Outbound result. `status` semantics depend on kind:

    - find_slot:           "ok" | "no_availability" | "error"
    - book_appointment:    "booked" | "conflict" | "error"
    - reschedule:          "rescheduled" | "conflict" | "not_found" | "error"
    - cancel:              "cancelled" | "not_found" | "error"
    - check_conflicts:     "clear" | "conflict" | "error"
    - ingest_intake_form:  "ok" | "validation_failed" | "error"
    - score_lead:          "ok" | "error"
    """
    kind: SentinelKind
    status: str
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    reason: Optional[str] = None
