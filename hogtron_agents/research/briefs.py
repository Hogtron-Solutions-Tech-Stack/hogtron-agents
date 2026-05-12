"""Research department brief + finding types."""
from __future__ import annotations

from typing import Literal, Any, Optional
from pydantic import BaseModel, Field

ResearchKind = Literal[
    "ip_clear",            # blocklist + USPTO TM check on a phrase (Factory)
    "trend_signals",       # scrape Etsy/Pinterest/Reddit → raw_signals (Factory)
    "cluster_concepts",    # Claude clusters raw_signals → concepts + phrases (Factory)
    "find_leads",          # Google Places + OSM scrape by location (Agency)
    "seo_audit",           # score a domain on SEO factors (Agency)
    "geo_audit",           # score a domain on GEO factors (Agency)
    "platform_presence",   # aggregator audit — which platforms is a biz on (Agency)
]


class ResearchBrief(BaseModel):
    kind: ResearchKind
    payload: dict[str, Any]
    context: dict[str, Any] = Field(default_factory=dict)
    requester: Optional[str] = None


class ResearchFinding(BaseModel):
    """Outbound result. `status` semantics depend on kind:

    - ip_clear: "clear" | "blocked" | "tm_hit" | "error"
    - trend_signals: "ok" | "error"
    - cluster_concepts: "ok" | "error"
    - find_leads: "ok" | "error"
    - seo_audit / geo_audit: "ok" (score in payload) | "error"
    - platform_presence: "ok" (per-platform results in payload) | "error"
    """
    kind: ResearchKind
    status: str
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    reason: Optional[str] = None
