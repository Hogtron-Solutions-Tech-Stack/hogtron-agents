"""Operations department brief + result types.

Operations *ships things*. Take an internal artifact, push it to an
external system (Printify, Etsy, Shopify, Pinterest, Railway), report back
what happened with external IDs and URLs.

Pattern note: Operations kinds are the natural seam where the autonomy
ladder rungs apply most directly — every kind here represents an action
with real-world consequences (a product appears on Etsy, a video gets
uploaded to YouTube, money may move). Layer 2/3 callers will gate these
behind risk thresholds (per ../docs/architecture.md autonomy ladder).
"""
from __future__ import annotations

from typing import Literal, Any, Optional
from pydantic import BaseModel, Field

OperationsKind = Literal[
    "printify_upload",   # Upload art -> create draft product (Factory)
    "publish_etsy",      # Push Printify draft to Etsy (Factory)
    "publish_shopify",   # Push to Shopify channel (Factory or Agency)
    "publish_pinterest", # Cross-post listing to Pinterest boards (Factory)
    "render_video",      # Ken Burns video from mockups via ffmpeg (Factory)
    "deploy_mockup",     # Push client mockup to Railway gallery (Agency)
    "deploy_proposal",   # Publish proposal to its share URL (Agency)
]


class OperationsBrief(BaseModel):
    kind: OperationsKind
    payload: dict[str, Any]
    context: dict[str, Any] = Field(default_factory=dict)
    requester: Optional[str] = None


class OperationsResult(BaseModel):
    """Outbound result. Operations actions hit external systems, so:

    - success: did the external action complete cleanly
    - external_id: ID assigned by the external system (Printify product id,
      Etsy listing id, Pinterest pin id, etc.)
    - external_url: where the artifact lives now
    - cost_estimate: rough USD cost of this single action (Printify is free,
      Etsy is $0.20/listing, ffmpeg is local, etc.) — Layer 3 needs this for
      budget caps
    """
    kind: OperationsKind
    success: bool
    external_id: Optional[str] = None
    external_url: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    cost_estimate_usd: float = 0.0
    error: Optional[str] = None
