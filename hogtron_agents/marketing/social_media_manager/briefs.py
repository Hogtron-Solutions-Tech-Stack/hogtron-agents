"""HERALD: Social Media Manager — brief, post, and asset types.

The SMM is a specialist *inside* the Marketing (HERALD) department. It
produces drafts, captions, calendars, hashtag packs, and repurposed posts.
It never publishes. Publishing is ANVIL's job (Operations), and only after
approval.

Asset/brief shape mirrors the rest of HERALD so this can later be promoted
into MarketingKind dispatch — or split into its own agent — without
breaking callers.
"""
from __future__ import annotations

from typing import Literal, Any, Optional
from pydantic import BaseModel, Field


SocialKind = Literal[
    "content_calendar",  # N-day calendar of post slots across platforms
    "caption",           # platform-specific caption(s) for one post
    "repurpose",         # turn a source asset into M posts across N platforms
    "hashtag_pack",      # broad + niche + local hashtag bundles for a topic
    "brand_review",      # score a draft post against voice/audience/hooks/CTA
]


SocialPlatform = Literal[
    "instagram",
    "facebook",
    "linkedin",
    "x",
    "tiktok",
    "pinterest",
    "youtube_community",
]


SocialPostStatus = Literal[
    "draft",                # SMM produced; not yet reviewed
    "needs_graphic",        # caption ready, visual missing — handoff to FORGE
    "ready_for_approval",   # caption + visual ready; awaiting human approval
    "approved",             # human approved; ANVIL can publish
    "published",            # ANVIL has published it
]


SourceKind = Literal[
    "blog_post",
    "review",
    "photo",
    "offer",
    "faq",
    "case_study",
    "raw_note",
]


class GraphicRequest(BaseModel):
    """Seed for a CreativeBrief — when a post needs a visual, the SMM emits
    one of these. Caller hands it to FORGE (Creative) to render.

    Kept dict-loose on purpose: matches CreativeBrief.payload shape so the
    caller can pass it through with minimal translation.
    """
    concept: str
    aspect_ratio: str = "1:1"           # 1:1, 4:5, 9:16, 16:9
    style_notes: str = ""
    palette_hint: str = "hogtron"       # navy/cyan/gold by default
    required_text: Optional[str] = None  # text that must appear on the graphic


class PublishIntent(BaseModel):
    """Seed for an OperationsBrief — what ANVIL needs to publish this post.

    SMM never calls Operations directly. It just declares the intent so the
    caller (or an Overseer loop) can route an approved post to the right
    Operations handler later.
    """
    platform: SocialPlatform
    scheduled_for: Optional[str] = None   # ISO-8601; None = "publish now after approval"
    caption: str
    hashtags: list[str] = Field(default_factory=list)
    media_ref: Optional[str] = None       # file_path or URL once FORGE delivers


class SocialPost(BaseModel):
    """One scheduled-or-draftable post. Status drives the handoff chain:

      draft → (FORGE if needed) → needs_graphic → ready_for_approval
            → (human) → approved → (ANVIL) → published
    """
    platform: SocialPlatform
    caption: str
    hashtags: list[str] = Field(default_factory=list)
    status: SocialPostStatus = "draft"
    scheduled_for: Optional[str] = None        # ISO-8601 suggestion
    topic: Optional[str] = None
    format_hint: Optional[str] = None          # "reel", "carousel", "single-image", "text-only"
    graphic_request: Optional[GraphicRequest] = None
    publish_intent: Optional[PublishIntent] = None
    notes: Optional[str] = None                # rationale, CTA reasoning, etc.


class SocialBrief(BaseModel):
    kind: SocialKind
    payload: dict[str, Any]
    context: dict[str, Any] = Field(default_factory=dict)
    requester: Optional[str] = None


class BrandReviewScore(BaseModel):
    """Per-criterion score for a brand_review pass. 0-10 scale, 10 = on-brand."""
    voice_fit: int = Field(ge=0, le=10)
    audience_language: int = Field(ge=0, le=10)
    hook_strength: int = Field(ge=0, le=10)
    cta_quality: int = Field(ge=0, le=10)
    platform_fit: int = Field(ge=0, le=10)
    banned_term_hits: list[str] = Field(default_factory=list)
    soft_flag_hits: list[str] = Field(default_factory=list)
    overall: int = Field(ge=0, le=10)
    verdict: Literal["ship_it", "minor_edits", "rewrite", "reject"]
    rewrite_suggestions: list[str] = Field(default_factory=list)
    rationale: str


class SocialAsset(BaseModel):
    """Outbound result. Shape varies by kind:

    - content_calendar: posts = N slots; summary = strategy rationale
    - caption:          posts = 1..N variants of the same post
    - repurpose:        posts = M posts across the requested platforms
    - hashtag_pack:     posts empty; payload has tiered hashtag bundles
    - brand_review:     posts empty; payload has BrandReviewScore data
    """
    kind: SocialKind
    posts: list[SocialPost] = Field(default_factory=list)
    summary: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
