"""Sales department brief + asset types.

Sales produces *closing motions* — content for a specific prospect with
intent to convert. Compare to Marketing, which is broadcast content for
many recipients through a channel.
"""
from __future__ import annotations

from typing import Literal, Any, Optional
from pydantic import BaseModel, Field

SalesKind = Literal[
    "proposal",                  # Full client proposal (10-page template)
    "aggregator_audit_report",   # Restaurant aggregator audit deliverable
    "follow_up",                 # Follow-up message after no-response
    "pricing_quote",             # Tiered quote given client size + scope
    "contract",                  # Fill in a contract template
]


class SalesBrief(BaseModel):
    kind: SalesKind
    payload: dict[str, Any]
    context: dict[str, Any] = Field(default_factory=dict)
    requester: Optional[str] = None


class SalesAsset(BaseModel):
    """Outbound result. Structure varies by kind:

    - proposal: payload has {sections, pricing_summary, executive_summary}
    - aggregator_audit_report: payload has full report dict (per_platform,
        projection, recommendations, competitive_intel, summary, meta)
    - follow_up: payload has {subject, body, tone}
    - pricing_quote: payload has {tiers, recommended_tier}
    - contract: payload has {document, fields_filled}
    """
    kind: SalesKind
    summary: Optional[str] = None  # one-line description of the deliverable
    payload: dict[str, Any] = Field(default_factory=dict)
    file_path: Optional[str] = None  # for assets rendered to disk (PDFs)
    email_draft: Optional[dict[str, Any]] = None  # subject/body if there's a send-ready draft
    metadata: dict[str, Any] = Field(default_factory=dict)
