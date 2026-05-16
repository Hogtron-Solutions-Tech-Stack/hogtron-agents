"""Sentinel department head — the HogTron concierge.

One agent. One entrypoint: do(brief) → SentinelFinding. Dispatch table
matches the Research shape: adding a kind is a 2-line change.

Sentinel handles scheduling, intake, comms, and organize work on behalf
of Hogtron-Concierge tenants (one config per business). All handlers
are stateless — caller (Concierge Node backend, CEO loop, APScheduler
job) supplies dependencies via brief.context and owns DB writes.

Approval-gate convention (autonomy rung 0):
- "send_*" and "publish_*" kinds always have a "*_draft" companion.
- Drafts return a SentinelFinding with the rendered message in payload.
- The caller is responsible for routing drafts to the approval queue
  before invoking the real send kind.
"""
from __future__ import annotations

from typing import Callable, Optional

from .briefs import SentinelBrief, SentinelFinding, SentinelKind
from ._calendar import CalendarProvider
from .._shared.telemetry import TelemetrySink, NullSink, working
from . import (
    _find_slot, _book_appointment, _reschedule, _cancel, _check_conflicts,
    _ingest_intake_form, _score_lead,
    _autonomous,
)

Handler = Callable[["Sentinel", SentinelBrief], SentinelFinding]


class Sentinel:
    NAME = "Sentinel"

    def __init__(
        self,
        telemetry: Optional[TelemetrySink] = None,
        calendar_provider: Optional[CalendarProvider] = None,
    ):
        """
        calendar_provider — default provider used when brief.context doesn't
        carry its own. Callers needing per-business providers (e.g. each
        tenant's own Google Calendar) should pass via brief.context instead;
        brief context wins on conflict.
        """
        self.telemetry = telemetry or NullSink()
        self.calendar_provider = calendar_provider
        self._handlers: dict[SentinelKind, Handler] = {
            "find_slot": _do_find_slot,
            "book_appointment": _do_book_appointment,
            "reschedule": _do_reschedule,
            "cancel": _do_cancel,
            "check_conflicts": _do_check_conflicts,
            "ingest_intake_form": _do_ingest_intake_form,
            "score_lead": _do_score_lead,
        }

    def do(self, brief: SentinelBrief) -> SentinelFinding:
        handler = self._handlers.get(brief.kind)
        if handler is None:
            raise ValueError(f"Sentinel has no handler for kind={brief.kind!r}")
        # Merge instance defaults into brief context (brief context wins).
        if self.calendar_provider is not None and "calendar_provider" not in brief.context:
            brief = brief.model_copy(update={
                "context": {**brief.context, "calendar_provider": self.calendar_provider},
            })
        with working(self.telemetry, self.NAME, f"do({brief.kind})"):
            return handler(self, brief)

    def register(self, kind: SentinelKind, handler: Handler) -> None:
        self._handlers[kind] = handler

    # --- Layer 2: autonomous reasoning loop -------------------------------

    def run_autonomous(
        self,
        directive: str,
        *,
        anthropic_api_key: str,
        model: str = "claude-sonnet-4-6",
        max_iterations: int = 10,
        progress_callback=None,
        should_cancel=None,
        max_cost_usd: Optional[float] = None,
    ):
        """Chain Layer 1 kinds in response to a natural-language directive.

        Default is Sonnet 4.6 — concierge work is mostly routine
        coordination (find a slot, book it, draft a confirmation), not
        novel synthesis. Override with 'claude-opus-4-7' for ambiguous
        intake triage or multi-party rescheduling.

        `max_cost_usd` caps the per-run spend. Concierge directives should
        typically cap at $0.05-0.10 — a tenant's chat shouldn't burn
        dollars on a single booking.

        Example:
            s = Sentinel(telemetry=...)
            result = s.run_autonomous(
                "Caller wants to reschedule appointment 482 to next Tuesday afternoon",
                anthropic_api_key=...,
                max_cost_usd=0.10,
            )
            print(result.summary)

        Returns AutonomousResult — see _autonomous.py for the full shape.
        """
        return _autonomous.run_autonomous(
            self, directive,
            anthropic_api_key=anthropic_api_key,
            model=model,
            max_iterations=max_iterations,
            progress_callback=progress_callback,
            should_cancel=should_cancel,
            max_cost_usd=max_cost_usd,
        )


# --- Handlers -----------------------------------------------------------

def _do_find_slot(self: Sentinel, brief: SentinelBrief) -> SentinelFinding:
    return _find_slot.find_slot(brief)


def _do_book_appointment(self: Sentinel, brief: SentinelBrief) -> SentinelFinding:
    return _book_appointment.book_appointment(brief)


def _do_reschedule(self: Sentinel, brief: SentinelBrief) -> SentinelFinding:
    return _reschedule.reschedule(brief)


def _do_cancel(self: Sentinel, brief: SentinelBrief) -> SentinelFinding:
    return _cancel.cancel(brief)


def _do_check_conflicts(self: Sentinel, brief: SentinelBrief) -> SentinelFinding:
    return _check_conflicts.check_conflicts(brief)


def _do_ingest_intake_form(self: Sentinel, brief: SentinelBrief) -> SentinelFinding:
    return _ingest_intake_form.ingest_intake_form(brief)


def _do_score_lead(self: Sentinel, brief: SentinelBrief) -> SentinelFinding:
    return _score_lead.score_lead(brief)
