"""Hashtag pack handler — tiered hashtag bundles for a topic and platform.

Returns three tiers per pack:
  - broad:  high-volume, high-competition. Use 1-2 per post.
  - niche:  mid-volume, focused. Use 3-5 per post.
  - local:  geo/community tags. Use 1-3 per post when location matters.

This is a utility kind. caption() and repurpose() can produce hashtags
inline, but hashtag_pack is the right call when you want a reusable bundle
for an entire campaign or content pillar.
"""
from __future__ import annotations

import os
from typing import Optional

from pydantic import BaseModel, Field

from ..._shared.claude_router import llm_available, route_messages_parse
from .briefs import SocialBrief, SocialAsset, SocialPlatform
from ._vault_loader import build_voice_context_block


class _HashtagPack(BaseModel):
    broad: list[str] = Field(min_length=3, max_length=8, description=(
        "High-volume, high-competition tags. Lowercase, no '#' prefix. "
        "Use 1-2 of these per post; they signal category but rarely drive "
        "discovery on their own."
    ))
    niche: list[str] = Field(min_length=5, max_length=15, description=(
        "Mid-volume, focused tags where your post can actually rank. "
        "These do the real discovery work."
    ))
    local: list[str] = Field(min_length=0, max_length=10, description=(
        "Geo/community tags for the locale provided. Empty list if no "
        "locale was given or the topic isn't local."
    ))
    keyword_phrases: list[str] = Field(min_length=2, max_length=10, description=(
        "Plain-English keyword phrases (NOT hashtags) for caption body, "
        "alt text, and SEO. e.g. 'small business marketing tampa'."
    ))
    rationale: str = Field(description=(
        "One sentence per tier: why these tags and not others."
    ))


SYSTEM_PROMPT = """You are HERALD: Social Media Manager building a hashtag
pack for a content pillar or campaign.

PRINCIPLES
- Lowercase, no leading '#' (it's added later). No spaces inside a tag.
- Avoid banned/shadowbanned tags (anything that's been used by 5M+ spam
  posts — they suppress reach).
- A great pack has FEW broad tags (signal only) and MANY niche tags
  (actual discovery). Local tags only when location is relevant.
- Tags should overlap with caption body keywords. Don't waste a tag on
  something that's not also implied in the copy.
- Keyword phrases are separate from hashtags — they live in the caption
  body / alt text / video transcript and drive search rankings on
  TikTok, YouTube, Pinterest, and increasingly Instagram."""


def hashtag_pack(brief: SocialBrief) -> SocialAsset:
    """Generate a tiered hashtag pack.

    brief.payload:
      topic (required) — the content pillar or campaign
      platform (required) — SocialPlatform (tag mix varies by platform)
      locale (optional) — e.g. "Tampa, FL" or "Atlanta metro"
      audience (optional)
    brief.context:
      anthropic_api_key (optional)
      model (optional, default claude-sonnet-4-6)
    """
    topic = brief.payload.get("topic")
    platform: Optional[SocialPlatform] = brief.payload.get("platform")
    if not topic or not platform:
        raise ValueError("hashtag_pack brief.payload must include 'topic' and 'platform'")

    key = brief.context.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY")
    if not llm_available(key):
        return SocialAsset(
            kind="hashtag_pack",
            metadata={"error": "No LLM backend configured"},
        )
    model = brief.context.get("model") or "claude-sonnet-4-6"
    locale = brief.payload.get("locale") or "no locale specified"
    audience = brief.payload.get("audience") or "unspecified"

    voice_context = brief.context.get("voice_context")
    if voice_context is None:
        # hashtag_pack only cares about audience-language for keyword phrases.
        voice_context = build_voice_context_block(
            platform=platform, include=("audience_language", "icp"),
        ) or "(none in vault)"

    user_prompt = (
        f"Topic: {topic}\n"
        f"Platform: {platform}\n"
        f"Locale: {locale}\n"
        f"Audience: {audience}\n\n"
        f"Voice context:\n{voice_context}\n\n"
        "Build the tiered hashtag pack + keyword phrases."
    )

    resp = route_messages_parse(
        agent="marketing.smm.hashtags",
        model=model,
        max_tokens=2500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
        output_format=_HashtagPack,
        api_key=key,
    )

    pack: _HashtagPack = resp.parsed_output

    def _clean(tags: list[str]) -> list[str]:
        return [t.lstrip("#").strip().lower().replace(" ", "") for t in tags if t.strip()]

    return SocialAsset(
        kind="hashtag_pack",
        posts=[],
        summary=pack.rationale,
        payload={
            "broad": _clean(pack.broad),
            "niche": _clean(pack.niche),
            "local": _clean(pack.local),
            "keyword_phrases": [p.strip() for p in pack.keyword_phrases if p.strip()],
        },
        metadata={
            "model": model,
            "topic": topic,
            "platform": platform,
            "locale": locale,
        },
    )
