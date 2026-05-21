"""Research department head.

One agent. One entrypoint: do(brief) → ResearchFinding. Dispatch table
matches the Creative shape: adding a kind is a 2-line change.

Constructed with optional dependencies (TMProvider, etc.) that handlers
need. Storage / caching is caller's concern — Research is stateless.
"""
from __future__ import annotations

from typing import Callable, Optional

from .briefs import ResearchBrief, ResearchFinding, ResearchKind
from .._shared.telemetry import TelemetrySink, NullSink, working
from .._shared.entitlements import require_agent_enabled
from . import (
    _ip_clear, _geo_audit, _platform_presence, _seo_audit,
    _cluster_concepts, _trend_signals, _find_leads,
    _autonomous,
)
from ._ip_clear import TMProvider

Handler = Callable[["Research", ResearchBrief], ResearchFinding]


class Research:
    NAME = "Research"

    def __init__(
        self,
        telemetry: Optional[TelemetrySink] = None,
        tm_provider: Optional[TMProvider] = None,
    ):
        self.telemetry = telemetry or NullSink()
        self.tm_provider = tm_provider
        self._handlers: dict[ResearchKind, Handler] = {
            "ip_clear": _do_ip_clear,
            "trend_signals": _do_trend_signals,
            "cluster_concepts": _do_cluster_concepts,
            "find_leads": _do_find_leads,
            "seo_audit": _do_seo_audit,
            "geo_audit": _do_geo_audit,
            "platform_presence": _do_platform_presence,
        }

    def do(self, brief: ResearchBrief) -> ResearchFinding:
        require_agent_enabled(brief.context, "research")
        handler = self._handlers.get(brief.kind)
        if handler is None:
            raise ValueError(f"Research has no handler for kind={brief.kind!r}")
        with working(self.telemetry, self.NAME, f"do({brief.kind})"):
            return handler(self, brief)

    def register(self, kind: ResearchKind, handler: Handler) -> None:
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
    ):
        """Chain Layer 1 kinds in response to a natural-language directive.

        Default is Sonnet 4.6 — saves ~5x vs Opus on routine audits / signal
        scans. The audit handlers themselves call Gemini Flash (free) or
        Haiku 4.5 internally, so the only Claude cost here is the reasoning
        loop. Override with model='claude-opus-4-7' for novel multi-step
        synthesis (cluster_concepts on a new market, etc.).

        Example:
            r = Research(tm_provider=...)
            result = r.run_autonomous(
                "Find 5 IP-clear shirt phrases for Father's Day this week",
                anthropic_api_key=...,
            )
            print(result.summary)
            print(f"cost ${result.cost_usd:.4f}, {result.iterations} iter")

        Returns AutonomousResult — see _autonomous.py for the full shape.
        """
        return _autonomous.run_autonomous(
            self, directive,
            anthropic_api_key=anthropic_api_key,
            model=model,
            max_iterations=max_iterations,
            progress_callback=progress_callback,
            should_cancel=should_cancel,
        )


# --- Handlers -----------------------------------------------------------

def _do_ip_clear(self: Research, brief: ResearchBrief) -> ResearchFinding:
    return _ip_clear.ip_clear(brief, tm_provider=self.tm_provider)


def _do_trend_signals(self: Research, brief: ResearchBrief) -> ResearchFinding:
    return _trend_signals.trend_signals(brief)


def _do_cluster_concepts(self: Research, brief: ResearchBrief) -> ResearchFinding:
    return _cluster_concepts.cluster_concepts(brief)


def _do_find_leads(self: Research, brief: ResearchBrief) -> ResearchFinding:
    return _find_leads.find_leads(brief)


def _do_seo_audit(self: Research, brief: ResearchBrief) -> ResearchFinding:
    return _seo_audit.seo_audit(brief)


def _do_geo_audit(self: Research, brief: ResearchBrief) -> ResearchFinding:
    return _geo_audit.geo_audit(brief)


def _do_platform_presence(self: Research, brief: ResearchBrief) -> ResearchFinding:
    return _platform_presence.platform_presence(brief)
