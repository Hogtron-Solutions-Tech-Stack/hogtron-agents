"""Ledger department head.

Internal-only financial agent. Layer 1 dispatch surface for piloted
ops; Layer 2 autonomous loop chains them via Claude.

Default model is Sonnet 4.6 — Ledger work is deterministic aggregation
plus light reasoning over numbers. Opus is overkill; Haiku is enough for
many directives but Sonnet is the right balance for the autonomous loop
when it needs to interpret results.
"""
from __future__ import annotations

from typing import Callable, Optional

from .briefs import LedgerBrief, LedgerAsset, LedgerKind
from .._shared.telemetry import TelemetrySink, NullSink, working
from . import _handlers, _autonomous


Handler = Callable[["Ledger", LedgerBrief], LedgerAsset]


class Ledger:
    NAME = "Ledger"

    def __init__(self, telemetry: Optional[TelemetrySink] = None):
        self.telemetry = telemetry or NullSink()
        self._handlers: dict[LedgerKind, Handler] = {
            "pnl_snapshot":    _do_pnl_snapshot,
            "pull_paypal":     _do_pull_paypal,
            "pull_anthropic":  _do_pull_anthropic,
            "pull_railway":    _do_pull_railway,
            "client_margin":   _do_client_margin,
            "ar_overview":     _do_ar_overview,
            "threshold_check": _do_threshold_check,
        }

    def build(self, brief: LedgerBrief) -> LedgerAsset:
        handler = self._handlers.get(brief.kind)
        if handler is None:
            raise ValueError(f"Ledger has no handler for kind={brief.kind!r}")
        with working(self.telemetry, self.NAME, f"build({brief.kind})"):
            return handler(self, brief)

    def register(self, kind: LedgerKind, handler: Handler) -> None:
        self._handlers[kind] = handler

    def run_autonomous(self, directive: str, *, anthropic_api_key: str,
                       context: Optional[dict] = None,
                       model: str = "claude-sonnet-4-6",
                       max_iterations: int = 6,
                       progress_callback=None, should_cancel=None):
        """Layer 2 — chain Ledger kinds in response to a directive.

        `context` is the same dict shape that handlers expect on
        LedgerBrief.context: supabase client + credentials for sources.
        It's forwarded into every brief the loop builds.
        """
        return _autonomous.run_autonomous(
            self, directive, anthropic_api_key=anthropic_api_key,
            context=context or {}, model=model,
            max_iterations=max_iterations,
            progress_callback=progress_callback,
            should_cancel=should_cancel,
        )


# --- Handler trampolines ------------------------------------------------

def _do_pnl_snapshot(self: Ledger, brief: LedgerBrief) -> LedgerAsset:
    return _handlers.pnl_snapshot(brief)


def _do_pull_paypal(self: Ledger, brief: LedgerBrief) -> LedgerAsset:
    return _handlers.pull_paypal(brief)


def _do_pull_anthropic(self: Ledger, brief: LedgerBrief) -> LedgerAsset:
    return _handlers.pull_anthropic(brief)


def _do_pull_railway(self: Ledger, brief: LedgerBrief) -> LedgerAsset:
    return _handlers.pull_railway(brief)


def _do_client_margin(self: Ledger, brief: LedgerBrief) -> LedgerAsset:
    return _handlers.client_margin(brief)


def _do_ar_overview(self: Ledger, brief: LedgerBrief) -> LedgerAsset:
    return _handlers.ar_overview(brief)


def _do_threshold_check(self: Ledger, brief: LedgerBrief) -> LedgerAsset:
    return _handlers.threshold_check(brief)
