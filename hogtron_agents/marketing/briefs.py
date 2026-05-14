"""Marketing department brief + asset types.

Marketing produces *words that sell* — broadcast content meant for many
recipients through a channel. Compare to Sales, which produces closing
motions for a specific prospect.
"""
from __future__ import annotations

from typing import Literal, Any, Optional
from pydantic import BaseModel, Field

MarketingKind = Literal[
    "etsy_listing",     # Title (≤140) + description + 13 tags for a Printify product (Factory)
    "social_post",      # Pinterest pin / IG caption for a published listing (Factory + Agency)
    "blog_post",        # Long-form blog from a brief or topic (Agency)
    "review_response",  # Personalized response to a Google/Yelp review (Agency)
    "ad_copy",          # Etsy Ads / Google Ads short copy (Factory)
    "email_outreach",   # Cold outreach drafts to leads (Agency)
    # --- HERALD: Social Media Manager (specialist subpackage) -----------------
    # First-class kinds. Delegates to marketing/social_media_manager/. Brief +
    # asset shape is the SocialBrief / SocialAsset over there; the wrapper
    # handlers in marketing.py adapt MarketingBrief ↔ SocialBrief at the seam.
    "content_calendar", # N-day calendar of post slots across platforms
    "caption",          # Multi-platform caption variants with hook-formula variety
    "repurpose",        # Source asset → fan-out of platform-native posts
    "hashtag_pack",     # Broad + niche + local hashtag bundles
    "brand_review",     # Quality-gate score on a draft post
]


class MarketingBrief(BaseModel):
    kind: MarketingKind
    payload: dict[str, Any]
    context: dict[str, Any] = Field(default_factory=dict)
    requester: Optional[str] = None


class MarketingAsset(BaseModel):
    """Outbound result. Structure varies by kind:

    - etsy_listing: payload has {title, description, tags, seo_rationale}
    - social_post:  payload has {title, body, hashtags}
    - blog_post:    payload has {title, body, meta_description, slug}
    - review_response: payload has {body, tone}
    - ad_copy:      payload has {headline, body, cta}
    - email_outreach: payload has {subject, body}
    """
    kind: MarketingKind
    primary_text: Optional[str] = None  # the headline / title / main pitch
    payload: dict[str, Any] = Field(default_factory=dict)
    variants: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
