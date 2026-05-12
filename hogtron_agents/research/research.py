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
from . import _ip_clear
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
        handler = self._handlers.get(brief.kind)
        if handler is None:
            raise ValueError(f"Research has no handler for kind={brief.kind!r}")
        with working(self.telemetry, self.NAME, f"do({brief.kind})"):
            return handler(self, brief)

    def register(self, kind: ResearchKind, handler: Handler) -> None:
        self._handlers[kind] = handler


# --- Handlers -----------------------------------------------------------

def _do_ip_clear(self: Research, brief: ResearchBrief) -> ResearchFinding:
    return _ip_clear.ip_clear(brief, tm_provider=self.tm_provider)


def _do_trend_signals(self: Research, brief: ResearchBrief) -> ResearchFinding:
    """Port target: FactoryHQ/agents/researcher.py discover() + tools/etsy_search.py.
    Scrapes Etsy/Pinterest/Reddit → raw_signals."""
    raise NotImplementedError(
        "trend_signals pending migration from FactoryHQ/agents/researcher.py discover()"
    )


def _do_cluster_concepts(self: Research, brief: ResearchBrief) -> ResearchFinding:
    """Port target: FactoryHQ/agents/researcher.py synthesize().
    Claude clusters raw_signals into concepts + phrase candidates."""
    raise NotImplementedError(
        "cluster_concepts pending migration from FactoryHQ/agents/researcher.py synthesize()"
    )


def _do_find_leads(self: Research, brief: ResearchBrief) -> ResearchFinding:
    """Port target: hogtron-dashboard/tools/lead_scraper.py.
    Google Places API + OSM Overpass fallback by zip / city+state / county+state."""
    raise NotImplementedError(
        "find_leads pending migration from hogtron-dashboard/tools/lead_scraper.py"
    )


def _do_seo_audit(self: Research, brief: ResearchBrief) -> ResearchFinding:
    """Port target: hogtron-dashboard/tools/seo_audit.py."""
    raise NotImplementedError(
        "seo_audit pending migration from hogtron-dashboard/tools/seo_audit.py"
    )


def _do_geo_audit(self: Research, brief: ResearchBrief) -> ResearchFinding:
    """Port target: hogtron-dashboard/tools/geo_audit.py + deployed geo-auditor service."""
    raise NotImplementedError(
        "geo_audit pending migration from hogtron-dashboard/tools/geo_audit.py"
    )


def _do_platform_presence(self: Research, brief: ResearchBrief) -> ResearchFinding:
    """Port target: hogtron-dashboard/tools/aggregator_audit/. SerpAPI site-restricted
    Google queries to detect DoorDash/UberEats/GrubHub/Postmates listings."""
    raise NotImplementedError(
        "platform_presence pending migration from hogtron-dashboard/tools/aggregator_audit/"
    )
