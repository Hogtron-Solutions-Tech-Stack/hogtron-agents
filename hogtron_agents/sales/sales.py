"""Sales department head.

One agent. One entrypoint: build(brief). Dispatches by kind. Closing motions
for a specific prospect — proposals, audit reports, follow-ups, quotes.
"""
from __future__ import annotations

from typing import Callable, Optional

from .briefs import SalesBrief, SalesAsset, SalesKind
from .._shared.telemetry import TelemetrySink, NullSink, working
from . import _aggregator_audit_report

Handler = Callable[["Sales", SalesBrief], SalesAsset]


class Sales:
    NAME = "Sales"

    def __init__(self, telemetry: Optional[TelemetrySink] = None):
        self.telemetry = telemetry or NullSink()
        self._handlers: dict[SalesKind, Handler] = {
            "proposal": _do_proposal,
            "aggregator_audit_report": _do_aggregator_audit_report,
            "follow_up": _do_follow_up,
            "pricing_quote": _do_pricing_quote,
            "contract": _do_contract,
        }

    def build(self, brief: SalesBrief) -> SalesAsset:
        handler = self._handlers.get(brief.kind)
        if handler is None:
            raise ValueError(f"Sales has no handler for kind={brief.kind!r}")
        with working(self.telemetry, self.NAME, f"build({brief.kind})"):
            return handler(self, brief)

    def register(self, kind: SalesKind, handler: Handler) -> None:
        self._handlers[kind] = handler


# --- Handlers -----------------------------------------------------------

def _do_aggregator_audit_report(self: Sales, brief: SalesBrief) -> SalesAsset:
    return _aggregator_audit_report.aggregator_audit_report(brief)


def _do_proposal(self: Sales, brief: SalesBrief) -> SalesAsset:
    """Port target: hogtron-dashboard proposals + reference_proposal_template.md.
    10-page proposal assembly: cover, snapshot, revenue, audits, mockup,
    packages, close. Pulls from Research findings + Creative assets + pricing."""
    raise NotImplementedError(
        "proposal pending migration from hogtron-dashboard proposal generator"
    )


def _do_follow_up(self: Sales, brief: SalesBrief) -> SalesAsset:
    """Net-new: draft a follow-up after no-response. No existing port source."""
    raise NotImplementedError("follow_up not yet implemented — net-new kind")


def _do_pricing_quote(self: Sales, brief: SalesBrief) -> SalesAsset:
    """Net-new: tiered quote given client size + scope. Pulls from
    reference_pricing.md (2026 tiers)."""
    raise NotImplementedError("pricing_quote not yet implemented — net-new kind")


def _do_contract(self: Sales, brief: SalesBrief) -> SalesAsset:
    """Net-new: contract template fill. No existing port source."""
    raise NotImplementedError("contract not yet implemented — net-new kind")
